"""V2 per-symbol liquidation ingestor loop (paper-only, public data
only).

Today this loop classifies the V2 per-symbol liquidation source state
(operator-decision-required to scope a continuous WSS client). It
writes only `v2:market:liquidations:heartbeat` (a status payload) and
the worklog/public dashboard payloads. It NEVER opens a network
connection in the current build, NEVER synthesises liquidation events,
NEVER touches legacy filesystem.

If a future V2 WSS client is approved, this loop will also read the
populated `v2:market:liquidations:*` keys and write the heartbeat
accordingly; the aggregator (in rl_core) consumes those keys when
present.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from v2.backend.app.services.native_ingestors.liquidations import (
    build_ingestor_status,
    write_heartbeat,
)

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_per_symbol_liquidation_source/latest/v2_liquidation_ingestor_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/operator_runtime/v2_liquidation_ingestor/latest/v2_liquidation_ingestor_status.json"
)
PUBLIC_DASHBOARD_SECONDARY = Path(
    "v2/frontend/public/v2_per_symbol_liquidation_source/latest/operator_dashboard_payload.json"
)


def _connect_redis():
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def run_once(
    symbols: tuple[str, ...] | None = None,
    *,
    redis_client_override=None,
    worklog_path: Path = WORKLOG_STATUS,
    public_paths: tuple[Path, ...] = (PUBLIC_DASHBOARD, PUBLIC_DASHBOARD_SECONDARY),
    write_redis_heartbeat: bool = True,
    smoke_test: bool = False,
) -> dict:
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

    r = redis_client_override if redis_client_override is not None else _connect_redis()
    resolved_symbols = tuple(resolve_symbols(explicit=symbols, smoke_test=smoke_test))
    payload = build_ingestor_status(r, symbols=resolved_symbols)
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    worklog_path.parent.mkdir(parents=True, exist_ok=True)
    worklog_path.write_text(body, encoding="utf-8")
    for p in public_paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    if write_redis_heartbeat and r is not None:
        write_heartbeat(r, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_liquidation_ingestor_loop")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--symbols", default=None)
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Use BTC/ETH/SOL only for explicit smoke tests; never the default.",
    )
    parser.add_argument("--no-redis-heartbeat", action="store_true")
    args = parser.parse_args(argv)
    symbols = (
        tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
        if args.symbols
        else None
    )
    payload = run_once(
        symbols,
        write_redis_heartbeat=not args.no_redis_heartbeat,
        smoke_test=args.smoke_test,
    )
    print(
        json.dumps(
            {
                "go_no_go": payload["go_no_go"],
                "source_classification": payload["source_classification"],
                "symbols_with_any_v2_liquidation_key_populated_count": payload[
                    "symbols_with_any_v2_liquidation_key_populated_count"
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
