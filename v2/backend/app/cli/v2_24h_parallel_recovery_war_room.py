"""V2 24h parallel recovery war-room CLI.

Reads existing replay-miner artifacts and observation-queue artifacts
(read-only) and emits the 24h war-room packet under
``claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/``
plus the public dashboard mirror under
``v2/frontend/public/v2_24h_parallel_recovery_war_room/latest/``.

Safety: no Redis writes, no exchange mutation, no legacy mutation, no
live/canary approvals.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.war_room.parallel_recovery_24h import (  # noqa: E402
    default_paths,
    run_war_room,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the V2 24h parallel recovery war-room executor "
            "(analysis-only)."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override the repository root used to locate inputs and outputs.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    paths = default_paths(repo_root)
    result = run_war_room(paths)

    summary = {
        "go_no_go": result.go_no_go,
        "lane_count": len(result.lane_statuses),
        "paths_written": [str(p) for p in result.paths_written],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
