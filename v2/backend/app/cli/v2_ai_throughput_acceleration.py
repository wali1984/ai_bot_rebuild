"""V2 AI Throughput Acceleration and Resource Plan CLI.

Reads existing replay-miner artifacts, observation-queue artifacts, and
local hardware state (read-only), and emits the throughput acceleration
packet under
``claude_worklog/final_readiness/v2_ai_throughput_acceleration/latest/``
plus the public dashboard mirror under
``v2/frontend/public/v2_ai_throughput_acceleration/latest/``.

Safety: no Redis writes, no exchange mutation, no legacy mutation, no
production / canary approvals.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.throughput.ai_throughput_acceleration import (  # noqa: E402
    default_paths,
    run_throughput_packet,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the V2 AI throughput acceleration packet (analysis-only).",
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override the repository root used to locate inputs and outputs.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    paths = default_paths(repo_root)
    result = run_throughput_packet(paths)

    summary = {
        "go_no_go": result.go_no_go,
        "paths_written": [str(p) for p in result.paths_written],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
