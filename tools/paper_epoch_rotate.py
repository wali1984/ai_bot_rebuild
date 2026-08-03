#!/usr/bin/env python3
"""Atomic PaperAccountEpochV1 rotation CLI — DRY-RUN by default (state_mutated=false).

A real rotation requires BOTH --execute AND --confirm-i-understand, runs ONLY if the
preflight PASSES, writes an archive manifest (read-back verified) then an atomic Lua
rotation, and NEVER touches the immutable global history keys. Run under the backend venv:

  # dry-run (safe; default): prints the full plan + archive manifest, mutates nothing
  "/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python3" tools/paper_epoch_rotate.py

  # real rotation (ONLY after preflight PASS across >=3 clean cycles + operator go):
  "/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python3" tools/paper_epoch_rotate.py \
      --execute --confirm-i-understand
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, "/home/wali/Desktop/AI BOT REBUILD/v2/backend")
from app.services.paper_session import epoch as E  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="PaperAccountEpochV1 rotation (dry-run default).")
    ap.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    ap.add_argument("--execute", action="store_true", help="perform the real rotation (with --confirm-i-understand)")
    ap.add_argument("--confirm-i-understand", action="store_true", help="required alongside --execute")
    ap.add_argument("--expected-previous-session-id", default=None)
    args = ap.parse_args()

    try:
        import redis  # type: ignore
        r = redis.Redis.from_url(args.redis_url, decode_responses=True, socket_timeout=5)
        r.ping()
    except Exception as e:  # pragma: no cover
        print(json.dumps({"status": "READ_ERROR", "state_mutated": False, "error": str(e)}), file=sys.stderr)
        return 1

    if args.execute and not args.confirm_i_understand:
        print(json.dumps({"status": "REFUSED", "state_mutated": False,
                          "reason": "real rotation requires --confirm-i-understand"}, indent=2))
        return 3

    execute = bool(args.execute and args.confirm_i_understand)
    result = E.rotate(r, expected_previous_session_id=args.expected_previous_session_id, execute=execute)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") in ("DRY_RUN_OK", "ROTATED", "NOOP_ALREADY_ROTATED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
