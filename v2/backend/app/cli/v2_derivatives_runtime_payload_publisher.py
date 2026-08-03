"""Publish the current V2 derivatives analytics payload.

Read-only: this runner reads current V2 public market/runtime keys and writes
browser-facing JSON under ``operator_runtime/v2_derivatives``. It never calls
order, test-order, cancel/modify, leverage, margin, transfer, or withdrawal
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
    accepted_symbols,
    publish_derivatives_payload,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_derivatives_runtime_payload_publisher")
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols; defaults to the adaptive derivatives universe.",
    )
    args = parser.parse_args(argv)
    explicit = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    # No explicit list -> let the publisher broaden to the adaptive derivatives
    # universe (accepted majors first, then the resolved symbol universe capped).
    payload = publish_derivatives_payload(symbols=explicit or None)
    print(
        json.dumps(
            {
                "status": "DERIVATIVES_RUNTIME_PAYLOAD_PUBLISHED",
                "symbols": payload.get("symbols"),
                "path": "v2/frontend/public/operator_runtime/v2_derivatives/latest/derivatives_payload.json",
                "generated_est": payload.get("generated_est"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
