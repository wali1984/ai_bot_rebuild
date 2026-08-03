"""Generate CUDA trainer false-negative/actionability artifacts.

Read-only behavior:
- consumes the CUDA edge-calibration/outcome burn-in operator payload;
- writes JSON/Markdown artifacts for missed-opportunity analysis;
- never changes thresholds in runtime config;
- never writes Redis or calls exchange/order paths.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.native_trainer.cuda_false_negative_actionability import (  # noqa: E402
    default_paths,
    run_false_negative_actionability,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build V2 CUDA trainer false-negative reduction and actionability artifacts."
    )
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--source-payload", default="")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    paths = default_paths(repo_root)
    source = Path(args.source_payload).resolve() if args.source_payload else None
    result = run_false_negative_actionability(paths=paths, source_payload_path=source)
    attr = result.operator_dashboard_payload["false_negative_attribution"]
    overlay = result.operator_dashboard_payload["paper_actionability_overlay"]
    edge = result.operator_dashboard_payload["edge_after_actionability_overlay"]
    print(
        json.dumps(
            {
                "go_no_go": result.go_no_go,
                "paths_written": list(result.paths_written),
                "false_negative_count": attr.get("false_negative_count"),
                "overlay_candidate_count": overlay.get("overlay_candidate_count"),
                "primary_recommendation": edge.get("primary_recommendation"),
                "live_gate": result.operator_dashboard_payload["live_gate"],
                "live_symbols": result.operator_dashboard_payload["live_symbols"],
                "execution_live_symbols": result.operator_dashboard_payload["execution_live_symbols"],
                "approves_live": result.operator_dashboard_payload["approves_live"],
                "approves_canary": result.operator_dashboard_payload["approves_canary"],
                "risk_bypass": result.operator_dashboard_payload["safety_scoreboard"]["risk_bypass"],
                "thresholds_auto_accepted": result.operator_dashboard_payload["safety_scoreboard"]["thresholds_auto_accepted"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
