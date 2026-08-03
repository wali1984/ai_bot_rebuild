"""Read-only platform status normalization for public presentation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


MARKET_DATA_STATUSES = {"LIVE", "DELAYED", "STALE", "OFFLINE"}
AUTOMATION_STATUSES = {"ACTIVE", "PAUSED", "DEGRADED", "UNKNOWN"}
EXECUTION_STATUSES = {"RESTRICTED", "PAPER", "LIVE_APPROVED", "DISABLED"}
ACCOUNT_STATUSES = {"CONNECTED", "UNAVAILABLE", "UNAUTHORIZED"}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _market_data_status(market_stream: dict[str, Any] | None) -> str:
    if not market_stream:
        return "OFFLINE"
    status = str(market_stream.get("status") or "").lower()
    source = str(market_stream.get("source") or "").lower()
    stale = bool(market_stream.get("stale"))
    if stale:
        return "STALE"
    if status in {"current", "live", "fresh"}:
        return "LIVE"
    if status in {"rest_fallback", "delayed"} or "fallback" in source:
        return "DELAYED"
    if status in {"offline", "unavailable", "missing"}:
        return "OFFLINE"
    return "STALE"


def _automation_status(runtime_state: str | None, data_status: str | None, redis_available: bool) -> str:
    state = str(runtime_state or data_status or "").upper()
    if "PAUSED" in state:
        return "PAUSED"
    if any(token in state for token in ("RUNNING", "CURRENT", "ACTIVE", "AVAILABLE", "OK")):
        return "ACTIVE"
    if redis_available and any(token in state for token in ("DEGRADED", "STALE", "PENDING", "MISSING")):
        return "DEGRADED"
    if not redis_available:
        return "UNKNOWN"
    return "UNKNOWN"


def _execution_status(
    *,
    live_gate_status: str | None,
    live_trading_enabled: bool,
    order_submission_enabled: bool,
    places_real_order: bool,
) -> str:
    gate = str(live_gate_status or "").lower()
    if live_trading_enabled and order_submission_enabled and places_real_order and gate in {
        "open",
        "live_approved",
        "enabled_operator_approved",
    }:
        return "LIVE_APPROVED"
    if any(token in gate for token in ("disabled", "off")):
        return "DISABLED"
    return "RESTRICTED"


def build_truthful_status_dimensions(
    *,
    market_stream: dict[str, Any] | None = None,
    runtime_state: str | None = None,
    data_status: str | None = None,
    redis_available: bool = False,
    live_gate_status: str | None = None,
    live_trading_enabled: bool = False,
    order_submission_enabled: bool = False,
    places_real_order: bool = False,
    account_authenticated: bool = False,
    account_connected: bool = False,
) -> dict[str, Any]:
    """Return the public-safe status dimensions without mutating any runtime state."""
    market_data = _market_data_status(market_stream)
    automation = _automation_status(runtime_state, data_status, redis_available)
    execution = _execution_status(
        live_gate_status=live_gate_status,
        live_trading_enabled=live_trading_enabled,
        order_submission_enabled=order_submission_enabled,
        places_real_order=places_real_order,
    )
    account = "CONNECTED" if account_connected else "UNAVAILABLE" if account_authenticated else "UNAUTHORIZED"
    return {
        "market_data": market_data,
        "automation": automation,
        "execution": execution,
        "account": account,
        "live_trading_enabled": bool(live_trading_enabled),
        "order_submission_enabled": bool(order_submission_enabled),
        "places_real_order": bool(places_real_order),
        "exchange_mutation_enabled": False,
        "source": "backend_truth_status_model",
        "updated_at": _utc_now(),
    }
