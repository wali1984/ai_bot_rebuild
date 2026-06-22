"""V2 website data alignment + control plane CLI.

Read-only with respect to legacy, V2 runtime, the exchange, and
Cloudflare. The deployed dashboard fetch is a single GET with a 5s
timeout; failure is recorded as DASHBOARD_FETCH_FAILED rather than
swallowed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.website_alignment.website_data_alignment import (  # noqa: E402
    default_paths,
    run_website_alignment_packet,
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the V2 website data alignment + control-plane packet "
            "(analysis-only)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override the repository root used to locate inputs and outputs.",
    )
    args = parser.parse_args(argv)
    paths = default_paths(Path(args.repo_root).resolve())
    result = run_website_alignment_packet(paths)
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
