"""V2 full observation builder status CLI (paper-only, V2-native).

Reads V2 runtime Redis state and emits the worklog + public dashboard
payloads. Never imports torch. Never deserializes any blob. Never
mutates legacy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from v2.backend.app.services.rl_core.full_observation_builder import (
    write_full_observation_status,
)

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_full_observation_builder/latest/full_observation_builder_status.json"
)
PUBLIC_RL_CORE = Path(
    "v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/v2_full_observation_builder/latest/operator_dashboard_payload.json"
)


def main(argv: list[str] | None = None) -> int:
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

    parser = argparse.ArgumentParser(prog="v2_full_observation_builder_status")
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--symbols", default=None,
        help=(
            "Comma-separated symbol list. Default uses the dynamic universe "
            "resolver (25-symbol baseline + published universe)."
        ),
    )
    parser.add_argument(
        "--smoke-test", action="store_true",
        help="Use the BTC/ETH/SOL smoke-test set (test only).",
    )
    parser.add_argument("--timeframe", default="1m")
    args = parser.parse_args(argv)
    symbols = tuple(resolve_symbols(explicit=args.symbols, smoke_test=args.smoke_test))
    payload = write_full_observation_status(
        worklog_path=WORKLOG_STATUS,
        public_paths=(PUBLIC_RL_CORE, PUBLIC_DASHBOARD),
        symbols=symbols,
        timeframe=args.timeframe,
    )
    summary = {
        "state": payload["state"],
        "checkpoint_compatibility_claimed": payload["checkpoint_compatibility_claimed"],
        "target_full_observation_dim": payload["target_full_observation_dim"],
        "per_symbol_summary": [
            {
                "symbol": row["symbol"],
                "generated": row["generated_full_observation_dim"],
                "missing": row["missing_dim_count"],
                "state": row["state"],
            }
            for row in payload["per_symbol"]
        ],
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
