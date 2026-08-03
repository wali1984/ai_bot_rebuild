#!/usr/bin/env python3
"""Operator-gated restore of the CG-F044 closed_trades rows.

Dry-run by default: shows exactly what would be merged. With --confirm it
merges the artifact-reconstructed rows from
raw_evidence/closed_trades_restore_ready_20260708.json into the live
closed-trades key, deduplicating against live rows, stamping every restored
row with reconstructed_from_artifacts=true and
counts_as_strict_preemptive_evidence=false. Never deletes or edits live rows;
only adds.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import redis

REPO = Path(__file__).resolve().parent.parent
RESTORE_FILE = REPO / "raw_evidence" / "closed_trades_restore_ready_20260708.json"
KEY = "v2:paper:closed_trades"
DEFAULT_EXPIRY_SECONDS = 30 * 24 * 3600


def _row_key(row: dict) -> str:
    return str(
        row.get("restore_dedup_key")
        or row.get("close_id")
        or row.get("position_id")
        or "|".join([str(row.get("symbol")), str(row.get("side")), str(row.get("realized_pnl_bps"))])
    )


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _restore_close_id(index: int, row: dict) -> str:
    symbol = str(row.get("symbol") or "UNKNOWN").replace(":", "_")
    return f"recon_close_{index}_{symbol}"


def _stamp_restore_row(row: dict, *, index: int, session: str, recorded_utc: str) -> dict:
    stamped = dict(row)
    stamped.setdefault("paper_session_id", session)
    stamped.setdefault("close_id", _restore_close_id(index, stamped))
    stamped["reconstructed_from_artifacts"] = True
    stamped["reconstruction_recorded_utc"] = recorded_utc
    stamped["counts_as_strict_preemptive_evidence"] = False
    stamped["counts_as_live_readiness_evidence"] = False
    stamped["counts_as_a_plus_evidence"] = False
    stamped.setdefault("preemptive_decision_id", f"backfilled_preemptive_recon_{index}")
    stamped["preemptive_decision_backfilled"] = True
    stamped.setdefault("paper_only", True)
    stamped.setdefault("routes_to_live", False)
    stamped.setdefault("places_real_order", False)
    stamped["restore_dedup_key"] = _row_key(stamped)
    return stamped


def _merge_restore_rows(live: list[dict], payload: dict, *, recorded_utc: str) -> tuple[str, list[dict], list[dict]]:
    session = payload["paper_session_id"]
    row_count = payload.get("row_count")
    candidates = payload.get("rows") or []
    if row_count is not None and int(row_count) != len(candidates):
        raise ValueError(f"restore row_count mismatch: declared={row_count} actual={len(candidates)}")

    live_sessions = {t.get("paper_session_id") for t in live if isinstance(t, dict) and t.get("paper_session_id")}
    if live_sessions and session not in live_sessions:
        raise RuntimeError(f"session mismatch: live={sorted(live_sessions)} restore={session}")

    to_add: list[dict] = []
    seen_keys = {_row_key(t) for t in live if isinstance(t, dict)}
    for index, row in enumerate(candidates):
        if not isinstance(row, dict):
            continue
        stamped = _stamp_restore_row(row, index=index, session=session, recorded_utc=recorded_utc)
        dedup_key = _row_key(stamped)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)
        to_add.append(stamped)
    return session, candidates, to_add


def _load_live_rows(r: redis.Redis) -> list[dict]:
    live = json.loads(r.get(KEY) or "[]")
    if not isinstance(live, list):
        raise RuntimeError(f"{KEY} must contain a JSON list")
    return [row for row in live if isinstance(row, dict)]


def _write_live_rows(r: redis.Redis, rows: list[dict]) -> int:
    ttl = r.ttl(KEY)
    if ttl and ttl > 0:
        r.set(KEY, json.dumps(rows, default=str), ex=ttl)
    elif ttl == -1:
        r.set(KEY, json.dumps(rows, default=str))
    else:
        r.set(KEY, json.dumps(rows, default=str), ex=DEFAULT_EXPIRY_SECONDS)
    return ttl


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="actually write")
    args = parser.parse_args()
    payload = json.loads(RESTORE_FILE.read_text())
    now = _utc_iso()

    r = redis.Redis(decode_responses=True)
    try:
        live = _load_live_rows(r)
        session, candidates, to_add = _merge_restore_rows(live, payload, recorded_utc=now)
    except Exception as exc:
        print("STOPPING:", exc)
        return 2
    ttl = r.ttl(KEY)

    print("restore session:", session)
    print("live ttl seconds:", ttl)
    print("live rows:", len(live), "| candidates:", len(candidates), "| to add:", len(to_add))
    for row in to_add:
        print("  +", row.get("symbol"), row.get("side"), "bps=", row.get("realized_pnl_bps"),
              "tier=", row.get("paper_opportunity_tier"), "dedup_key=", row.get("restore_dedup_key"))
    if not args.confirm:
        print()
        print("DRY RUN ONLY - operator review required before --confirm")
        return 0
    merged = live + to_add
    written_ttl = _write_live_rows(r, merged)
    print()
    print("APPLIED:", len(merged), "total rows")
    print("PRESERVED_TTL_SECONDS:", written_ttl)
    print("Next: paper loop propagates to mirrors; re-run guardian verifier.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
