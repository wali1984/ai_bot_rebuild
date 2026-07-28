#!/usr/bin/env python3
"""Read-only preflight safety gate for the PaperAccountEpochV1 rotation.

Thin CLI over the canonical `app.services.paper_session.epoch.evaluate_preconditions`
so the gate logic has ONE source of truth (shared with the rotation + tests). STRICTLY
READ-ONLY: only Redis GET/TYPE reads, never writes/deletes, never restarts anything,
never mutates paper state (`state_mutated: false` always). On any failing precondition
it reports `status: BLOCKED_RESET_PRECONDITION` — it does NOT "solve" a failure by
deleting a position/proof/quarantine row.

Usage (backend venv):
  "/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python3" tools/paper_epoch_preflight.py
Exit 0 = PASS (safe to proceed), 2 = BLOCKED, 1 = read error.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "/home/wali/Desktop/AI BOT REBUILD/v2/backend")
from app.services.paper_session.epoch import evaluate_preconditions  # noqa: E402

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def main() -> int:
    try:
        import redis  # type: ignore
        r = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=5)
        r.ping()
        report = evaluate_preconditions(r)
    except Exception as e:  # pragma: no cover
        print(json.dumps({"status": "READ_ERROR", "state_mutated": False, "error": str(e)}), file=sys.stderr)
        return 1
    report["note"] = (
        "PASS reflects one snapshot; CG-F056 phantom churn means positions/fills must be "
        "proof-clean across >=3 consecutive cycles before rotation. Re-run this gate each cycle."
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
