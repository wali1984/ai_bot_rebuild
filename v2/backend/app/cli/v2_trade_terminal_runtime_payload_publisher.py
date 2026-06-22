"""Publish the current V2 trade-terminal payload.

Read-only: this runner merges public market/runtime data into
``operator_runtime/v2_trade_terminal`` and never calls exchange mutation
endpoints.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from v2.backend.app.services.operator_truth.trade_derivatives_runtime import (  # noqa: E402
    publish_trade_terminal_payload,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (  # noqa: E402
    resolve_symbols,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_trade_terminal_runtime_payload_publisher")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args(argv)
    symbol = args.symbol or resolve_symbols(smoke_test=args.smoke_test)[0]
    payload = publish_trade_terminal_payload(symbol=symbol)
    print(
        json.dumps(
            {
                "status": payload.get("data_status"),
                "symbol": payload.get("symbol"),
                "path": "v2/frontend/public/operator_runtime/v2_trade_terminal/latest/trade_terminal_payload.json",
                "generated_est": payload.get("generated_est"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
