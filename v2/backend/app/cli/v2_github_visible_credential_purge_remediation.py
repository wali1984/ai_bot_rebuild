"""V2 GitHub-visible credential purge remediation CLI.

Classifies findings into actionable buckets and redacts CONFIRMED_SECRET
hits in tracked / public / worklog artifacts. NEVER touches local
runtime vaults (`.local_secrets/`, `.local_models/`, `*.env*`). NEVER
auto-rewrites git history.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.security.github_visible_credential_purge_remediation import (  # noqa: E402
    default_paths,
    run_remediation_packet,
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the V2 GitHub-visible credential purge remediation "
            "(classifies findings, redacts CONFIRMED_SECRET in tracked / "
            "public / worklog files only)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override the repository root used to locate inputs and outputs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify only; do not apply any redaction.",
    )
    args = parser.parse_args(argv)
    paths = default_paths(Path(args.repo_root).resolve())
    result = run_remediation_packet(paths, apply_redactions=not args.dry_run)
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
