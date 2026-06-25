"""C2: public-status route.

Returns a whitelisted subset of the operator-truth payload safe for the
public landing surface. No internal IDs, no decision IDs, no quarantine
details — only high-level state labels.

This is the only public-safe endpoint added by the landing redesign.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis
from app.api.v2.status_contracts import _safe_market_stream_status
from app.api.v2.truthful_status import build_truthful_status_dimensions

router = APIRouter(prefix="/public", tags=["v2-landing-public"])


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
