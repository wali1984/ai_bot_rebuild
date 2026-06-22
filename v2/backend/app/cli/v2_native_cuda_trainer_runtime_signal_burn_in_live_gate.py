"""Build V2 CUDA trainer burn-in and website live-gate artifacts.

The command is read-only with respect to runtime systems. It consumes the
existing V2 native CUDA trainer payload and writes report/website artifacts.
It never enables live/canary, never writes Redis, and never calls exchanges.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.native_trainer.cuda_trainer_live_gate import (  # noqa: E402
    default_paths,
    run_runtime_signal_gate,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate V2 CUDA trainer runtime signal burn-in and website live-gate artifacts."
    )
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument(
        "--source-payload",
        default="",
        help="Optional source operator_dashboard_payload.json from the native CUDA trainer implementation.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    paths = default_paths(repo_root)
    source = Path(args.source_payload).resolve() if args.source_payload else None
    result = run_runtime_signal_gate(paths=paths, source_payload_path=source)
    print(
        json.dumps(
            {
                "go_no_go": result.go_no_go,
                "paths_written": list(result.paths_written),
                "prediction_contract": result.operator_dashboard_payload["prediction_contract"]["status"],
                "risk_consumption": result.operator_dashboard_payload["risk_consumption"]["status"],
                "orchestrator_consumption": result.operator_dashboard_payload["orchestrator_consumption"]["status"],
                "paper_signal_lineage": result.operator_dashboard_payload["paper_signal_lineage"]["status"],
                "edge_recompute": result.operator_dashboard_payload["edge_recompute"]["status"],
                "live_gate": result.operator_dashboard_payload["live_readiness"]["live_gate"],
                "live_symbols": result.operator_dashboard_payload["live_readiness"]["live_symbols"],
                "execution_live_symbols": result.operator_dashboard_payload["live_readiness"]["execution_live_symbols"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
