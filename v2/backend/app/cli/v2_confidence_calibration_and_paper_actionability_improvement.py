#!/usr/bin/env python3
"""Publish confidence calibration and paper actionability artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from v2.backend.app.services.native_trainer.confidence_actionability_calibration import (  # noqa: E402
    run_confidence_actionability,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="v2_confidence_calibration_and_paper_actionability_improvement"
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    result = run_confidence_actionability(repo_root=args.repo_root)
    dashboard = result.operator_dashboard_payload
    print(
        json.dumps(
            {
                "go_no_go": result.go_no_go,
                "generated_est": dashboard.get("generated_est"),
                "prediction_rows": dashboard.get("summary", {}).get("prediction_rows"),
                "confidence_blocked_rows": dashboard.get("summary", {}).get(
                    "confidence_blocked_rows"
                ),
                "under_confident_candidate_count": dashboard.get("summary", {}).get(
                    "under_confident_candidate_count"
                ),
                "paper_threshold_auto_applied": dashboard.get("summary", {}).get(
                    "paper_threshold_auto_applied"
                ),
                "live_threshold_changed": dashboard.get("summary", {}).get(
                    "live_threshold_changed"
                ),
                "paths_written": len(result.paths_written),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.go_no_go.endswith("_READY") else 2


if __name__ == "__main__":
    raise SystemExit(main())

