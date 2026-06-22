"""Paper-only outcome-memory rebuild from current V2 Redis closed trades.

Default mode is a dry run: it reads v2:paper:closed_trades and v2:paper:ledger,
builds the buckets the entry gate reads, and writes only the optional report
file requested by --out. Redis writes require --write-v2-paper-outcome-memory.

This is runtime recovery evidence, not a historical replay or training loader.
It must not be used to create point-in-time training samples.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from v2.backend.app.services.paper_trade_management.outcome_memory_updater import (
    rebuild_outcome_memory_from_redis,
)


def _connect_redis() -> Any | None:
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="v2_paper_outcome_memory_rebuild")
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--write-v2-paper-outcome-memory",
        action="store_true",
        help="Write rebuilt buckets to v2:paper:outcome_memory:* Redis keys.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    redis_client = _connect_redis()
    if redis_client is None:
        report = {
            "schema_version": "v2_outcome_memory_updater_v1",
            "dry_run": not args.write_v2_paper_outcome_memory,
            "writes_redis": False,
            "mutates_exchange": False,
            "places_real_order": False,
            "writes_old_redis": False,
            "live_gate": "blocked_human_only",
            "errors": ["REDIS_UNAVAILABLE"],
        }
        if args.out is not None:
            _write_report(report, args.out)
        print(json.dumps(report, sort_keys=True))
        return 2

    report = rebuild_outcome_memory_from_redis(
        redis_client=redis_client,
        write=bool(args.write_v2_paper_outcome_memory),
    )
    if args.out is not None:
        _write_report(report, args.out)
    print(json.dumps(report, sort_keys=True))
    return 0 if not report.get("errors") else 2


if __name__ == "__main__":
    sys.exit(main())
