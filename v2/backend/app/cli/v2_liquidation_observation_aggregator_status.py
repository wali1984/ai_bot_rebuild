"""V2 liquidation observation aggregator status CLI (paper-only).

Emits the worklog + public dashboard for the 12-slot per-symbol
liquidation subfamily computed from V2-native sources only. Never
imports torch. Never reads legacy filesystem. Never modifies legacy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from v2.backend.app.services.rl_core.liquidation_observation_aggregator import (
    build_aggregator_status,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (
    BASELINE_25_SYMBOLS,
    resolve_symbols,
)

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_full_observation_liquidation_burndown/latest/liquidation_aggregator_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/v2_full_observation_liquidation_burndown/latest/liquidation_aggregator_status.json"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="v2_liquidation_observation_aggregator_status"
    )
    parser.add_argument("--once", action="store_true")
    # Default resolves dynamically from the symbol-universe payload, merged
    # with the 25-symbol baseline. The legacy ``BTCUSDT,ETHUSDT,SOLUSDT``
    # default was flagged as 3-symbol drift by Codex 5.5; smoke-test mode is
    # an explicit opt-in.
    parser.add_argument("--symbols", default=None,
                        help="comma-separated; defaults to dynamic+baseline")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--out-worklog", type=Path, default=WORKLOG_STATUS)
    parser.add_argument("--out-public", type=Path, default=PUBLIC_DASHBOARD)
    args = parser.parse_args(argv)
    symbols = tuple(resolve_symbols(
        explicit=args.symbols, smoke_test=args.smoke_test, include_baseline=True
    )) or tuple(BASELINE_25_SYMBOLS)
    payload = build_aggregator_status(symbols, args.timeframe)
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    args.out_worklog.parent.mkdir(parents=True, exist_ok=True)
    args.out_public.parent.mkdir(parents=True, exist_ok=True)
    args.out_worklog.write_text(body, encoding="utf-8")
    args.out_public.write_text(body, encoding="utf-8")
    print(
        json.dumps(
            {
                "subfamily_total_present_across_symbols": payload[
                    "subfamily_total_present_across_symbols"
                ],
                "subfamily_total_target_across_symbols": payload[
                    "subfamily_total_target_across_symbols"
                ],
                "v2_liquidation_aggregator_per_symbol_source_available": payload[
                    "v2_liquidation_aggregator_per_symbol_source_available"
                ],
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
