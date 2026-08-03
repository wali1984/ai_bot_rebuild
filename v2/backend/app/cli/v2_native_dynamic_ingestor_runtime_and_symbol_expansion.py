"""V2-native dynamic ingestor runtime + 25-symbol expansion CLI.

Analysis/contract only: declares typed V2-native runtime contracts for
Binance OHLCV / orderbook / feature pipeline / TA across the 25-symbol
universe and emits per-symbol envelopes. Does NOT open exchange
connections, load credentials, or write any Redis key.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.native_dynamic_runtime.dynamic_runtime import (  # noqa: E402
    default_paths,
    run_dynamic_runtime_packet,
)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the V2-native dynamic ingestor runtime + 25-symbol "
            "expansion packet (analysis-only)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override the repository root used to locate outputs.",
    )
    args = parser.parse_args(argv)
    paths = default_paths(Path(args.repo_root).resolve())
    result = run_dynamic_runtime_packet(paths)
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
