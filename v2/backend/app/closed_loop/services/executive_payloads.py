"""Executive and operator payloads sourced from the SQLite truth plane."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.closed_loop.lease_store.sqlite_store import SQLiteLeaseStore

REPO_ROOT = Path(__file__).resolve().parents[5]
WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_codex_spark_parallel_closed_loop"
    / "latest"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def build_executive_payload(store: SQLiteLeaseStore) -> dict[str, Any]:
    metrics = store.metrics_snapshot()
    reconciled = store.reconcile()
    active_tasks = store.active_tasks()
    completed_last_hour = (
        store._conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='task_completed' "
            "AND created_at > datetime('now', '-1 hour')"
        ).fetchone()[0]
    )
    active_lane_groups = sorted({task["lane_group"] for task in active_tasks})
    blockers_after = store._conn.execute(
        "SELECT COUNT(*) FROM codex_fail_map WHERE operator_required=0 AND unsafe_to_fix=0"
    ).fetchone()[0]
    blockers_before = store._conn.execute(
        "SELECT COUNT(*) FROM codex_fail_map"
    ).fetchone()[0]
    spark_runtime_ready = (
        blockers_after == 0
        and metrics.get("v2_closed_loop_executor_unavailable", 1.0) == 0.0
        and metrics.get("v2_closed_loop_queue_eligible_tasks", 0.0) == 0.0
    )
    payload = {
        "SPARK_RUNTIME_READY": bool(spark_runtime_ready),
        "MIGRATION_COMPLETE": False,
        "LEGACY_SHUTDOWN_READY": False,
        "LIVE_READY": False,
        "PAPER_EDGE_PROVEN": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "AUTOMATION_EXECUTING": metrics.get("v2_closed_loop_active_leases", 0.0) > 0.0,
        "automation_detail": {
            "active_leases": metrics.get("v2_closed_loop_active_leases", 0.0),
            "busy_workers": metrics.get("v2_closed_loop_busy_workers", 0.0),
            "idle_ready_workers": metrics.get("v2_closed_loop_idle_workers", 0.0),
            "queued_eligible_tasks": metrics.get("v2_closed_loop_queue_eligible_tasks", 0.0),
            "oldest_queued_task_age_seconds": metrics.get("v2_closed_loop_queue_oldest_task_age_seconds"),
            "codex_fail_unmapped_count": int(blockers_after),
            "lease_backend": "sqlite-wal",
            "active_lane_groups": active_lane_groups,
            "current_running_tasks": [task["task_id"] for task in active_tasks[:20]],
            "completed_last_hour": int(completed_last_hour or 0),
            "blockers_before": int(blockers_before),
            "blockers_after": int(blockers_after),
        },
        "next_action": (
            "Continue running queue drain with canary-to-fulllane expansion."
            if spark_runtime_ready
            else "Review blockers and unmapped Codex fails before production-equivalence claim."
        ),
        "blocks": reconciled,
        "generated_utc": _now_iso(),
        "marker": "V2_CODEX_SPARK_PARALLEL_CLOSED_LOOP_RUNTIME_READY"
        if spark_runtime_ready
        else "V2_CODEX_SPARK_PARALLEL_CLOSED_LOOP_RUNTIME_BLOCKED",
    }
    return payload


def build_operator_payload(store: SQLiteLeaseStore) -> dict[str, Any]:
    executive = build_executive_payload(store)
    operator_payload = {
        "active_leases": executive["automation_detail"]["active_leases"],
        "active_claude": int(executive["AUTOMATION_EXECUTING"]),
        "active_codex": int(executive["AUTOMATION_EXECUTING"]),
        "queued_eligible_tasks": executive["automation_detail"]["queued_eligible_tasks"],
        "ready": bool(executive["SPARK_RUNTIME_READY"]),
        "next_action": executive["next_action"],
        "safe_envelope_required": {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        },
        "generated_utc": _now_iso(),
        "marker": "V2_CODEX_SPARK_PARALLEL_CLOSED_LOOP_RUNTIME_EXECUTIVE_READY"
        if executive["AUTOMATION_EXECUTING"]
        else "V2_CODEX_SPARK_PARALLEL_CLOSED_LOOP_RUNTIME_BLOCKED",
    }
    operator_payload.update(executive)
    return operator_payload


def run_once(*, db_path: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    store = SQLiteLeaseStore(db_path=db_path)
    executive_payload = build_executive_payload(store)
    operator_payload = build_operator_payload(store)
    _write_json(WORKLOG_DIR / "executive_payload_spark_status.json", executive_payload)
    _write_json(WORKLOG_DIR / "operator_payload_spark_status.json", operator_payload)
    store.close()
    return executive_payload, operator_payload


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--operator-only", action="store_true", default=False)
    args = parser.parse_args(argv)
    run_once(db_path=args.db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
