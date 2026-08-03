#!/usr/bin/env python3
"""Publish runtime-alpha dynamic strategy/leverage/margin readiness artifacts.

Read-only paper evidence wrapper. It never submits real/test orders, never
cancels/modifies orders, never changes leverage or margin mode, and never
writes Redis.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from v2.backend.app.services.runtime_alpha_dynamic_readiness import (  # noqa: E402
    READY,
    DynamicReadinessPaths,
    publish_all,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_runtime_alpha_remediated_dynamic_strategy_leverage_margin")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    payloads = publish_all(
        DynamicReadinessPaths(
            repo_root=repo_root,
            public_root=repo_root / "v2/frontend/public",
        )
    )
    dashboard: dict[str, Any] = payloads["operator_dashboard_payload.json"]
    print(
        json.dumps(
            {
                "gate": dashboard.get("gate"),
                "status": dashboard.get("status"),
                "blockers": dashboard.get("blockers"),
                "soak_12h_complete": dashboard.get("soak_12h_complete"),
                "completion_window_elapsed_seconds": dashboard.get("completion_window_elapsed_seconds"),
                "completion_window_required_seconds": dashboard.get("completion_window_required_seconds"),
                "paper_only": dashboard.get("paper_only"),
                "live_order_submitted": dashboard.get("live_order_submitted"),
                "exchange_leverage_mutation": dashboard.get("exchange_leverage_mutation"),
                "exchange_margin_mode_mutation": dashboard.get("exchange_margin_mode_mutation"),
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if dashboard.get("gate") == READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
