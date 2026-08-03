"""V2 legacy-startup-manifest parity and bridge-exit CLI.

Analysis-only. Emits the parity packet under
``claude_worklog/final_readiness/v2_legacy_startup_manifest_parity_and_bridge_exit/latest/``
and the public dashboard mirror.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.legacy_startup_parity.native_runtime_legacy_parity import (  # noqa: E402
    default_paths,
    run_legacy_parity_packet,
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the V2 legacy-startup-manifest parity and bridge-exit "
            "planner (analysis-only)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override the repository root used to locate inputs and outputs.",
    )
    args = parser.parse_args(argv)
    paths = default_paths(Path(args.repo_root).resolve())
    result = run_legacy_parity_packet(paths)
    print(
        json.dumps(
            {
                "go_no_go": result.go_no_go,
                "paths_written": [str(p) for p in result.paths_written],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
