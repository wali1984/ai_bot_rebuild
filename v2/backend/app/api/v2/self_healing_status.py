"""Self-healing supervisor status for the dashboard + mobile app.

Reads ``v2:self_healing:status`` (written by v2_self_healing_supervisor) and
returns the per-service health list plus a computed banner summary of services
that are STILL down after auto-heal (rate-limited restarts exhausted, alert-mode
components, or the supervisor itself stale). Read-only; never mutates anything.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis

router = APIRouter(prefix="/self-healing", tags=["v2-self-healing"])

STATUS_KEY = "v2:self_healing:status"
# The supervisor loops every 60s; treat its own status as stale past this.
SUPERVISOR_STALE_SECONDS = 180

# Actions that mean "auto-heal could not (yet) recover this service" -> banner.
_BANNER_ACTIONS = {"SKIP_RATE_LIMITED", "ALERT_DEAD", "ALERT_STALE"}
# Actions that are healthy or operator-intended -> never banner.
_BENIGN_ACTIONS = {
    "OK",
    "SKIP_DELIBERATELY_STOPPED",
    "SKIP_NOT_ENABLED",
    "SKIP_NOT_INSTALLED",
    "SKIP_DENYLISTED",
}
_ACTIVE_STATES = {"active", "activating", "reloading"}


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _empty(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "component_count": 0,
        "decisions": [],
        "action_counts": {},
        "unhealthy_services": [],
        "banner": {
            "show": True,
            "severity": "warn",
            "count": 1,
            "services": [],
            "message": f"Self-healing supervisor status unavailable ({reason}).",
        },
        "routes_to_exchange": False,
        "places_exchange_action": False,
    }


@router.get("/status")
async def get_self_healing_status() -> dict[str, Any]:
    r = get_redis()
    if r is None:
        return _empty("redis_unavailable")
    try:
        raw = r.get(STATUS_KEY)
    except Exception:
        return _empty("redis_read_failed")
    if not raw:
        return _empty("supervisor_status_missing")
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return _empty("supervisor_status_unparseable")
    if not isinstance(payload, dict):
        return _empty("supervisor_status_malformed")

    now = datetime.now(timezone.utc)
    generated = _parse_utc(payload.get("generated_utc"))
    supervisor_age = (now - generated).total_seconds() if generated else None
    supervisor_stale = supervisor_age is None or supervisor_age > SUPERVISOR_STALE_SECONDS

    decisions = payload.get("decisions") if isinstance(payload.get("decisions"), list) else []

    unhealthy: list[dict[str, Any]] = []
    for row in decisions:
        if not isinstance(row, dict):
            continue
        action = str(row.get("action") or "")
        active_state = str(row.get("active_state") or "")
        # A service is "still down" if auto-heal is exhausted/alerting, or it is
        # simply not active while it is supposed to be (enabled, not operator-off).
        down = action in _BANNER_ACTIONS or (
            action not in _BENIGN_ACTIONS and active_state not in _ACTIVE_STATES
        )
        if down:
            unhealthy.append(
                {
                    "name": row.get("name"),
                    "unit": row.get("unit"),
                    "category": row.get("category"),
                    "criticality": row.get("criticality"),
                    "action": action,
                    "active_state": active_state,
                    "reason": row.get("reason"),
                    "heartbeat_age_seconds": row.get("heartbeat_age_seconds"),
                }
            )

    # Banner: show when a service is still down after auto-heal, or the supervisor
    # itself is stale (it may be down).
    banner_services = unhealthy
    show_banner = bool(unhealthy) or supervisor_stale
    if supervisor_stale and not unhealthy:
        severity = "warn"
        message = (
            f"Self-healing supervisor status is stale "
            f"({int(supervisor_age) if supervisor_age is not None else 'unknown'}s) — monitoring may be down."
        )
    elif unhealthy:
        crit = [u for u in unhealthy if u.get("criticality") == "critical"]
        severity = "critical" if crit else "warn"
        names = ", ".join(str(u.get("name")) for u in unhealthy[:6])
        message = (
            f"{len(unhealthy)} service(s) down after auto-heal: {names}"
            + ("…" if len(unhealthy) > 6 else "")
        )
    else:
        severity = "ok"
        message = "All services healthy."

    return {
        "available": True,
        "schema_version": payload.get("schema_version"),
        "generated_utc": payload.get("generated_utc"),
        "supervisor_age_seconds": round(supervisor_age, 1) if supervisor_age is not None else None,
        "supervisor_stale": supervisor_stale,
        "component_count": payload.get("component_count"),
        "action_counts": payload.get("action_counts") or {},
        "restarted_units": payload.get("restarted_units") or [],
        "restarted_count": payload.get("restarted_count") or 0,
        "healthy_count": sum(
            1 for d in decisions if isinstance(d, dict) and d.get("action") == "OK"
        ),
        "unhealthy_count": len(unhealthy),
        "unhealthy_services": unhealthy,
        "decisions": decisions,
        "banner": {
            "show": show_banner,
            "severity": severity,
            "count": len(banner_services),
            "services": banner_services,
            "message": message,
        },
        "live_gate": payload.get("live_gate", "blocked_human_only"),
        "routes_to_exchange": False,
        "places_exchange_action": False,
    }
