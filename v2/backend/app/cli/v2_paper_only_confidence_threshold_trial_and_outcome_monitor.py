#!/usr/bin/env python3
"""Run the paper-only confidence threshold trial and publish artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from v2.backend.app.services.native_trainer.paper_confidence_threshold_trial import (  # noqa: E402
    TRIAL_THRESHOLD,
    run_paper_confidence_threshold_trial,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="v2_paper_only_confidence_threshold_trial_and_outcome_monitor"
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--threshold", type=float, default=TRIAL_THRESHOLD)
    parser.add_argument(
        "--monitor-only",
        action="store_true",
        help="publish artifacts without writing the V2 paper trial signal overlay",
    )
    parser.add_argument(
        "--skip-paper-loop",
        action="store_true",
        help="write the trial signal overlay but do not run the paper loop once",
    )
    args = parser.parse_args(argv)

    result = run_paper_confidence_threshold_trial(
        repo_root=args.repo_root,
        threshold=args.threshold,
        apply_trial=not args.monitor_only,
        run_paper_loop=not args.skip_paper_loop,
    )
    dashboard = result.artifacts.get("operator_dashboard_payload.json", {})
    print(
        json.dumps(
            {
                "go_no_go": result.go_no_go,
                "generated_est": dashboard.get("generated_est"),
                "prediction_rows": dashboard.get("summary", {}).get("prediction_rows"),
                "paper_allowed_before": dashboard.get("summary", {}).get("paper_allowed_before"),
                "trial_candidate_count": dashboard.get("summary", {}).get("trial_candidate_count"),
                "quarantine_blocked_candidate_count": dashboard.get("summary", {}).get(
                    "quarantine_blocked_candidate_count"
                ),
                "trial_promoted_signal_count": dashboard.get("summary", {}).get(
                    "trial_promoted_signal_count"
                ),
                "paper_loop_run": dashboard.get("summary", {}).get("paper_loop_run"),
                "live_threshold_changed": dashboard.get("live", {}).get("live_threshold_changed"),
                "paths_written": len(result.paths_written),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.go_no_go.endswith("_READY") else 2


if __name__ == "__main__":
    raise SystemExit(main())
