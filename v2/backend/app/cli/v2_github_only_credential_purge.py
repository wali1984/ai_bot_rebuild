"""V2 GitHub-only credential purge audit CLI.

Read-only audit of git-tracked files / public payloads / worklog artifacts
for high-confidence secret patterns. Reports file paths + line numbers
only; never reads or emits credential values. Does NOT touch any local
runtime credential vault. Does NOT auto-edit any tracked file. Does NOT
auto-rewrite git history.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.security.github_only_credential_purge import (  # noqa: E402
    default_paths,
    run_purge_packet,
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the V2 GitHub-only credential purge audit (read-only "
            "file-path reporter)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override the repository root used to locate inputs and outputs.",
    )
    args = parser.parse_args(argv)
    paths = default_paths(Path(args.repo_root).resolve())
    result = run_purge_packet(paths)
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
