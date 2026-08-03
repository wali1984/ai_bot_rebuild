"""V2 native trainer bridge-exit prediction publisher CLI.

Consumes V2-native feature / TA payloads already populated under
``v2:*`` by the dynamic runtime executor, and emits per-symbol
per-timeframe blocked baseline / contract-only predictions through a
publisher that refuses any non-``v2:*`` key.

Honest: no native trainer claim, no checkpoint compatibility claim,
no paper-fill-gate weakening, no live approval. Existing stronger
runtime predictions are preserved, not overwritten.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.trainer_bridge_exit.native_prediction_publisher import (  # noqa: E402
    V2OnlyPublisher,
    default_paths,
    run_publisher_packet,
)


def _try_localhost_publisher() -> V2OnlyPublisher:
    try:
        import redis  # type: ignore

        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        client.ping()
        return V2OnlyPublisher(client=client)
    except Exception:  # noqa: BLE001
        return V2OnlyPublisher(client=None)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run the V2 native trainer bridge-exit prediction publisher "
            "(baseline / contract-only; paper-fill gate stays blocked)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Override the repository root used to locate outputs.",
    )
    parser.add_argument(
        "--no-redis",
        action="store_true",
        help="Run with publisher in audit-only mode (no Redis client).",
    )
    args = parser.parse_args(argv)
    paths = default_paths(Path(args.repo_root).resolve())
    publisher = V2OnlyPublisher(client=None) if args.no_redis else _try_localhost_publisher()
    result = run_publisher_packet(paths, publisher=publisher)
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
