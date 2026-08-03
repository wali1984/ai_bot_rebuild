"""Compatibility wrapper for the Spark Codex worker.

The default CLI delegates to Spark.  Imported legacy callers and
``LEASE_BACKEND=file`` use the file-backed worker loop kept here for rollback
and backward compatibility.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT_FOR_IMPORT))

from v2.backend.app.closed_loop.workers.codex_worker import (
    main as _spark_main,
    run_review_task as _spark_run_review_task,
)

import v2_closed_loop_worker_pool as pool
import v2_codex_review_runner as review_runner
from v2_closed_loop_lifecycle import read_json, utc_iso, write_json_atomic


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


def execute_review(
    worker_id: str,
    claim: dict[str, Any],
    executor: dict[str, Any],
    *,
    timeout: int = 300,
) -> dict[str, Any]:
    """Execute one legacy file-backed Codex review lease with heartbeats."""

    lease = claim["lease"]
    task = claim.get("task") or {}
    task_id = str(lease["task_id"])
    task_path = _task_path(claim)

    if not executor.get("available"):
        pool.write_worker_heartbeat(
            worker_id,
            pool.LANE_TYPE_CODEX,
            state="blocked_executor",
            current_task_id=task_id,
            extra={"blocker": "CODEX_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED"},
        )
        _mark_task(
            task_path,
            {
                "status": "blocked_operator_required",
                "operator_required_reason": "CODEX_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED",
            },
        )
        pool.update_lease(
            lease["lease_id"],
            status="blocked_operator_required",
            heartbeat=True,
            blocker="CODEX_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED",
        )
        return {
            "action": "operator_required",
            "task_id": task_id,
            "reason": "CODEX_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED",
        }

    def _heartbeat() -> None:
        pool.write_worker_heartbeat(
            worker_id,
            pool.LANE_TYPE_CODEX,
            state="busy",
            current_task_id=task_id,
            extra={"child_review_in_progress": True},
        )
        pool.update_lease(lease["lease_id"], status="running", heartbeat=True)

    _heartbeat()
    result = review_runner.run_codex_review(
        task_path,
        task,
        executor,
        dry_run=False,
        timeout=timeout,
        heartbeat_callback=_heartbeat,
        heartbeat_interval=1,
    )
    verdict = str(result.get("verdict") or "")
    action = result.get("action")
    if action == "completed" or verdict.endswith("_PASS") or verdict == "CURRENT_CODEX_PASS":
        _mark_task(task_path, {"status": "completed", "completed_at": utc_iso(), "codex_verdict": verdict})
        pool.update_lease(lease["lease_id"], status="completed", heartbeat=True, verdict=verdict)
        return {"action": "completed", "task_id": task_id, "verdict": verdict}

    _mark_task(
        task_path,
        {
            "status": "failed",
            "codex_verdict": verdict or "CODEX_REVIEW_FAILED",
            "fail_blockers": result.get("fail_blockers") or [],
        },
    )
    pool.update_lease(
        lease["lease_id"],
        status="failed",
        heartbeat=True,
        verdict=verdict or "CODEX_REVIEW_FAILED",
    )
    return {"action": "failed", "task_id": task_id, "verdict": verdict}


def run_worker(
    worker_id: str,
    *,
    max_iterations: int | None = None,
    task_timeout: int | None = None,
    task_timeout_seconds: int = 300,
    lane_group: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Run the legacy file-backed Codex worker loop."""

    del lane_group, db_path
    timeout = int(task_timeout if task_timeout is not None else task_timeout_seconds)
    executor = review_runner.discover_codex_executor()
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
            pool.LANE_TYPE_CODEX,
            state="blocked_executor",
            extra={"blocker": "CODEX_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED"},
        )
        summary["operator_required"] += 1
        return summary

    while max_iterations is None or summary["iterations"] < max_iterations:
        summary["iterations"] += 1
        claim = pool.claim_next_task(worker_id, (pool.LANE_TYPE_CODEX, pool.LANE_TYPE_TAKEOVER))
        if claim is None:
            summary["idle_cycles"] += 1
            pool.write_worker_heartbeat(worker_id, pool.LANE_TYPE_CODEX, state="idle_ready")
            time.sleep(1)
            continue
        result = execute_review(worker_id, claim, executor, timeout=timeout)
        if result.get("action") == "completed":
            summary["completed"] += 1
        elif result.get("action") == "operator_required":
            summary["operator_required"] += 1
        else:
            summary["failed"] += 1
        pool.write_worker_heartbeat(worker_id, pool.LANE_TYPE_CODEX, state="post_task")

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


run_review_task = _spark_run_review_task

__all__ = [
    "main",
    "run_worker",
    "execute_review",
    "run_review_task",
    "time",
]


if __name__ == "__main__":
    raise SystemExit(main())
