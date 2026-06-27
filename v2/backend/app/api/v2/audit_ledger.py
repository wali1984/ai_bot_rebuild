"""B1 + B2: audit-ledger summary and tail routes.

Both routes read the `audit:ledger*` Redis streams. They NEVER write to
those streams. Public-landing must not call /tail — that requires an
`observer+` role.

Shapes:
- GET /audit-ledger/summary  →
    { chain_ok: bool, tail_age_ms: int|None, last_event_id: str|None,
      last_event_ts: str|None }
- GET /audit-ledger/tail?limit=N  →
    list[ { evt_id, source, act, decision_id, reason, chain_status,
            age_seconds } ]
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.v2._common import (
    TtlCache,
    discover_audit_ledger_streams,
    get_redis,
    require_min_role,
)

router = APIRouter(prefix="/audit-ledger", tags=["v2-landing"])

# 1-second TTL — protects Redis from hammer when the landing polls every 5s.
_SUMMARY_CACHE = TtlCache(ttl_seconds=1.0)
_CACHE_KEY_SUMMARY = "summary"


def _parse_event_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Normalize a stream entry's fields into the documented shape.

    Source fields are unknown across legacy streams; we accept a handful of
    common spellings and fall back to None. Never raises.
    """

    def pick(*keys: str) -> Any:
        for k in keys:
            if k in fields and fields[k] not in (None, ""):
                return fields[k]
        return None

    return {
        "source": pick("source", "src", "origin"),
        "act": pick("act", "action", "event"),
        "decision_id": pick("decision_id", "decisionId", "did"),
        "reason": pick("reason", "reason_code", "msg"),
        "chain_status": pick("chain_status", "chain_state", "chain"),
    }


def _stream_entry_ms(evt_id: str) -> int | None:
    """Redis stream IDs are `<ms>-<seq>`. Returns the ms portion or None."""
    if not isinstance(evt_id, str) or "-" not in evt_id:
        return None
    head, _, _ = evt_id.partition("-")
    try:
        return int(head)
    except (TypeError, ValueError):
        return None


def _build_summary(r: Any) -> dict[str, Any]:
    """Inspect the last entry of any discovered audit:ledger* stream.

    Returns the documented shape even if Redis is unreachable. `chain_ok`
    is True iff we successfully read a last entry AND it does not carry a
    `chain_status` of `broken` / `mismatch` / `false`. Missing key /
    empty stream → chain_ok=False, all other fields None.
    """
    out: dict[str, Any] = {
        "chain_ok": False,
        "tail_age_ms": None,
        "last_event_id": None,
        "last_event_ts": None,
    }
    if r is None:
        return out
    streams = discover_audit_ledger_streams(r)
    if not streams:
        return out

    newest_ms: int | None = None
    newest_event_id: str | None = None
    newest_fields: dict[str, Any] | None = None
    for s in streams:
        try:
            tail = r.xrevrange(s, count=1)
        except Exception:
            continue
        if not tail:
            continue
        try:
            evt_id, fields = tail[0]
        except Exception:
            continue
        ms = _stream_entry_ms(evt_id)
        if ms is None:
            continue
        if newest_ms is None or ms > newest_ms:
            newest_ms = ms
            newest_event_id = evt_id
            newest_fields = fields if isinstance(fields, dict) else dict(fields or {})

    if newest_event_id is None or newest_ms is None:
        return out

    now_ms = int(time.time() * 1000)
    tail_age_ms = max(0, now_ms - newest_ms)
    last_event_ts = datetime.fromtimestamp(newest_ms / 1000.0, tz=timezone.utc).isoformat()

    chain_status = None
    if newest_fields:
        cs = newest_fields.get("chain_status") or newest_fields.get("chain_state")
        chain_status = str(cs).lower() if cs is not None else None
    chain_ok = chain_status not in {"broken", "mismatch", "false", "fail", "failed"}

    out.update(
        {
            "chain_ok": bool(chain_ok),
            "tail_age_ms": int(tail_age_ms),
            "last_event_id": str(newest_event_id),
            "last_event_ts": last_event_ts,
        }
    )
    return out


@router.get("/summary")
async def get_audit_ledger_summary() -> dict[str, Any]:
    cached = _SUMMARY_CACHE.get(_CACHE_KEY_SUMMARY)
    if cached is not None:
        return cached
    r = get_redis()
    summary = _build_summary(r)
    _SUMMARY_CACHE.set(_CACHE_KEY_SUMMARY, summary)
    return summary


@router.get(
    "/tail",
    dependencies=[Depends(require_min_role("observer"))],
)
async def get_audit_ledger_tail(
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Tail of merged audit:ledger* streams, newest first.

    Observer+ only. Public requesters get 403 via the RBAC dependency.
    """
    r = get_redis()
    if r is None:
        return []
    streams = discover_audit_ledger_streams(r)
    if not streams:
        return []

    candidates: list[tuple[int, str, dict[str, Any]]] = []
    per_stream = min(limit, 100)
    for s in streams:
        try:
            entries = r.xrevrange(s, count=per_stream)
        except Exception:
            continue
        for evt_id, fields in entries or []:
            ms = _stream_entry_ms(evt_id)
            if ms is None:
                continue
            normalized_fields = fields if isinstance(fields, dict) else dict(fields or {})
            candidates.append((ms, evt_id, normalized_fields))

    # Sort newest first, take `limit`.
    candidates.sort(key=lambda t: t[0], reverse=True)
    candidates = candidates[:limit]

    now_ms = int(time.time() * 1000)
    out: list[dict[str, Any]] = []
    for ms, evt_id, fields in candidates:
        parsed = _parse_event_fields(fields)
        out.append(
            {
                "evt_id": evt_id,
                "source": parsed["source"],
                "act": parsed["act"],
                "decision_id": parsed["decision_id"],
                "reason": parsed["reason"],
                "chain_status": parsed["chain_status"],
                "age_seconds": max(0, int((now_ms - ms) / 1000)),
            }
        )
    return out


_EVENTS_CACHE = TtlCache(ttl_seconds=5.0)
_CACHE_KEY_EVENTS = "events"


@router.get(
    "/events",
    dependencies=[Depends(require_min_role("observer"))],
)
async def get_audit_events(
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Audit events in the shape the audit-ledger frontend page expects.

    Returns { events: [...], total: int, immutable: bool }.
    """
    cached = _EVENTS_CACHE.get(_CACHE_KEY_EVENTS)
    if cached is not None:
        return cached

    r = get_redis()
    if r is None:
        result: dict[str, Any] = {"events": [], "total": 0, "immutable": False}
        return result

    streams = discover_audit_ledger_streams(r)
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    per_stream = min(limit, 200)
    for s in streams:
        try:
            entries = r.xrevrange(s, count=per_stream)
        except Exception:
            continue
        for evt_id, fields in entries or []:
            ms = _stream_entry_ms(evt_id)
            if ms is None:
                continue
            normalized = fields if isinstance(fields, dict) else dict(fields or {})
            candidates.append((ms, evt_id, normalized))

    candidates.sort(key=lambda t: t[0], reverse=True)
    candidates = candidates[:limit]

    now_ms = int(time.time() * 1000)
    events: list[dict[str, Any]] = []
    for ms, evt_id, fields in candidates:
        parsed = _parse_event_fields(fields)
        ts = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()
        events.append(
            {
                "id": str(evt_id),
                "actor": str(parsed.get("source") or fields.get("trader_id") or "system"),
                "action": str(parsed.get("act") or "event"),
                "resource": str(parsed.get("decision_id") or ""),
                "result": str(parsed.get("chain_status") or fields.get("result") or "recorded"),
                "reason": parsed.get("reason"),
                "evidence": str(evt_id),
                "timestamp": ts,
            }
        )

    result = {
        "events": events,
        "total": len(events),
        "immutable": True,
    }
    _EVENTS_CACHE.set(_CACHE_KEY_EVENTS, result)
    return result
