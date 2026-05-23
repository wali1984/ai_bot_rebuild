"""V2 throughput-plan Codex CLI command remediation CLI.

Probes the installed Codex CLI, refreshes the throughput packet so it
uses installed-CLI-valid review commands, scans the refreshed artifacts
for any remaining invalid command form, and emits the remediation
packet plus a public-mirror probe payload.

Safety: read-only with respect to Redis, the exchange, and the legacy
bot tree. No live/canary/shutdown/Redis-trim approvals.
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
    default_paths as throughput_default_paths,
    run_throughput_packet,
)
from v2.backend.app.services.throughput.codex_cli_command_remediation import (  # noqa: E402
    default_paths,
    run_remediation,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the V2 AI throughput-plan Codex CLI command remediation "
            "(analysis-only)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override the repository root used to locate inputs and outputs.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    paths = default_paths(repo_root)

    def _refresh() -> dict:
        throughput_paths = throughput_default_paths(repo_root)
        result = run_throughput_packet(throughput_paths)
        return {
            "go_no_go": result.go_no_go,
            "paths_written": [str(p) for p in result.paths_written],
        }

    result = run_remediation(paths, refresh_throughput_packet_fn=_refresh)

    summary = {
        "go_no_go": result.go_no_go,
        "invalid_hits_remaining": result.invalid_hits_remaining,
        "paths_written": [str(p) for p in result.paths_written],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if result.invalid_hits_remaining == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
