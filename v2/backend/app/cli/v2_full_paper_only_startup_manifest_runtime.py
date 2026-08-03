"""V2 full paper-only startup manifest runtime CLI.

Verify-only supervisor: probes V2 process / Redis / public-payload state
read-only and emits the paper-startup-manifest packet. Never starts or
stops any daemon, never loads credential values, never calls the
exchange.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.native_runtime_migration.v2_paper_startup_manifest import (  # noqa: E402
    default_paths,
    run_paper_startup_packet,
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the V2 full paper-only startup manifest supervisor "
            "(verify-only)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override the repository root used to locate outputs.",
    )
    args = parser.parse_args(argv)
    paths = default_paths(Path(args.repo_root).resolve())
    result = run_paper_startup_packet(paths)
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
