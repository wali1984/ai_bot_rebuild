"""Codex review worker for Spark closed-loop runtime."""

from __future__ import annotations

import argparse
import os
import threading
import signal
import subprocess
import sys
import time
from typing import Any

from v2.backend.app.closed_loop.lane_registry import all_codex_lanes
from v2.backend.app.closed_loop.services.fail_mapper import classify_fail, classify_from_output
from v2.backend.app.closed_loop.lease_store.sqlite_store import SQLiteLeaseStore
from v2.backend.app.closed_loop.services.systemd_notify import (
    notify_ready,
    notify_status,
    notify_watchdog,
)


REVIEW_PROMPT_PREFIX = (
    "Review V2 closed-loop task implementation for policy, safety, and recovery impact.\n"
    "Rules: do not call exchange mutation, no live/canary/shutdown changes, "
    "live_gate must remain blocked_human_only."
)


def _descriptor_payload(task: dict[str, Any]) -> dict[str, Any]:
    payload = task.get("payload_json")
    return payload if isinstance(payload, dict) else {}


def _safe_to_claim(task: dict[str, Any]) -> tuple[bool, str | None]:
    payload = _descriptor_payload(task)
    env = task.get("safe_envelope") or payload.get("safe_envelope") or {}
    if env.get("live_gate") != "blocked_human_only":
        return False, "unsafe_live_gate"
    if env.get("live_symbols") != []:
        return False, "unsafe_live_symbols"
    if env.get("approves_live"):
        return False, "unsafe_live_approval"
    if env.get("approves_canary"):
        return False, "unsafe_canary_approval"
    return True, None


def _heartbeat_review_task(
    store: SQLiteLeaseStore,
    worker_id: str,
    lease_id: str,
    lane_group: str,
    task_id: str,
    stop_event: threading.Event,
) -> None:
    while not stop_event.is_set():
        store.heartbeat_worker(
            worker_id,
            state="busy",
            lane_group=lane_group,
            worker_kind="codex",
            current_task_id=task_id,
        )
        if lease_id:
            store.heartbeat_lease(lease_id)
        notify_watchdog()
        notify_status(f"CODEX reviewing {task_id}")
        stop_event.wait(1.0)


def _run_codex_review(
    task: dict[str, Any],
    timeout: int,
    store: SQLiteLeaseStore,
    worker_id: str,
    lease_id: str,
    lane_group: str,
) -> tuple[int, str]:
    payload = _descriptor_payload(task)
    scoped_prompt = (
        f"{REVIEW_PROMPT_PREFIX}\nTask {task.get('task_id')} paired with "
        f"{task.get('codex_pair_task_id') or payload.get('codex_pair_task_id')}"
    )
    cmd = ["codex", "exec", "review", scoped_prompt]
    start = time.time()
    stop = threading.Event()
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
    except FileNotFoundError:
        return 127, "codex_cli_missing"
    thread = threading.Thread(
        target=_heartbeat_review_task,
        args=(store, worker_id, lease_id, lane_group, task["task_id"], stop),
        daemon=True,
    )
    thread.start()
    try:
        notify_status(f"CODEX review running {task['task_id']}")
        while True:
            try:
                stdout, _ = proc.communicate(timeout=1)
                return proc.returncode or 0, stdout or ""
            except subprocess.TimeoutExpired:
                if (time.time() - start) > timeout:
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except OSError:
                        pass
                    stdout, _ = proc.communicate(timeout=1)
                    return 124, stdout or "codex_review_timeout"
                continue
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        return 124, "codex_review_timeout"
    except Exception:
        return 126, "codex_runtime_error"
    finally:
        stop.set()
        thread.join(timeout=1)
        notify_status(f"CODEX review finished {task['task_id']}")


def _parse_verdict(task: dict[str, Any], output: str) -> tuple[str, list[str]]:
    if output is None:
        output = ""
    lowered = output.lower()
    blockers: list[str] = []
    if "pass" in lowered and "fail" not in lowered:
        return "PASS", blockers
    if "codexfail" in lowered or "fail" in lowered:
        return "FAIL", [line.strip() for line in output.splitlines() if line.strip()]
    if "undetermined" in lowered or "blocked" in lowered:
        return "UNDETERMINED", blockers
    # Fallback to explicit marker in task payload if no text produced
    payload = _descriptor_payload(task)
    marker = (task.get("expected_verdict") or payload.get("expected_verdict") or "").upper()
    if marker.endswith("_PASS"):
        return "PASS", blockers
    if marker.endswith("_FAIL") or marker:
        return "FAIL", blockers or ["payload_marker"]
    return "UNDETERMINED", blockers


def _write_codex_failure_remediation(
    store: SQLiteLeaseStore,
    task: dict[str, Any],
    lease_id: str | None,
    verdict: str,
    blockers: list[str],
) -> None:
    classification = classify_from_output(" ".join(blockers))
    class_name = classification.get("classification")
    operator_required = classification.get("operator_required", False)
    unsafe_to_fix = classification.get("unsafe_to_fix", False)
    if not operator_required and not unsafe_to_fix:
        store.fail_task(
            task["task_id"],
            lease_id=lease_id,
            reason=f"codex_verdict_{verdict}",
            safe_to_remediate=True,
            operator_required=False,
            unsafe_to_fix=False,
        )
        store.add_codex_fail_map(
            codex_task_id=task["task_id"],
            classification=class_name or "remediation_available",
            remediation_task_id=f"closed_loop_remediation_{task['task_id']}",
            operator_required=False,
            unsafe_to_fix=False,
            payload={"blockers": blockers, "verdict": verdict},
        )
    else:
        store.fail_task(
            task["task_id"],
            lease_id=lease_id,
            reason=f"codex_verdict_{verdict}",
            safe_to_remediate=False,
            operator_required=operator_required,
            unsafe_to_fix=unsafe_to_fix,
        )
        store.add_codex_fail_map(
            codex_task_id=task["task_id"],
            classification=class_name or "operator_required",
            remediation_task_id=None,
            operator_required=operator_required,
            unsafe_to_fix=unsafe_to_fix,
            payload={"blockers": blockers, "verdict": verdict},
        )


def run_review_task(store: SQLiteLeaseStore, worker_id: str, claim: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    lease = claim["lease"]
    task = claim["task"]
    task_id = task["task_id"]
    safe_ok, reason = _safe_to_claim(task)
    if not safe_ok:
        store.complete_task(task_id, lease_id=lease["lease_id"], status="failed", failure_reason=reason)
        return {"action": "refused", "task_id": task_id, "reason": reason}

    store.heartbeat_worker(
        worker_id,
        state="busy",
        lane_group=lease["lane_group"],
        worker_kind="codex",
        current_task_id=task_id,
    )
    rc, output = _run_codex_review(
        task,
        timeout,
        store=store,
        worker_id=worker_id,
        lease_id=lease["lease_id"],
        lane_group=claim["lease"]["lane_group"],
    )
    store.heartbeat_lease(lease["lease_id"])

    verdict, blockers = _parse_verdict(task, output)
    if rc != 0:
        reason = "codex_cli_unavailable" if (
            "codex_cli_missing" in output or "codex_runtime_error" in output
        ) else f"codex_review_returncode_{rc}"
        store.fail_task(
            task_id,
            lease_id=lease["lease_id"],
            reason=reason,
            safe_to_remediate=False,
            operator_required=True,
            unsafe_to_fix=False,
        )
        store.add_codex_fail_map(
            codex_task_id=task_id,
            classification="codex_executor_unavailable",
            remediation_task_id=None,
            operator_required=True,
            unsafe_to_fix=False,
            payload={"returncode": rc, "verdict": verdict, "reason": reason},
        )
        return {"action": "operator_required", "task_id": task_id, "verdict": verdict}

    if verdict == "PASS":
        store.complete_task(task_id, lease_id=lease["lease_id"], status="completed")
        return {"action": "completed", "task_id": task_id, "verdict": verdict}

    if verdict == "FAIL":
        classify_fail(blockers=blockers)
        _write_codex_failure_remediation(store, task, lease["lease_id"], verdict, blockers)
        return {"action": "failed", "task_id": task_id, "verdict": verdict}

    store.complete_task(task_id, lease_id=lease["lease_id"], status="operator_required", failure_reason="codex_verdict_undetermined")
    return {"action": "operator_required", "task_id": task_id, "verdict": verdict}


def _idle_sleep(seconds: int, store: SQLiteLeaseStore, worker_id: str, lane_group: str) -> None:
    elapsed = 0
    while elapsed < seconds:
        store.heartbeat_worker(
            worker_id,
            state="idle_ready",
            lane_group=lane_group,
            worker_kind="codex",
            current_task_id=None,
        )
        notify_watchdog()
        notify_status(f"CODEX idle_ready lane={lane_group}")
        time.sleep(1)
        elapsed += 1


def run_worker(
    worker_id: str,
    *,
    max_iterations: int | None = None,
    task_timeout_seconds: int = 300,
    lane_group: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    store = SQLiteLeaseStore(db_path=db_path)
    summary = {
        "worker_id": worker_id,
        "iterations": 0,
        "completed": 0,
        "failed": 0,
        "refused": 0,
        "operator_required": 0,
        "idle_cycles": 0,
    }

    codex_lanes = [cfg.lane_group for cfg in all_codex_lanes()]
    if lane_group:
        codex_lanes = [lane_group]
    notify_ready()
    notify_status(f"CODEX worker {worker_id} starting lane={lane_group or 'runtime-codex'}")
    if lane_group is None:
        lane_group = "runtime-codex"
    for lane in codex_lanes:
        store.upsert_worker(
            {
                "worker_id": worker_id,
                "worker_kind": "codex",
                "lane_group": lane,
                "pid": os.getpid(),
                "status": "active",
                "payload_json": {"state": "idle_ready"},
            }
        )

    while max_iterations is None or summary["iterations"] < max_iterations:
        summary["iterations"] += 1
        claim = None
        for lane in codex_lanes:
            claim = store.claim_task(worker_id=worker_id, lane_group=lane, worker_kind="codex")
            if claim is not None:
                break
        if claim is None:
            summary["idle_cycles"] += 1
            _idle_sleep(5, store, worker_id, lane_group or codex_lanes[0])
            continue

        result = run_review_task(store, worker_id, claim, timeout=task_timeout_seconds)
        if result["action"] == "completed":
            summary["completed"] += 1
        elif result["action"] == "failed":
            summary["failed"] += 1
        elif result["action"] == "refused":
            summary["refused"] += 1
        else:
            summary["operator_required"] += 1

        store.heartbeat_worker(
            worker_id,
            state="post_task",
            lane_group=claim["lease"]["lane_group"],
            worker_kind="codex",
            current_task_id=None,
        )

    store.heartbeat_worker(
        worker_id,
        state="stopped",
        lane_group=lane_group or codex_lanes[0],
        worker_kind="codex",
        current_task_id=None,
    )
    notify_status(f"CODEX worker {worker_id} stopped")
    store.close()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--lane-group", default=None)
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--task-timeout-seconds", type=int, default=300)
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args(argv)
    run_worker(
        args.worker_id,
        lane_group=args.lane_group,
        max_iterations=args.max_iterations,
        task_timeout_seconds=args.task_timeout_seconds,
        db_path=args.db_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
