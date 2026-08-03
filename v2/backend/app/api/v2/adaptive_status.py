"""Read-only adaptive-subsystem status endpoint.

The last-week producer work (adaptive policy-shadow evaluator, candidate-outcome
maturation, candidate calibration, paper-policy authority, escalation supervisor,
and the data-utilization funnel) writes rich telemetry to Redis but had **no API
surface** — so the frontend/iOS could not observe any of it. This endpoint reads
those keys and exposes them.

Every section is honest about freshness (``age_seconds`` + ``stale``) and
availability (``available`` + ``reason``) so the UI can distinguish
"fresh real data", "stale — producer idle", and "producer not publishing"
instead of rendering an ambiguous blank.

Bounded payload: large list fields (e.g. per-cycle ``actions``) are sampled, not
returned whole. Read-only; never mutates anything; live trading stays blocked.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis

router = APIRouter(prefix="/adaptive", tags=["v2-adaptive"])

# section name -> source Redis key. Order is the display order.
_SECTIONS: tuple[tuple[str, str], ...] = (
    ("policy_shadow_status", "v2:adaptive_system:policy_shadow:status"),
    ("policy_shadow_latest", "v2:adaptive_system:policy_shadow:latest"),
    ("candidate_outcomes", "v2:adaptive_system:candidate_outcomes:status"),
    ("candidate_calibration", "v2:adaptive_system:candidate_calibration:status"),
    ("paper_policy_authority", "v2:adaptive_system:paper_policy_authority:status"),
    ("escalation_supervisor", "v2:adaptive_system:escalation_supervisor:status"),
    ("data_utilization_funnel", "v2:training:data_utilization_funnel"),
)

_GENERATED_ISO_FIELDS = ("generated_at", "generated_utc", "generated_at_utc")
_GENERATED_MS_FIELDS = ("generated_at_ms", "generated_utc_ms")

_CACHE_TTL_SECONDS = 10.0
_STALE_AFTER_SECONDS = 900.0  # producer considered idle beyond 15 min
_LIST_SAMPLE_LIMIT = 5
_MAX_STR_LEN = 4096
_MAX_DEPTH = 5

_cache_lock = threading.Lock()
_cache: tuple[float, dict[str, Any]] | None = None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _iso_age_seconds(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - parsed).total_seconds())


def _ms_age_seconds(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    now_ms = datetime.now(UTC).timestamp() * 1000.0
    return max(0.0, (now_ms - float(value)) / 1000.0)


def _age_seconds(payload: dict[str, Any]) -> float | None:
    for field in _GENERATED_ISO_FIELDS:
        age = _iso_age_seconds(payload.get(field))
        if age is not None:
            return age
    for field in _GENERATED_MS_FIELDS:
        age = _ms_age_seconds(payload.get(field))
        if age is not None:
            return age
    return None


def _bound(value: Any, depth: int = 0) -> Any:
    """Recursively bound a payload so a large blob can never blow the response.

    Lists longer than the sample limit are replaced with a bounded sample plus an
    ``_omitted`` count; strings are truncated; recursion is depth-capped.
    """
    if depth >= _MAX_DEPTH:
        return "…(depth-capped)"
    if isinstance(value, str):
        return value if len(value) <= _MAX_STR_LEN else value[:_MAX_STR_LEN] + "…"
    if isinstance(value, list):
        sample = [_bound(item, depth + 1) for item in value[:_LIST_SAMPLE_LIMIT]]
        if len(value) > _LIST_SAMPLE_LIMIT:
            return {
                "_list_len": len(value),
                "_sample": sample,
                "_omitted": len(value) - _LIST_SAMPLE_LIMIT,
            }
        return sample
    if isinstance(value, dict):
        return {str(k): _bound(v, depth + 1) for k, v in value.items()}
    return value


def _read_section(r: Any, key: str) -> dict[str, Any]:
    if r is None:
        return {"available": False, "reason": "redis_unavailable", "source_key": key}
    try:
        raw = r.get(key)
    except Exception:
        return {"available": False, "reason": "redis_read_failed", "source_key": key}
    if not raw:
        # Producer exists in the tree but is not publishing this key (idle/gated).
        return {"available": False, "reason": "producer_not_publishing", "source_key": key}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return {"available": False, "reason": "payload_unparseable", "source_key": key}
    if not isinstance(payload, dict):
        return {"available": False, "reason": "payload_not_object", "source_key": key}
    age = _age_seconds(payload)
    return {
        "available": True,
        "source_key": key,
        "source_bytes": len(raw),
        "age_seconds": age,
        "stale": (age is not None and age > _STALE_AFTER_SECONDS),
        "live_gate": payload.get("live_gate") or "blocked_human_only",
        "places_real_order": bool(payload.get("places_real_order", False)),
        "routes_to_live": bool(payload.get("routes_to_live", False)),
        "data": _bound(payload),
    }


def _build_status() -> dict[str, Any]:
    r = get_redis()
    sections: dict[str, Any] = {}
    fresh = stale = absent = 0
    for name, key in _SECTIONS:
        section = _read_section(r, key)
        sections[name] = section
        if not section.get("available"):
            absent += 1
        elif section.get("stale"):
            stale += 1
        else:
            fresh += 1
    return {
        "schema_version": "adaptive_status_v1",
        "sections": sections,
        "summary": {
            "section_total": len(_SECTIONS),
            "fresh_count": fresh,
            "stale_count": stale,
            "absent_count": absent,
        },
        "stale_after_seconds": _STALE_AFTER_SECONDS,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
    }


@router.get("/status")
async def get_adaptive_status() -> dict[str, Any]:
    """Consolidated read-only status of the adaptive paper/shadow subsystem."""
    global _cache
    now_mono = time.monotonic()
    with _cache_lock:
        if _cache is not None and now_mono - _cache[0] <= _CACHE_TTL_SECONDS:
            cached = dict(_cache[1])
            cached["generated_at_utc"] = _utc_now()
            cached["cache_hit"] = True
            return cached

    status = _build_status()
    with _cache_lock:
        _cache = (time.monotonic(), dict(status))
    status["cache_ttl_seconds"] = _CACHE_TTL_SECONDS
    status["generated_at_utc"] = _utc_now()
    status["cache_hit"] = False
    return status
