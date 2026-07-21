"""Public-safe `/api/v2/status` contract."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from app.api.v2._common import get_redis
from app.api.v2.market_contracts import (
    _canonical_market_feed_truth,
    _derivatives_realtime_source_evidence,
    _market_stream_telemetry,
)
from app.api.v2.truthful_status import build_truthful_status_dimensions
from app.services.market_stream_alert_history import market_stream_alert_history_summary
from app.services.market_stream_alert_notifier import market_stream_alert_notifier_status

router = APIRouter(tags=["v2-public-status"])
V2_STATUS_BUILD_TIMEOUT_SECONDS = float(os.environ.get("ALPHAFORGE_V2_STATUS_BUILD_TIMEOUT_SECONDS", "1.25"))


def _redis_json(key: str) -> Any:
    r = get_redis()
    if r is None:
        return None
    try:
        raw = r.get(key)
        if raw is None:
            return None
        return json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except Exception:
        return None


def _scan_keys(r: Any, pattern: str, cap: int = 2000) -> list[str]:
    """Bounded cursor SCAN (never blocking KEYS). These are public endpoints, so
    a KEYS glob on the ~726K-key store is an unauthenticated DoS/latency vector."""
    keys: list[str] = []
    try:
        cursor = 0
        while True:
            cursor, batch = r.scan(cursor=cursor, match=pattern, count=1000)
            keys.extend(k.decode("utf-8") if isinstance(k, bytes) else str(k) for k in batch)
            if cursor == 0 or len(keys) >= cap:
                break
    except Exception:
        return keys
    return keys


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


async def _bounded_status_build(func: Any, *args: Any, timeout: float) -> Any:
    return await asyncio.wait_for(
        run_in_threadpool(func, *args),
        timeout=max(0.1, float(timeout)),
    )


def _fallback_v2_status(reason: str) -> dict[str, Any]:
    live_gate_status = "blocked_human_only"
    status_dimensions = build_truthful_status_dimensions(
        market_stream={"status": "unavailable", "stale": True},
        runtime_state="source unavailable",
        data_status="source unavailable",
        redis_available=False,
        live_gate_status=live_gate_status,
        live_trading_enabled=False,
        order_submission_enabled=False,
        places_real_order=False,
        account_authenticated=False,
        account_connected=False,
    )
    return {
        "status": "degraded",
        "platform_status": "degraded",
        "api_status": "available",
        "data_status": "source unavailable",
        "paper_mode": True,
        "live_trading_enabled": False,
        "status_dimensions": status_dimensions,
        "market_stream": {
            "symbol": "BTCUSDT",
            "status": "unavailable",
            "source": "Data source unavailable",
            "last_frame_at": None,
            "lag_ms": None,
            "stale": True,
        },
        "market_stream_alert": {
            "status": "active",
            "severity": "warning",
            "summary": "Market stream freshness is degraded or unavailable.",
            "action": "Fallback market data remains labeled until stream freshness recovers.",
            "stale_for_ms": None,
        },
        "market_stream_alert_history": {"status": "unavailable", "alerts": [], "count": 0},
        "market_stream_alert_notifier": {"status": "unavailable"},
        "derivatives_data": {
            "status": "pending",
            "source": "Derivatives source evidence pending",
            "funding": "pending",
            "open_interest": "pending",
            "liquidations": "pending",
            "long_short": "pending",
            "basis": "pending",
            "exchange_comparison": "pending",
            "stale": True,
            "missing_count": 1,
        },
        "incidents": [{"status": "investigating", "summary": reason}],
        "updated_at": _utc_now(),
        "source": "bounded status fallback",
        "endpoint": "/api/v2/status",
        "stale": True,
        "warnings": [reason],
    }


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
    if stale:
        # The in-process adapter telemetry only tracks THIS backend's own
        # /ws/market-data adapter, not the canonical binance ingestor feed in
        # Redis (the one /api/v2/market/overview reports fresh). Consult the
        # canonical feed before branding public market_data STALE while live
        # prices tick on the same page.
        try:
            canonical = _canonical_market_feed_truth(get_redis())
        except Exception:
            canonical = {}
        canonical_age = canonical.get("age_seconds")
        if (
            canonical.get("freshness_state") == "MARKET_FEED_CURRENT"
            and isinstance(canonical_age, int)
        ):
            return {
                "symbol": symbol,
                "status": "current",
                "source": "Redis ingestor feed (binance WSS primary)",
                "last_frame_at": canonical.get("last_event_at"),
                "lag_ms": canonical_age * 1000,
                "stale": False,
            }
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


def _build_v2_status_payload() -> dict[str, Any]:
    r = get_redis()
    warnings: list[str] = []
    platform_status = "available"
    api_status = "available"
    data_status = "source pending"
    paper_mode = True
    live_trading_enabled = False
    live_gate_status = "blocked_human_only"
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

    status_dimensions = build_truthful_status_dimensions(
        market_stream=market_stream,
        runtime_state=data_status,
        data_status=data_status,
        redis_available=r is not None,
        live_gate_status=live_gate_status,
        live_trading_enabled=live_trading_enabled,
        order_submission_enabled=False,
        places_real_order=False,
        account_authenticated=False,
        account_connected=False,
    )

    return {
        "status": platform_status,
        "platform_status": platform_status,
        "api_status": api_status,
        "data_status": data_status,
        "paper_mode": paper_mode,
        "live_trading_enabled": live_trading_enabled,
        "status_dimensions": status_dimensions,
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


async def _fallback_v2_status_with_market_truth(reason: str) -> dict[str, Any]:
    """Fallback status that still reports honest market-data freshness.

    The full status build can exceed its bounded runtime budget (it walks
    many Redis families); the canonical market-feed check is just 1-2 GETs,
    so give it its own small budget instead of branding market_data STALE
    whenever the FULL build is slow — live prices tick on the same page.
    """
    payload = _fallback_v2_status(reason)
    try:
        market_stream = await _bounded_status_build(
            _safe_market_stream_status,
            "BTCUSDT",
            timeout=0.4,
        )
    except Exception:
        return payload
    if isinstance(market_stream, dict) and market_stream.get("stale") is False:
        payload["market_stream"] = market_stream
        payload["market_stream_alert"] = _safe_market_stream_alert(market_stream)
        payload["status_dimensions"]["market_data"] = "LIVE"
    return payload


@router.get("/status")
async def get_v2_status() -> dict[str, Any]:
    try:
        return await _bounded_status_build(
            _build_v2_status_payload,
            timeout=V2_STATUS_BUILD_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return await _fallback_v2_status_with_market_truth(
            "Public status read exceeded bounded runtime budget"
        )
    except Exception as exc:
        return await _fallback_v2_status_with_market_truth(
            f"Public status read unavailable: {type(exc).__name__}"
        )


# ---------------------------------------------------------------------------
# /api/v2/ai/model-state  — ML model / technical analysis state
# (Consumed by the Technical Analysis page)
# ---------------------------------------------------------------------------

@router.get("/ai/model-state")
async def get_ai_model_state() -> dict[str, Any]:
    r = get_redis()
    now = _utc_now()

    ta_keys_total = 0
    ta_keys_fresh = 0
    symbols_covered = 0
    sample_btc_1m: dict[str, Any] | None = None

    if r is not None:
        try:
            ta_keys = _scan_keys(r, "v2:features:ta_full:*")
            ta_keys_total = len(ta_keys or [])
            symbols_seen: set[str] = set()
            for k in (ta_keys or [])[:200]:
                key_str = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                parts = key_str.split(":")
                if len(parts) >= 5:
                    symbol = parts[3]
                    symbols_seen.add(symbol)
                try:
                    raw = r.get(k)
                    if raw:
                        ta_keys_fresh += 1
                        if key_str.endswith("BTCUSDT:1m") and sample_btc_1m is None:
                            data = json.loads(raw)
                            if isinstance(data, dict):
                                # ta_full stores the real indicator values in a
                                # nested `indicators` dict (rsi_14, macd, atr_14,
                                # sma_20, ema_*, bb_width_pct, …) and family names in
                                # `families_present`. The old code filtered top-level
                                # `ta_`-prefixed scalars, which produced an EMPTY map
                                # (all 8 Research tiles rendered "—").
                                nested = data.get("indicators")
                                indicators_src = nested if isinstance(nested, dict) else data
                                families = data.get("families_present")
                                if not isinstance(families, list):
                                    families = [k for k in indicators_src if str(k).startswith("ta_")]
                                sample_btc_1m = {
                                    "symbol": "BTCUSDT",
                                    "timeframe": "1m",
                                    "generated_utc": data.get("generated_utc") or now,
                                    "source_label": str(data.get("source") or "redis"),
                                    "families_present": [str(f) for f in families][:12],
                                    "indicators": {
                                        k: v for k, v in indicators_src.items()
                                        if isinstance(v, (int, float)) and not isinstance(v, bool)
                                    },
                                }
                except Exception:
                    pass
            symbols_covered = len(symbols_seen)
        except Exception:
            pass

    # Determine classification
    if ta_keys_fresh > 50:
        classification = "ACTIVE_REDIS_EVIDENCE"
    elif ta_keys_fresh > 0:
        classification = "PARTIAL_EVIDENCE"
    else:
        classification = "MISSING_EVIDENCE"

    return {
        "generated_at": now,
        "classification": classification,
        "symbols_covered": symbols_covered,
        "symbols_fresh": symbols_covered,
        "ta_keys_total": ta_keys_total,
        "ta_keys_fresh": ta_keys_fresh,
        "sample_btc_1m": sample_btc_1m,
        "source": "redis:v2:features:ta_full:*",
        "stale": ta_keys_fresh == 0,
    }


# ---------------------------------------------------------------------------
# /api/v2/signals/all-timeframe-truth  — all-timeframe signal truth table
# (fallbackSource in canonicalFieldRegistry)
# ---------------------------------------------------------------------------

@router.get("/signals/all-timeframe-truth")
async def get_signals_all_timeframe_truth() -> dict[str, Any]:
    r = get_redis()
    now = _utc_now()
    truth_rows: list[dict[str, Any]] = []
    timeframes = ["1m", "5m", "15m", "1h", "4h"]

    if r is not None:
        try:
            signal_keys = _scan_keys(r, "v2:trainer:hybrid_cuda:signals:paper:*")
            for k in (signal_keys or [])[:100]:
                key_str = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                parts = key_str.split(":")
                symbol = parts[-2] if len(parts) >= 7 and parts[-1] in timeframes else parts[-1]
                tf = parts[-1] if parts[-1] in timeframes else None
                try:
                    raw = r.get(k)
                    if raw:
                        data = json.loads(raw)
                        if isinstance(data, dict):
                            truth_rows.append({
                                "symbol": symbol,
                                "timeframe": tf,
                                "side": data.get("side") or data.get("direction"),
                                "confidence": data.get("confidence"),
                                "model_source": data.get("model_source"),
                                "trainer_source": data.get("trainer_source"),
                                "generated_at": data.get("generated_at") or data.get("timestamp"),
                            })
                except Exception:
                    pass
        except Exception:
            pass

    return {
        "generated_at": now,
        "timeframes": timeframes,
        "symbols_count": len({r["symbol"] for r in truth_rows}),
        "truth_rows": truth_rows[:200],
        "total": len(truth_rows),
        "source": "redis:v2:trainer:hybrid_cuda:signals:paper:*",
        "stale": len(truth_rows) == 0,
    }
