"""Run the V2 all-timeframe prediction/signal/price-target publisher."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.all_timeframe_prediction_signal_price_target_publisher import (  # noqa: E402
    DEFAULT_STALE_SECONDS,
    DEFAULT_RUNTIME_TRAINER_TRUST_RECONCILIATION_LIMIT,
    V2KeyValueStore,
    build_packet,
    default_paths,
    write_outputs,
)


def _localhost_store() -> V2KeyValueStore:
    try:
        import redis  # type: ignore

        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=5,
        )
        client.ping()
        return V2KeyValueStore(client=client)
    except Exception:  # noqa: BLE001
        return V2KeyValueStore(client=None)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="v2_all_timeframe_prediction_signal_price_target_publisher")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--prediction-stale-seconds", type=int, default=DEFAULT_STALE_SECONDS)
    parser.add_argument("--production-base-url", default="https://dashboard.wajidali.us")
    parser.add_argument(
        "--routes",
        nargs="*",
        default=[
            "/ai-predictions",
            "/signals",
            "/trade",
            "/derivatives",
            "/backtests",
            "/system/trainer",
            "/system/orchestrator",
            "/system/risk-controllers",
            "/system/execution",
            "/system/readiness",
        ],
    )
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument(
        "--trainer-trust-reconciliation-limit",
        type=int,
        default=DEFAULT_RUNTIME_TRAINER_TRUST_RECONCILIATION_LIMIT,
        help="Maximum expensive trainer trust scope checks per publish cycle; use -1 for no limit.",
    )
    parser.add_argument(
        "--full-trainer-feature-parity",
        action="store_true",
        help="Rebuild trainer examples for feature parity instead of using prediction-row feature summaries.",
    )
    parser.add_argument("--no-redis-write", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args(argv)


def run_once(args: argparse.Namespace) -> dict:
    paths = default_paths(Path(args.repo_root).resolve())
    store = _localhost_store()
    result = build_packet(
        paths=paths,
        store=store,
        stale_seconds=max(1, int(args.prediction_stale_seconds)),
        production_base_url=str(args.production_base_url),
        routes=list(args.routes),
        write_redis=not bool(args.no_redis_write),
        trainer_trust_reconciliation_limit=(
            None
            if int(args.trainer_trust_reconciliation_limit) < 0
            else int(args.trainer_trust_reconciliation_limit)
        ),
        feature_parity_from_prediction_rows=not bool(args.full_trainer_feature_parity),
    )
    if not args.no_write:
        result = write_outputs(paths, result)
    return {
        "go_no_go": result.go_no_go,
        "paths_written": [str(path) for path in result.paths_written],
        "redis_connected": store.audit.connected,
        "redis_writes_succeeded": store.audit.writes_succeeded,
        "old_redis_write_attempts": store.audit.old_redis_write_attempts,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.loop:
        while True:
            print(json.dumps(run_once(args), sort_keys=True), flush=True)
            time.sleep(max(10, int(args.interval_seconds)))
    print(json.dumps(run_once(args), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
