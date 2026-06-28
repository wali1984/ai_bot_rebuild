"""C2: public-status route.

Returns a whitelisted subset of the operator-truth payload safe for the
public landing surface. No internal IDs, no decision IDs, no quarantine
details — only high-level state labels.

This is the only public-safe endpoint added by the landing redesign.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis
from app.api.v2.status_contracts import _safe_market_stream_status
from app.api.v2.truthful_status import build_truthful_status_dimensions

router = APIRouter(prefix="/public", tags=["v2-landing-public"])

PAPER_HEARTBEAT_STALE_AFTER_SECONDS = 900


_DEFAULT_PAYLOAD: dict[str, Any] = {
    "live_gate_status": "blocked_human_only",
    "runtime_state": "MISSING_EVIDENCE",
    "public_route_failed_count": None,
    "supervisor_health": "MISSING_EVIDENCE",
    "status_dimensions": {
        "market_data": "OFFLINE",
        "automation": "UNKNOWN",
        "execution": "RESTRICTED",
        "account": "UNAUTHORIZED",
        "live_trading_enabled": False,
        "order_submission_enabled": False,
        "places_real_order": False,
        "exchange_mutation_enabled": False,
        "source": "backend_truth_status_model",
        "updated_at": None,
    },
}


def _json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _runtime_state_from_paper_heartbeat(heartbeat: dict[str, Any]) -> str | None:
    if str(heartbeat.get("worker_id") or "") != "v2_trade_management_paper_loop":
        return None
    generated = _parse_utc(
        heartbeat.get("heartbeat_generated_at")
        or heartbeat.get("finished_at")
        or heartbeat.get("started_at")
    )
    if generated is None:
        return "PAPER_RUNTIME_HEARTBEAT_STALE"
    age_seconds = (datetime.now(UTC) - generated).total_seconds()
    if age_seconds > PAPER_HEARTBEAT_STALE_AFTER_SECONDS:
        return "PAPER_RUNTIME_HEARTBEAT_STALE"
    return "PAPER_RUNTIME_ONLINE_ACTIVE"


@router.get("/status")
async def get_public_status() -> dict[str, Any]:
    r = get_redis()
    payload = dict(_DEFAULT_PAYLOAD)
    if r is None:
        return payload
    try:
        gate = r.get("live_readiness:gate")
        if gate:
            payload["live_gate_status"] = str(gate)
    except Exception:
        pass
    try:
        runtime = r.get("status:paper_loop")
        if runtime:
            payload["runtime_state"] = str(runtime)
    except Exception:
        pass
    if payload.get("runtime_state") == "MISSING_EVIDENCE":
        try:
            runtime_state = _runtime_state_from_paper_heartbeat(
                _json_object(r.get("v2:paper:heartbeat"))
            )
            if runtime_state:
                payload["runtime_state"] = runtime_state
        except Exception:
            pass
    try:
        failed = r.get("tonight:readiness:public_route_failed_count")
        if failed is not None:
            payload["public_route_failed_count"] = int(failed)
    except Exception:
        pass
    try:
        stale = r.get("operator:truth:supervisor:stale_or_conflicting")
        if stale is not None:
            payload["supervisor_health"] = "stale_or_conflicting" if stale in ("1", "true", "True") else "current"
    except Exception:
        pass
    try:
        market_stream = _safe_market_stream_status("BTCUSDT")
    except Exception:
        market_stream = None
    payload["status_dimensions"] = build_truthful_status_dimensions(
        market_stream=market_stream,
        runtime_state=str(payload.get("runtime_state") or ""),
        data_status=str(payload.get("runtime_state") or ""),
        redis_available=r is not None,
        live_gate_status=str(payload.get("live_gate_status") or "blocked_human_only"),
        live_trading_enabled=False,
        order_submission_enabled=False,
        places_real_order=False,
        account_authenticated=False,
        account_connected=False,
    )
    return payload
