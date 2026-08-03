"""CLI orchestration for Spark runtime worker families."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from v2.backend.app.closed_loop.lane_registry import all_claude_lanes, all_codex_lanes
from v2.backend.app.closed_loop.workers.claude_worker import run_worker as run_claude_worker
from v2.backend.app.closed_loop.workers.codex_worker import run_worker as run_codex_worker
from v2.backend.app.closed_loop.lease_store.sqlite_store import SQLiteLeaseStore


def _write_status(path: Path, status: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")


def run_once(
    *,
    db_path: str | None = None,
    max_iterations: int | None = None,
    only_workers: str | None = None,
    lane_group: str | None = None,
) -> dict[str, Any]:
    store = SQLiteLeaseStore(db_path=db_path)
    status = {
        "mode": "worker_pool_once",
        "lane_groups": [cfg.lane_group for cfg in (all_claude_lanes() + all_codex_lanes())],
        "results": [],
    }
    if only_workers in (None, "claude"):
        for cfg in all_claude_lanes():
            if lane_group is not None and cfg.lane_group != lane_group:
                continue
            summary = run_claude_worker(
                f"{cfg.lane_group}-canary",
                lane_group=cfg.lane_group,
                max_iterations=max_iterations,
                db_path=db_path,
                task_timeout_seconds=300,
            )
            status["results"].append({"lane_group": cfg.lane_group, "summary": summary})
    if only_workers in (None, "codex"):
        for cfg in all_codex_lanes():
            if lane_group is not None and cfg.lane_group != lane_group:
                continue
            summary = run_codex_worker(
                f"{cfg.lane_group}-canary",
                lane_group=cfg.lane_group,
                max_iterations=max_iterations,
                db_path=db_path,
                task_timeout_seconds=300,
            )
            status["results"].append({"lane_group": cfg.lane_group, "summary": summary})
    _write_status(Path("worker_pool_status.json"), status)
    store.close()
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--max-iterations", type=int, default=1)
    parser.add_argument("--only-workers", choices=("claude", "codex"), default=None)
    parser.add_argument("--lane-group", default=None)
    args = parser.parse_args(argv)

    run_once(
        db_path=args.db_path,
        max_iterations=args.max_iterations,
        lane_group=args.lane_group,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
