"""Paper-only closed-trade path telemetry backfill.

Default mode is a dry run. Redis writes require
--write-v2-paper-path-telemetry and only update V2 paper runtime keys. The
backfill uses final candles contained between entry and exit; uncovered rows
remain dirty.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from v2.backend.app.services.paper_trade_management.path_telemetry_backfill import (
    SCHEMA_VERSION,
    build_path_telemetry_backfill_report,
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
    parser = argparse.ArgumentParser(prog="v2_paper_path_telemetry_backfill")
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--write-v2-paper-path-telemetry",
        action="store_true",
        help="Write repaired path telemetry to v2:paper:* Redis paper keys.",
    )
    parser.add_argument(
        "--fetch-binance-public-klines",
        action="store_true",
        help="Read missing final candle coverage from Binance USD-M public klines.",
    )
    parser.add_argument(
        "--fetch-binance-public-agg-trades",
        action="store_true",
        help="Read missing short-interval path coverage from Binance USD-M public aggregate trades.",
    )
    parser.add_argument("--request-timeout-seconds", type=float, default=8.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    redis_client = _connect_redis()
    if redis_client is None:
        report = {
            "schema_version": SCHEMA_VERSION,
            "dry_run": not args.write_v2_paper_path_telemetry,
            "writes_redis": False,
            "writes_exchange_orders": False,
            "places_real_order": False,
            "live_gate": "blocked_human_only",
            "errors": ["REDIS_UNAVAILABLE"],
        }
        if args.out is not None:
            _write_report(report, args.out)
        print(json.dumps(report, sort_keys=True))
        return 2

    report = build_path_telemetry_backfill_report(
        redis_client,
        write=bool(args.write_v2_paper_path_telemetry),
        fetch_binance_public_klines=bool(args.fetch_binance_public_klines),
        fetch_binance_public_agg_trades=bool(args.fetch_binance_public_agg_trades),
        timeout_seconds=float(args.request_timeout_seconds),
    )
    if args.out is not None:
        _write_report(report, args.out)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
