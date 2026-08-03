"""V2 startup-parity first-batch execution CLI.

Runs the 10 V2-native migration task scaffolds and emits the
final-readiness packet plus the public dashboard mirror. Read-only with
respect to legacy and the exchange.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.native_runtime_migration.first_batch_executor import (  # noqa: E402
    default_paths,
    run_first_batch,
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the V2 startup-parity first-batch execution (analysis-only)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override the repository root used to locate inputs and outputs.",
    )
    args = parser.parse_args(argv)
    paths = default_paths(Path(args.repo_root).resolve())
    result = run_first_batch(paths)
    print(
        json.dumps(
            {
                "go_no_go": result.go_no_go,
                "task_count": result.task_count,
                "active_lanes": result.active_lanes,
                "paths_written": [str(p) for p in result.paths_written],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
