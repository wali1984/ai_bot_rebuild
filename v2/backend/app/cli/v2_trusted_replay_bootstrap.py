"""Bootstrap trusted replay learning from V2-owned feature snapshots.

This CLI is read-only against Redis and writes only V2-owned disk/public JSON
artifacts. It never places orders, mutates exchange settings, trims Redis, or
writes legacy Redis namespaces.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.trusted_replay.bootstrap import (
    bootstrap_trusted_replay_dataset,
)


def connect_redis() -> Any:
    import redis  # type: ignore

    client = redis.Redis(
        host="127.0.0.1",
        port=6379,
        db=0,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=10,
    )
    client.ping()
    return client


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--scan-limit", type=int, default=25_000)
    parser.add_argument("--replay-limit", type=int, default=20_000)
    parser.add_argument(
        "--archive-only",
        action="store_true",
        help="Skip Redis snapshot import and rebuild trusted replay artifacts from the durable archive.",
    )
    args = parser.parse_args()
    result = bootstrap_trusted_replay_dataset(
        client=connect_redis(),
        repo_root=args.repo_root,
        scan_limit=args.scan_limit,
        replay_limit=args.replay_limit,
        import_from_redis=not args.archive_only,
    )
    print(json.dumps(result["dataset_status"], indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
