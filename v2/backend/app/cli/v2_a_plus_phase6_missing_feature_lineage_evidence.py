#!/usr/bin/env python3
"""Publish A+ Phase 6 missing-critical-feature lineage evidence artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from v2.backend.app.services.native_trainer.a_plus_phase6_missing_feature_lineage import (  # noqa: E402
    GOAL_ID,
    write_phase6_missing_feature_lineage_artifacts,
)


def _connect_redis(*, host: str, port: int, db: int) -> Any:
    import redis

    client = redis.Redis(
        host=host,
        port=port,
        db=db,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=5,
    )
    client.ping()
    return client


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--redis-host", default="127.0.0.1")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--redis-db", type=int, default=0)
    parser.add_argument("--goal-dir", default=None)
    parser.add_argument(
        "--public-dir",
        default="v2/frontend/public/operator_runtime/a_plus_phase6_missing_feature_lineage/latest",
    )
    parser.add_argument("--sample-symbols", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    goal_dir = Path(args.goal_dir) if args.goal_dir else repo_root / "goal_state" / GOAL_ID
    if not goal_dir.is_absolute():
        goal_dir = repo_root / goal_dir
    public_dir = Path(args.public_dir) if args.public_dir else None
    if public_dir is not None and not public_dir.is_absolute():
        public_dir = repo_root / public_dir
    client = _connect_redis(host=args.redis_host, port=args.redis_port, db=args.redis_db)
    status = write_phase6_missing_feature_lineage_artifacts(
        redis_client=client,
        repo_root=repo_root,
        goal_dir=goal_dir,
        public_dir=public_dir,
        sample_symbols=args.sample_symbols,
    )
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(json.dumps({"status": status["status"], "pass_conditions": status["pass_conditions"]}, sort_keys=True))
    return 0 if status["status"] == "MISSING_CRITICAL_FEATURE_LINEAGE_FIX_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
