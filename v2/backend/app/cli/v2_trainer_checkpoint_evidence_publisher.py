"""Publish V2 trainer checkpoint evidence.

This worker scans legacy checkpoint files read-only, writes metadata-only
evidence to V2 artifacts and optional ``v2:*`` Redis keys, and never loads
weights or mutates legacy state.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from v2.backend.app.services.rl_core.trainer_checkpoint_evidence import (
    DEFAULT_SCAN_ROOTS,
    WORKER_ID,
    build_trainer_checkpoint_evidence,
)

V2_REDIS_PREFIX = "v2:"
REPO_ROOT = Path(__file__).resolve().parents[4]
PUBLIC_STATUS = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime"
    / WORKER_ID
    / "latest"
    / f"{WORKER_ID}_status.json"
)
LOCAL_STATUS = (
    REPO_ROOT
    / "v2/runtime"
    / WORKER_ID
    / "latest"
    / f"{WORKER_ID}_status.json"
)
WORKLOG_STATUS = (
    REPO_ROOT
    / "claude_worklog/final_readiness/legacy_runtime_gap_closure_20260603/latest"
    / f"{WORKER_ID}_status.json"
)


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis.from_url(
            os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        client.ping()
        return client
    except Exception:
        return None


def _safe_set_v2(client, key: str, value: str, *, ex: int) -> bool:
    if client is None or not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        client.set(key, value, ex=int(ex))
        return True
    except Exception:
        return False


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_once(
    *,
    roots: tuple[Path, ...],
    sha256_compute_max_bytes: int,
    write_v2_redis: bool,
    ttl_seconds: int,
) -> dict:
    payload = build_trainer_checkpoint_evidence(
        roots,
        sha256_compute_max_bytes=sha256_compute_max_bytes,
    )
    payload["v2_redis_keys_written"] = []
    payload["v2_redis_keys_written_count"] = 0
    if write_v2_redis:
        client = _connect_redis()
        body = json.dumps(payload, sort_keys=True)
        keys = [
            f"{V2_REDIS_PREFIX}trainer:checkpoint:evidence",
            f"{V2_REDIS_PREFIX}trainer:checkpoint:heartbeat",
        ]
        written = [
            key for key in keys
            if _safe_set_v2(client, key, body, ex=ttl_seconds)
        ]
        payload["v2_redis_keys_written"] = written
        payload["v2_redis_keys_written_count"] = len(written)
        payload["redis_ok"] = client is not None
    for path in (PUBLIC_STATUS, LOCAL_STATUS, WORKLOG_STATUS):
        _write_json(path, payload)
    return payload


def _parse_roots(values: list[str] | None) -> tuple[Path, ...]:
    if not values:
        return tuple(REPO_ROOT / root for root in DEFAULT_SCAN_ROOTS)
    return tuple(Path(raw).expanduser().resolve() for raw in values)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_trainer_checkpoint_evidence_publisher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--root", action="append", default=None)
    parser.add_argument("--sha256-compute-max-bytes", type=int, default=32 * 1024 * 1024)
    parser.add_argument("--write-v2-redis", action="store_true")
    parser.add_argument("--v2-redis-ttl-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    roots = _parse_roots(args.root)
    while True:
        payload = run_once(
            roots=roots,
            sha256_compute_max_bytes=args.sha256_compute_max_bytes,
            write_v2_redis=bool(args.write_v2_redis),
            ttl_seconds=int(args.v2_redis_ttl_seconds),
        )
        if not args.loop:
            print(json.dumps({
                "checkpoint_evidence_status": payload["checkpoint_evidence_status"],
                "candidate_count": payload["candidate_count"],
                "selected_checkpoint_id": payload["selected_checkpoint_id"],
                "checkpoint_weight_status": payload["checkpoint_weight_status"],
                "v2_redis_keys_written_count": payload["v2_redis_keys_written_count"],
            }, sort_keys=True))
            return 0
        time.sleep(max(30, int(args.interval_seconds)))


if __name__ == "__main__":
    sys.exit(main())
