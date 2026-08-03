#!/usr/bin/env python3
"""Publish semantic runtime-truth repair artifacts for model/prediction pages."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from v2.backend.app.services.native_trainer.runtime_truth import (  # noqa: E402
    READY,
    NativeTrainerRuntimePaths,
    publish_all,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="v2_model_state_ai_predictions_signals_runtime_truth_semantic_repair"
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    paths = NativeTrainerRuntimePaths(repo_root=args.repo_root.resolve(), public_root=args.repo_root.resolve() / "v2/frontend/public")
    payloads = publish_all(paths)
    dashboard = payloads["operator_dashboard_payload.json"]
    print(
        json.dumps(
            {
                "gate": dashboard.get("gate"),
                "generated_est": dashboard.get("generated_est"),
                "prediction_grid_rows": dashboard.get("trainer", {}).get("prediction_grid_rows"),
                "prediction_grid_expected_rows": dashboard.get("trainer", {}).get("prediction_grid_expected_rows"),
                "valid_symbol_count": dashboard.get("trainer", {}).get("valid_symbol_count"),
                "timeframes": dashboard.get("trainer", {}).get("timeframes"),
                "training_steps_total": dashboard.get("trainer", {}).get("training_steps_total"),
                "training_steps_last_hour": dashboard.get("trainer", {}).get("training_steps_last_hour"),
                "resource_bottleneck_reason": dashboard.get("trainer", {}).get("resource_bottleneck_reason"),
                "paper_equity": dashboard.get("paper", {}).get("equity"),
                "paper_pnl": dashboard.get("paper", {}).get("pnl"),
                "live_gate": dashboard.get("live", {}).get("live_gate"),
                "live_submit_blocker": dashboard.get("live", {}).get("live_order_submit_blocker"),
                "semantic_validation": dashboard.get("semantic_validation"),
                "blockers": dashboard.get("blockers"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if dashboard.get("gate") == READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
