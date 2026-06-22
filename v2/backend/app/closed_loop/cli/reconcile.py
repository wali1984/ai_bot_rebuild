"""CLI wrapper for source-of-truth reconciliation checks."""

from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.closed_loop.lease_store.sqlite_store import SQLiteLeaseStore


def run_reconcile(db_path: str | None = None) -> dict[str, bool | int | list[str]]:
    store = SQLiteLeaseStore(db_path=db_path)
    status = store.reconcile()
    status["ok"] = (
        status["duplicate_active_task_leases"] == 0
        and status["duplicate_file_lock_active_leases"] == 0
        and status["tasks_missing_safe_envelope"] == 0
    )
    store.close()
    return status


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args(argv)
    status = run_reconcile(db_path=args.db_path)
    Path(".").joinpath("reconcile_status.json").write_text(
        json.dumps(status, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return 0 if status.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
