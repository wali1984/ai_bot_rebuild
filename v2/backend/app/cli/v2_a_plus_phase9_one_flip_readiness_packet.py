#!/usr/bin/env python3
"""Publish the legacy Phase 9 non-authoritative execution diagnostic."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from v2.backend.app.services.native_trainer.a_plus_phase9_one_flip_readiness import (  # noqa: E402
    GOAL_ID,
    write_phase9_one_flip_readiness_packet,
)


def _read_json_file(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _redis_client(redis_url: str | None) -> Any:
    if not redis_url:
        return None
    try:
        import redis
    except Exception:
        return None
    try:
        client = redis.Redis.from_url(redis_url, decode_responses=True)
        client.ping()
    except Exception:
        return None
    return client


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--goal-dir", default=None)
    parser.add_argument(
        "--public-dir",
        default="v2/frontend/public/operator_runtime/a_plus_phase9_one_flip/latest",
    )
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    parser.add_argument("--no-redis", action="store_true")
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
    phase8_matrix = _read_json_file(goal_dir / "a_plus_candidate_matrix.json")
    redis_client = None if args.no_redis else _redis_client(args.redis_url)
    packet = write_phase9_one_flip_readiness_packet(
        goal_dir=goal_dir,
        public_dir=public_dir,
        redis_client=redis_client,
        phase8_candidate_matrix=phase8_matrix,
    )
    if args.json:
        print(json.dumps(packet, indent=2, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "status": packet["status"],
                    "selected_A_plus_candidate": packet["selected_A_plus_candidate"],
                    "missing_required_fields": packet.get("missing_required_fields"),
                    "live_gate": packet["live_gate"],
                    "canonical_runtime_ready": packet["canonical_runtime_ready"],
                    "operator_flip_sufficient": packet["operator_flip_sufficient"],
                    "order_submitted": packet["order_submitted"],
                    "test_order_submitted": packet["test_order_submitted"],
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
