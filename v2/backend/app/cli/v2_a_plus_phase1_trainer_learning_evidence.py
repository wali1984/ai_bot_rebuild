#!/usr/bin/env python3
"""Publish legacy A+ Phase 1 non-canonical trainer diagnostics.

The command reads V2 Redis/model evidence and writes non-expiring diagnostic
JSON snapshots. These snapshots never authorize canonical runtime readiness,
serving, paper routing, or live execution.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.native_trainer.a_plus_phase1_evidence import (  # noqa: E402
    DIAGNOSTIC_COMPLETE,
    GOAL_ID,
    write_a_plus_phase1_trainer_artifacts,
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
    parser.add_argument(
        "--goal-dir",
        default=None,
        help="Artifact directory. Defaults to goal_state/<A+ goal id>.",
    )
    parser.add_argument(
        "--public-dir",
        default="v2/frontend/public/operator_runtime/a_plus_phase1_trainer_learning/latest",
        help="Optional public operator artifact directory relative to repo root. Use an empty string to skip.",
    )
    parser.add_argument("--json", action="store_true", help="Print full status JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    client = _connect_redis(host=args.redis_host, port=args.redis_port, db=args.redis_db)
    goal_dir = Path(args.goal_dir) if args.goal_dir else repo_root / "goal_state" / GOAL_ID
    if not goal_dir.is_absolute():
        goal_dir = repo_root / goal_dir
    public_dir = Path(args.public_dir) if args.public_dir else None
    if public_dir is not None and not public_dir.is_absolute():
        public_dir = repo_root / public_dir
    status = write_a_plus_phase1_trainer_artifacts(
        redis_client=client,
        repo_root=repo_root,
        goal_dir=goal_dir,
        public_dir=public_dir,
    )
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "status": status["status"],
                    "diagnostic_conditions": status["diagnostic_conditions"],
                    "canonical_runtime_ready": status["canonical_runtime_ready"],
                },
                sort_keys=True,
            )
        )
    return 0 if status["status"] == DIAGNOSTIC_COMPLETE else 2


if __name__ == "__main__":
    raise SystemExit(main())
