"""Run V2 native dynamic runtime + trainer bridge-exit execution packet."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.native_dynamic_runtime.execution import (  # noqa: E402
    default_paths,
    run_execution_packet,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run bounded V2-native dynamic runtime and trainer bridge-exit "
            "execution. Public market-data reads only; V2 Redis writes only."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root used for artifacts.",
    )
    args = parser.parse_args(argv)
    paths = default_paths(Path(args.repo_root).resolve())
    result = run_execution_packet(paths)
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
