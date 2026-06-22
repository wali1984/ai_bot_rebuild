"""Claude worker process for Spark closed-loop runtime."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from v2.backend.app.closed_loop.lane_registry import (
    all_claude_lanes,
    claude_lane_priority,
)
from v2.backend.app.closed_loop.lease_store.sqlite_store import SQLiteLeaseStore
from v2.backend.app.closed_loop.services.systemd_notify import (
    notify_ready,
    notify_status,
    notify_watchdog,
)


WORKER_SCRIPT = "claude_worklog/tools/agent_supervisor.py"
POLL_SECONDS = 5
HEARTBEAT_SECONDS = 1
STATE_DIR = (
    Path(os.environ.get("STATE_DIRECTORY") or ".")
    / "ai-bot-v2"
    / "closed-loop"
)


def _descriptor_payload(task: dict[str, Any]) -> dict[str, Any]:
    payload = task.get("payload_json")
    return payload if isinstance(payload, dict) else {}


def _safe_to_claim(task: dict[str, Any]) -> tuple[bool, str | None]:
    if task.get("lane_type") not in {"CLAUDE_IMPLEMENTATION", "CLAUDE_REMEDIATION"}:
        if task.get("agent") != "claude":
            return False, "non_claude_task"
    try:
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
    except Exception:
        return False, "invalid_safe_envelope"
    return True, None


def _write_task_descriptor(task: dict[str, Any]) -> Path:
    legacy_dir = (
        Path(__file__).resolve().parents[5]
        / "claude_worklog"
        / "final_readiness"
        / "v2_closed_loop_execution"
        / "latest"
        / "tasks"
    )
    legacy_dir.mkdir(parents=True, exist_ok=True)
    descriptor_path = legacy_dir / f"{task['task_id']}.json"
    descriptor = _descriptor_payload(task).copy()
    for key, value in task.items():
        if key != "payload_json" and key not in descriptor:
            descriptor[key] = value
    descriptor_path.write_text(json.dumps(descriptor, indent=2, sort_keys=True), encoding="utf-8")
    return descriptor_path


def _build_prompt(task: dict[str, Any]) -> str:
    payload = _descriptor_payload(task)
    base = task.get("prompt") or payload.get("prompt")
    if base:
        return str(base)
    return (
        f"Work on V2 closed-loop task {task.get('task_id')}. "
        "Do not modify legacy AI BOT directory. "
        "Do not call exchange mutation. "
        "Keep live_gate=blocked_human_only."
    )


def _run_child(
    task: dict[str, Any],
    timeout: int,
    store: SQLiteLeaseStore,
    worker_id: str,
    lease_id: str,
    lane_group: str,
) -> tuple[int, str]:
    repo_root = Path(__file__).resolve().parents[5]
    descriptor_path = _write_task_descriptor(task)
    cmd = [
        sys.executable,
        str(repo_root / WORKER_SCRIPT),
        "--task",
        str(descriptor_path.relative_to(repo_root)),
    ]
    start = time.time()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        return -1, str(exc)
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                return rc, "completed"
            if (time.time() - start) > timeout:
                os.killpg(proc.pid, signal.SIGTERM)
                return -1, "timeout"
            store.heartbeat_worker(
                worker_id,
                state="busy",
                lane_group=lane_group,
                worker_kind="claude",
                current_task_id=task["task_id"],
            )
            store.heartbeat_lease(lease_id)
            notify_watchdog()
            notify_status(f"CLAUDE executing {task['task_id']}")
            time.sleep(1)
    finally:
        try:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass


def execute_task(store: SQLiteLeaseStore, worker_id: str, claim: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    lease = claim["lease"]
    task = claim["task"]
    task_id = task["task_id"]
    safe_ok, reason = _safe_to_claim(task)
    if not safe_ok:
        store.complete_task(task_id, lease_id=lease["lease_id"], status="failed", failure_reason=reason)
        return {"action": "refused", "task_id": task_id, "reason": reason}

    store.heartbeat_lease(lease["lease_id"])
    store.heartbeat_worker(
        worker_id,
        state="busy",
        lane_group=lease["lane_group"],
        worker_kind=task.get("agent", "claude"),
        current_task_id=task_id,
    )
    rc, state = _run_child(
        task,
        timeout,
        store=store,
        worker_id=worker_id,
        lease_id=lease["lease_id"],
        lane_group=lease["lane_group"],
    )
    if state == "timeout":
        store.fail_task(task_id, lease_id=lease["lease_id"], reason="timeout")
        return {"action": "failed", "task_id": task_id, "returncode": -1}
    if rc == 0:
        store.complete_task(task_id, lease_id=lease["lease_id"], status="completed")
        return {"action": "completed", "task_id": task_id, "returncode": rc}
    store.fail_task(task_id, lease_id=lease["lease_id"], reason=f"returncode_{rc}")
    return {"action": "failed", "task_id": task_id, "returncode": rc}


def _idle_sleep(seconds: int, store: SQLiteLeaseStore, worker_id: str, lane_group: str) -> None:
    elapsed = 0
    while elapsed < seconds:
        store.heartbeat_worker(
            worker_id,
            state="idle_ready",
            lane_group=lane_group,
            worker_kind="claude",
            current_task_id=None,
        )
        notify_watchdog()
        notify_status(f"CLAUDE idle_ready lane={lane_group}")
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
    summary: dict[str, Any] = {
        "worker_id": worker_id,
        "iterations": 0,
        "completed": 0,
        "failed": 0,
        "refused": 0,
        "idle_cycles": 0,
    }

    claude_lanes = [cfg.lane_group for cfg in all_claude_lanes()]
    if lane_group:
        claude_lanes = [lane_group]

    notify_ready()
    notify_status(f"CLAUDE worker {worker_id} starting lane={lane_group or 'runtime-claude'}")
    state = "idle_ready"
    if lane_group is None:
        lane_group = "runtime-claude"
    for lane in claude_lane_priority():
        if lane_group is not None and lane != lane_group:
            continue
        store.upsert_worker(
            {
                "worker_id": worker_id,
                "worker_kind": "claude",
                "lane_group": lane,
                "pid": os.getpid(),
                "status": "active",
                "payload_json": {"state": state},
            }
        )

    while max_iterations is None or summary["iterations"] < max_iterations:
        summary["iterations"] += 1
        claim = None
        for lane in claude_lane_priority():
            if lane_group is not None and lane != lane_group:
                continue
            if lane not in claude_lanes:
                continue
            claim = store.claim_task(worker_id=worker_id, lane_group=lane, worker_kind="claude")
            if claim:
                break
        if claim is None:
            summary["idle_cycles"] += 1
            _idle_sleep(POLL_SECONDS, store, worker_id, lane_group or claude_lanes[0])
            notify_status("CLAUDE idle - waiting for eligible tasks")
            continue

        store.heartbeat_worker(
            worker_id,
            state="busy",
            lane_group=claim["lease"]["lane_group"],
            worker_kind="claude",
            current_task_id=claim["task"]["task_id"],
        )
        result = execute_task(
            store,
            worker_id,
            claim,
            timeout=task_timeout_seconds,
        )
        if result["action"] == "completed":
            summary["completed"] += 1
        elif result["action"] == "refused":
            summary["refused"] += 1
        else:
            summary["failed"] += 1
        store.heartbeat_worker(
            worker_id,
            state="post_task",
            lane_group=claim["lease"]["lane_group"],
            worker_kind="claude",
            current_task_id=None,
        )
        if max_iterations is None:
            time.sleep(0.1)

    store.heartbeat_worker(
        worker_id,
        state="stopped",
        lane_group=lane_group or "runtime-claude",
        worker_kind="claude",
        current_task_id=None,
    )
    notify_status("CLAUDE worker stopped")
    try:
        store.stale_lease_reclaim()
    except Exception:
        pass
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
