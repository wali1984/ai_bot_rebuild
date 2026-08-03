"""Compatibility wrapper for the Spark Claude worker.

The executable delegates to the first-class Spark worker by default.  The
legacy file-backed API remains available for existing tests, queue tools, and
``LEASE_BACKEND=file`` rollback.
"""

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

REPO_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT_FOR_IMPORT))

from v2.backend.app.closed_loop.workers.claude_worker import (
    _safe_to_claim as _spark_safe_to_claim,
    main as _spark_main,
)

import v2_claude_task_runner as task_runner
import v2_closed_loop_worker_pool as pool
from v2_closed_loop_lifecycle import REPO_ROOT, read_json, utc_iso, write_json_atomic

_safe_to_claim = _spark_safe_to_claim


def _task_path(claim: dict[str, Any]) -> Path:
    raw = claim.get("task_path")
    if raw:
        return Path(raw)
    return pool.TASKS_DIR / f"{claim['lease']['task_id']}.json"


def _mark_task(path: Path, updates: dict[str, Any]) -> dict[str, Any]:
    task = read_json(path)
    if not isinstance(task, dict):
        task = {}
    task.update(updates)
    task["updated_at"] = utc_iso()
    write_json_atomic(path, task)
    return task


def _child_command(claim: dict[str, Any], executor: dict[str, Any]) -> list[str]:
    task = claim.get("task") or {}
    prompt = task.get("prompt") or (
        f"Work on V2 closed-loop task {task.get('task_id')}. "
        "Do not modify legacy. Do not call exchange mutation. "
        "Keep live_gate=blocked_human_only and live_symbols=[]."
    )
    if executor.get("executor") == "claude_cli" and executor.get("command_probe"):
        return [str(executor["command_probe"][0]), "-p", str(prompt)]
    return list(executor.get("command_probe") or [sys.executable, "-c", "pass"])


def execute_task(
    worker_id: str,
    claim: dict[str, Any],
    executor: dict[str, Any],
    *,
    timeout: int = 300,
) -> dict[str, Any]:
    """Execute one legacy file-backed Claude lease with durable heartbeats."""

    lease = claim["lease"]
    task = claim.get("task") or {}
    task_id = str(lease["task_id"])
    task_path = _task_path(claim)

    if not executor.get("available"):
        pool.write_worker_heartbeat(
            worker_id,
            pool.LANE_TYPE_CLAUDE,
            state="blocked_executor",
            current_task_id=task_id,
            extra={"blocker": task_runner.CLAUDE_EXECUTOR_NOT_AVAILABLE},
        )
        _mark_task(
            task_path,
            {
                "status": "blocked_operator_required",
                "operator_required_reason": task_runner.CLAUDE_EXECUTOR_NOT_AVAILABLE,
            },
        )
        pool.update_lease(
            lease["lease_id"],
            status="blocked_operator_required",
            heartbeat=True,
            blocker=task_runner.CLAUDE_EXECUTOR_NOT_AVAILABLE,
        )
        return {
            "action": "operator_required",
            "task_id": task_id,
            "reason": task_runner.CLAUDE_EXECUTOR_NOT_AVAILABLE,
        }

    cmd = _child_command(claim, executor)
    started = time.time()
    proc: subprocess.Popen[Any] | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        while True:
            pool.write_worker_heartbeat(
                worker_id,
                pool.LANE_TYPE_CLAUDE,
                state="busy",
                current_task_id=task_id,
                extra={"child_pid": proc.pid},
            )
            pool.update_lease(lease["lease_id"], status="running", heartbeat=True)
            polled = proc.poll()
            if polled is not None:
                rc = int(polled)
                break
            if time.time() - started > timeout:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except OSError:
                    proc.terminate()
                rc = -1
                break
            time.sleep(1)
    except OSError as exc:
        _mark_task(task_path, {"status": "failed", "failure_reason": str(exc)})
        pool.update_lease(lease["lease_id"], status="failed", heartbeat=True, failure_reason=str(exc))
        return {"action": "failed", "task_id": task_id, "reason": str(exc)}
    finally:
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()

    if rc == 0:
        _mark_task(task_path, {"status": "completed", "completed_at": utc_iso()})
        pool.update_lease(lease["lease_id"], status="completed", heartbeat=True, returncode=rc)
        return {"action": "completed", "task_id": task_id, "returncode": rc}
    _mark_task(task_path, {"status": "failed", "failure_reason": f"returncode_{rc}"})
    pool.update_lease(lease["lease_id"], status="failed", heartbeat=True, returncode=rc)
    return {"action": "failed", "task_id": task_id, "returncode": rc}


def run_worker(
    worker_id: str,
    *,
    max_iterations: int | None = None,
    task_timeout: int | None = None,
    task_timeout_seconds: int = 300,
    lane_group: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Run the legacy file-backed Claude worker loop.

    ``lane_group`` and ``db_path`` are accepted for Spark signature
    compatibility; imported legacy callers use the file-backed path.
    """

    del lane_group, db_path
    timeout = int(task_timeout if task_timeout is not None else task_timeout_seconds)
    executor = task_runner.discover_claude_executor()
    summary = {
        "worker_id": worker_id,
        "iterations": 0,
        "completed": 0,
        "failed": 0,
        "operator_required": 0,
        "idle_cycles": 0,
    }

    if not executor.get("available"):
        pool.write_worker_heartbeat(
            worker_id,
            pool.LANE_TYPE_CLAUDE,
            state="blocked_executor",
            extra={"blocker": task_runner.CLAUDE_EXECUTOR_NOT_AVAILABLE},
        )
        summary["operator_required"] += 1
        return summary

    while max_iterations is None or summary["iterations"] < max_iterations:
        summary["iterations"] += 1
        claim = pool.claim_next_task(
            worker_id,
            (pool.LANE_TYPE_CLAUDE, pool.LANE_TYPE_REMEDIATION),
        )
        if claim is None:
            summary["idle_cycles"] += 1
            pool.write_worker_heartbeat(worker_id, pool.LANE_TYPE_CLAUDE, state="idle_ready")
            time.sleep(1)
            continue

        result = execute_task(worker_id, claim, executor, timeout=timeout)
        if result.get("action") == "completed":
            summary["completed"] += 1
        elif result.get("action") == "operator_required":
            summary["operator_required"] += 1
        else:
            summary["failed"] += 1
        pool.write_worker_heartbeat(worker_id, pool.LANE_TYPE_CLAUDE, state="post_task")

    return summary


def _file_backend_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--task-timeout", type=int, default=None)
    parser.add_argument("--task-timeout-seconds", type=int, default=300)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    summary = run_worker(
        args.worker_id,
        max_iterations=args.max_iterations,
        task_timeout=args.task_timeout,
        task_timeout_seconds=args.task_timeout_seconds,
    )
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    if os.environ.get("LEASE_BACKEND") == "file":
        return _file_backend_main(argv)
    return _spark_main(argv)


__all__ = ["main", "run_worker", "execute_task", "_safe_to_claim", "subprocess", "time"]


if __name__ == "__main__":
    raise SystemExit(main())
