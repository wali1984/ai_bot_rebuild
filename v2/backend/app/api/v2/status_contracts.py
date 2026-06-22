"""Public-safe `/api/v2/status` contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis
from app.api.v2.market_contracts import _derivatives_realtime_source_evidence, _market_stream_telemetry
from app.services.market_stream_alert_history import market_stream_alert_history_summary
from app.services.market_stream_alert_notifier import market_stream_alert_notifier_status

router = APIRouter(tags=["v2-public-status"])


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_market_stream_status(symbol: str = "BTCUSDT") -> dict[str, Any]:
    telemetry = _market_stream_telemetry(symbol)
    source = str(telemetry.get("source") or "unavailable")
    is_wss = source == "binance_usdm_public_websocket_adapter"
    is_rest = source in ("safe_api_contract_stream", "rest_fallback", "binance_rest_fallback")
    public_source = (
        "WSS primary"
        if is_wss
        else "REST fallback (no WSS)"
        if is_rest
        else "Data source unavailable"
    )
    stale = bool(telemetry.get("stale"))
    # REST fallback is intentional — do not flag it as "stale", flag as "rest_fallback"
    status = "stale" if (stale and is_wss) else "rest_fallback" if (is_rest and not stale) else "stale" if stale else "current"
    return {
        "symbol": str(telemetry.get("symbol") or symbol),
        "status": status,
        "source": public_source,
        "last_frame_at": telemetry.get("last_frame_at"),
        "lag_ms": telemetry.get("lag_ms"),
        "stale": stale and not is_rest,
    }


def _safe_market_stream_alert(stream: dict[str, Any]) -> dict[str, Any]:
    stale = bool(stream.get("stale"))
    status_val = str(stream.get("status") or "")
    lag_ms = stream.get("lag_ms") if isinstance(stream.get("lag_ms"), (int, float)) else None
    if not stale:
        if status_val == "rest_fallback":
            return {
                "status": "rest_fallback",
                "severity": "info",
                "summary": "Market data is via REST fallback (no WSS). This is expected for non-primary symbols.",
                "action": "No action required — REST fallback is intentional for 61/85 symbols.",
                "stale_for_ms": lag_ms,
            }
        return {
            "status": "clear",
            "severity": "info",
            "summary": "Market stream freshness is within the public status threshold.",
            "action": "No public action required.",
            "stale_for_ms": lag_ms,
        }
    return {
        "status": "active",
        "severity": "warning",
        "summary": "Market stream freshness is degraded or unavailable.",
        "action": "Fallback market data remains labeled until stream freshness recovers.",
        "stale_for_ms": lag_ms,
    }


def _safe_derivatives_data_status() -> dict[str, Any]:
    evidence = _derivatives_realtime_source_evidence()
    valid = bool(evidence.get("valid"))
    missing_fields = evidence.get("missing_fields") if isinstance(evidence.get("missing_fields"), list) else []
    return {
        "status": "verified" if valid else "pending",
        "source": "Validated derivatives source evidence" if valid else "Derivatives source evidence pending",
        "funding": "verified" if evidence.get("funding_realtime_verified") is True else "pending",
        "open_interest": "verified" if evidence.get("open_interest_realtime_verified") is True else "pending",
        "liquidations": "verified" if evidence.get("liquidation_source_verified") is True else "pending",
        "long_short": "verified" if evidence.get("long_short_source_verified") is True else "pending",
        "basis": "verified" if evidence.get("basis_source_verified") is True else "pending",
        "exchange_comparison": "verified" if evidence.get("exchange_comparison_verified") is True else "pending",
        "stale": not valid,
        "missing_count": len(missing_fields),
    }


@router.get("/status")
async def get_v2_status() -> dict[str, Any]:
    r = get_redis()
    warnings: list[str] = []
    platform_status = "available"
    api_status = "available"
    data_status = "source pending"
    paper_mode = True
    live_trading_enabled = False
    incidents: list[dict[str, str]] = []
    market_stream = _safe_market_stream_status("BTCUSDT")
    market_stream_alert = _safe_market_stream_alert(market_stream)
    market_stream_alert_history = market_stream_alert_history_summary("BTCUSDT")
    market_stream_alert_notifier = market_stream_alert_notifier_status()
    derivatives_data = _safe_derivatives_data_status()

    if r is None:
        warnings.append("Runtime status source unavailable; returning safe default state.")
        data_status = "source unavailable"
    else:
        try:
            runtime = r.get("status:paper_loop")
            if runtime:
                data_status = "current"
        except Exception:
            warnings.append("Runtime status source unavailable; returning safe default state.")
            data_status = "source unavailable"
        try:
            public_failures = r.get("tonight:readiness:public_route_failed_count")
            if public_failures is not None and int(public_failures) > 0:
                platform_status = "degraded"
                incidents.append({"status": "investigating", "summary": "Public route checks reported issues."})
        except Exception:
            pass

    if market_stream["stale"]:
        if data_status == "current":
            data_status = "degraded"
        warnings.append("Market stream telemetry is stale or unavailable.")

    if derivatives_data["stale"]:
        warnings.append("Derivatives source evidence is pending.")

    return {
        "platform_status": platform_status,
        "api_status": api_status,
        "data_status": data_status,
        "paper_mode": paper_mode,
        "live_trading_enabled": live_trading_enabled,
        "market_stream": market_stream,
        "market_stream_alert": market_stream_alert,
        "market_stream_alert_history": market_stream_alert_history,
        "market_stream_alert_notifier": market_stream_alert_notifier,
        "derivatives_data": derivatives_data,
        "incidents": incidents,
        "updated_at": _utc_now(),
        "source": "runtime status summary" if r is not None else "unavailable",
        "endpoint": "/api/v2/status",
        "stale": r is None,
        "warnings": warnings,
    }
