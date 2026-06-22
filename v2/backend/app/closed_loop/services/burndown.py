"""Burndown service for Spark task execution readiness."""

from __future__ import annotations

import argparse
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


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_counts(store: SQLiteLeaseStore) -> tuple[int, int, int]:
    codex_fail_unmapped = store._conn.execute(
        """
        SELECT COUNT(*)
        FROM tasks
        WHERE lane_group LIKE '%-codex' AND status IN ('failed', 'operator_required')
        """
    ).fetchone()[0]
    unresolved = store._conn.execute(
        "SELECT COUNT(*) FROM codex_fail_map WHERE operator_required = 0 AND unsafe_to_fix = 0"
    ).fetchone()[0]
    pending = store._conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE status='pending'"
    ).fetchone()[0]
    return int(codex_fail_unmapped), int(unresolved), int(pending)


def evaluate_ready_gate(blockers_after: int) -> bool:
    return blockers_after == 0


def run_once(*, db_path: str | None = None) -> dict[str, Any]:
    store = SQLiteLeaseStore(db_path=db_path)
    tasks = store.list_tasks()
    tasks_completed_last_hour = 0
    now = datetime.now(timezone.utc).timestamp()
    one_hour = 60 * 60
    completed_events = store._conn.execute(
        "SELECT created_at FROM events WHERE event_type='task_completed'"
    ).fetchall()
    for row in completed_events:
        created = datetime.fromisoformat(row[0].replace("Z", "+00:00")).timestamp()
        if now - created <= one_hour:
            tasks_completed_last_hour += 1
    codex_fail_unmapped, unresolved, pending = _safe_counts(store)
    blockers_before = codex_fail_unmapped
    blockers_after = unresolved
    ready_allowed = evaluate_ready_gate(blockers_after)
    cycle_id = store.add_burndown_cycle(
        blockers_before=blockers_before,
        blockers_after=blockers_after,
        flat_reason="no_flat",
        ready_allowed=ready_allowed,
        unresolved_codex_fails=unresolved,
        payload={
            "total_tasks": len(tasks),
            "completed_last_hour": tasks_completed_last_hour,
            "timestamp": _now_iso(),
        },
    )
    payload = {
        "marker": "V2_CODEX_SPARK_BURNDOWN_READY" if ready_allowed else "V2_CODEX_SPARK_BURNDOWN_BLOCKED",
        "blockers_before": blockers_before,
        "blockers_after": blockers_after,
        "ready_allowed": ready_allowed,
        "codex_fail_unmapped_count": unresolved,
        "completed_last_hour": tasks_completed_last_hour,
        "pending_tasks": pending,
        "cycle_id": cycle_id,
        "generated_utc": _now_iso(),
    }
    _write_json(WORKLOG_DIR / "burndown_status.json", payload)
    _write_json(WORKLOG_DIR / "codex_fail_to_remediation_status.json", {
        "cycle_id": cycle_id,
        "unresolved": unresolved,
        "ready_allowed": ready_allowed,
    })
    store.close()
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--no-store", action="store_true", default=False)
    args = parser.parse_args(argv)
    run_once(db_path=args.db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
