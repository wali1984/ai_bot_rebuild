"""B6: replay status route.

Reads `replay:last_run:*` Redis keys to surface the most recent bounded
replay's marker. Never invokes the replay runner, never mutates any key.

Shape:
{ last_run: str|None, idempotent_hash: str|None, bounded_events_count: int|None }
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis

router = APIRouter(prefix="/replay", tags=["v2-landing"])


def _empty() -> dict[str, Any]:
    return {
        "last_run": None,
        "idempotent_hash": None,
        "bounded_events_count": None,
    }


def _coerce_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _merge_from_json(out: dict[str, Any], raw: Any) -> bool:
    """Update `out` in-place from a JSON-encoded value. Returns True if any
    field was populated.
    """
    if not isinstance(raw, str):
        return False
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    found = False
    if data.get("last_run") not in (None, ""):
        out["last_run"] = data["last_run"]
        found = True
    if data.get("idempotent_hash") not in (None, ""):
        out["idempotent_hash"] = data["idempotent_hash"]
        found = True
    if data.get("bounded_events_count") is not None:
        coerced = _coerce_int(data["bounded_events_count"])
        if coerced is not None:
            out["bounded_events_count"] = coerced
            found = True
    return found


@router.get("/status")
async def get_replay_status() -> dict[str, Any]:
    r = get_redis()
    out = _empty()
    if r is None:
        return out

    # Aggregate JSON keys first.
    json_candidates = (
        "replay:last_run",
        "replay:last_run:latest",
        "replay:last_run:summary",
        "v2:replay:last_run",
    )
    for key in json_candidates:
        try:
            raw = r.get(key)
        except Exception:
            raw = None
        if raw is not None:
            _merge_from_json(out, raw)

    # Discrete keys override (or fill) individual fields.
    discrete = (
        ("replay:last_run:id", "last_run"),
        ("replay:last_run:ts", "last_run"),
        ("replay:last_run:hash", "idempotent_hash"),
        ("replay:last_run:idempotent_hash", "idempotent_hash"),
        ("replay:last_run:events_count", "bounded_events_count"),
        ("replay:last_run:bounded_events_count", "bounded_events_count"),
    )
    for key, field in discrete:
        try:
            raw = r.get(key)
        except Exception:
            raw = None
        if raw is None:
            continue
        if field == "bounded_events_count":
            coerced = _coerce_int(raw)
            if coerced is not None:
                out[field] = coerced
        else:
            out[field] = raw

    return out
