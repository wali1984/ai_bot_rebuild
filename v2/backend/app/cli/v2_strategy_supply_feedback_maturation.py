"""Mature strategy-supply pending evidence into trainer feedback labels.

The command is paper/shadow only. It reads append-only pending evidence, waits
for the future label window to close, validates PIT entry snapshots, and writes
trainer feedback rows only when no future leakage or missing snapshot/accounting
evidence is present.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from v2.backend.app.services.strategy_supply.feedback_maturation import (
    mature_strategy_supply_feedback,
)


def _redis_client(redis_url: str | None) -> Any | None:
    if not redis_url:
        return None
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        return redis.Redis.from_url(redis_url, decode_responses=True)
    except Exception:
        return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pending-path", type=Path, required=True)
    parser.add_argument("--matured-path", type=Path, default=None)
    parser.add_argument("--rejected-path", type=Path, default=None)
    parser.add_argument("--status-path", type=Path, default=None)
    parser.add_argument("--read-redis", action="store_true")
    parser.add_argument("--publish-redis", action="store_true")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pending_path = Path(args.pending_path)
    matured_path = Path(args.matured_path) if args.matured_path else pending_path.with_name(
        "strategy_supply_matured_evidence.jsonl"
    )
    rejected_path = Path(args.rejected_path) if args.rejected_path else pending_path.with_name(
        "strategy_supply_rejected_evidence.jsonl"
    )
    status_path = Path(args.status_path) if args.status_path else pending_path.with_name(
        "strategy_supply_feedback_maturation_status.json"
    )
    client = _redis_client(str(args.redis_url)) if args.read_redis or args.publish_redis else None
    status = mature_strategy_supply_feedback(
        pending_path=pending_path,
        matured_path=matured_path,
        rejected_path=rejected_path,
        status_path=status_path,
        redis_client=client,
        publish_to_redis=bool(args.publish_redis),
    )
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(status.get("schema_version"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
