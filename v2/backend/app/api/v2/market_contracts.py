"""Read-only V2 market/trading contracts for public trader surfaces.

These routes normalize existing public payload files into typed, honest API
states. They never place orders, cancel orders, change leverage/margin, mutate
live gates, or write execution state. Missing data returns a structured
``unavailable`` response instead of raising a server error.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.v2._common import get_redis
from app.auth.security import optional_auth, require_auth
from app.auth.users import UserRecord, safe_exchange_accounts, safe_user
from app.domain.governance.audit_chain import local_paper_audit_policy_metadata
from app.services.account_position_monitor.service import (
    BinanceFuturesReadOnlyClient,
    ExchangeReadError,
    ReadOnlyContractError,
    ReadOnlyCredentials,
    collect_account_position_evidence,
)
from app.services.credential_status import backend_readonly_credential_binding
from app.services.market_stream_alert_history import (
    append_market_stream_alert_record,
    market_stream_alert_from_telemetry,
    market_stream_alert_history_summary,
    production_market_stream_alerting_evidence,
    production_market_stream_validation_evidence,
    read_market_stream_alert_history,
)
from app.services.market_stream_alert_notifier import market_stream_alert_notifier_status
from app.services.paper_audit_ledger import local_paper_audit_ledger_metadata, read_local_paper_audit_events
from app.services.trader_account_repository import TraderPaperAccount, get_trader_account_repository

router = APIRouter(tags=["v2-market-contracts"])
stream_router = APIRouter(tags=["v2-market-streams"])

SourceType = Literal["api", "repository", "redis_live", "static_payload", "unavailable"]
Mode = Literal["paper", "read_only", "live_blocked", "paper_preview_unverified"]
BINANCE_FAPI_BASE = os.environ.get("ALPHAFORGE_BINANCE_FAPI_BASE", "https://fapi.binance.com").rstrip("/")
BINANCE_HTTP_TIMEOUT_SECONDS = float(os.environ.get("ALPHAFORGE_BINANCE_PUBLIC_TIMEOUT_SECONDS", "4"))
BINANCE_PUBLIC_WS_BASE = os.environ.get(
    "ALPHAFORGE_BINANCE_PUBLIC_WS_BASE",
    "wss://fstream.binance.com/stream",
).rstrip("/")
BINANCE_NATIVE_STREAM_ENABLED = os.environ.get("ALPHAFORGE_BINANCE_NATIVE_STREAM_ENABLED", "1") != "0"
MARKET_STREAM_TELEMETRY: dict[str, dict[str, Any]] = {}
MARKET_STREAM_TELEMETRY_LOCK = threading.Lock()
READONLY_RESOURCE_HTTP_TIMEOUT_SECONDS = float(os.environ.get("ALPHAFORGE_READONLY_RESOURCE_HTTP_TIMEOUT_SECONDS", "1.5"))
BINANCE_PUBLIC_CACHE_TTL_SECONDS = float(os.environ.get("ALPHAFORGE_BINANCE_PUBLIC_CACHE_TTL_SECONDS", "5"))
BINANCE_PUBLIC_JSON_CACHE_LOCK = threading.Lock()
BINANCE_PUBLIC_JSON_CACHE: dict[str, tuple[float, Any, str]] = {}
SIGNALS_MATRIX_CACHE_TTL_SECONDS = float(os.environ.get("ALPHAFORGE_SIGNALS_MATRIX_CACHE_TTL_SECONDS", "2"))
SIGNALS_MATRIX_CACHE_LOCK = threading.Lock()
SIGNALS_MATRIX_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
PREDICTIONS_MATRIX_CACHE_TTL_SECONDS = float(os.environ.get("ALPHAFORGE_PREDICTIONS_MATRIX_CACHE_TTL_SECONDS", "2"))
PREDICTIONS_MATRIX_CACHE_LOCK = threading.Lock()
PREDICTIONS_MATRIX_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
PAPER_ACTIVITY_CACHE_LOCK = threading.Lock()
PAPER_ACTIVITY_LAST_NON_EMPTY_POSITIONS: dict[str, Any] = {
    "positions": [],
    "updated_monotonic": 0.0,
    "updated_at": None,
}
READONLY_RESOURCE_WS_DENY_PREFIXES = (
    "/api/v2/ws/",
    "/ws/",
    "/api/v2/orders/",
    "/api/v2/orders",
    "/api/v2/backtest/run",
)
READONLY_RESOURCE_WS_STATIC_PREFIXES = (
    "/operator_runtime/",
    "/operator_truth/",
    "/v2_",
    "/tonight_live_like_paper_shadow/",
    "/enterprise_trading_cockpit/",
    "/external_manual_position_quarantine/",
    "/readonly_market_exchange_data_plane/",
    "/system_atlas_runtime_coverage/",
    "/system_atlas_gap_remediation/",
    "/phase3c_runtime_monitor_verification/",
    "/redis_memory_pressure_remediation/",
    "/redis_memory_human_approval/",
    "/redis_export_capacity_remediation/",
    "/redis_liquidations_full_export/",
    "/redis_safe_trim_packet/",
    "/autonomous_governor/",
)
READONLY_RESOURCE_WS_DENY_PARTS = (
    "/fill",
    "/cancel",
    "/submit",
    "/mutate",
    "/leverage",
    "/margin",
)
FALLBACK_RUNTIME_SOURCE = "Fallback runtime snapshot"
TRADER_ACCOUNT_REPOSITORY_SOURCE = "Trader account repository"
ADAPTIVE_CAPITAL_BASE_REL = "operator_runtime/v2_adaptive_capital_productivity/latest"
ADAPTIVE_CAPITAL_COMPACT_CACHE_LOCK = threading.Lock()
ADAPTIVE_CAPITAL_COMPACT_CACHE: dict[str, Any] = {
    "signature": None,
    "payload": None,
    "timestamp": None,
}


def _repo_root() -> Path:
    return Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))


def _public_root() -> Path:
    return _repo_root() / "v2" / "frontend" / "public"


def _market_stream_telemetry_store_path() -> Path:
    configured = os.environ.get("ALPHAFORGE_MARKET_STREAM_TELEMETRY_STORE")
    if configured:
        return Path(configured)
    return _repo_root() / "v2" / "backend" / "market_stream_telemetry.json"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _timestamp_from_payload(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    freshness = payload.get("freshness")
    if isinstance(freshness, dict) and isinstance(freshness.get("generated_at"), str):
        return freshness["generated_at"]
    for key in (
        "generated_at",
        "generated_utc",
        "generated_est",
        "timestamp",
        "received_at",
        "updated_at",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _lag_ms(timestamp: str | None) -> int | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds() * 1000))


def _read_json(relative: str) -> tuple[dict[str, Any] | None, str]:
    path = _public_root() / relative
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload if isinstance(payload, dict) else {"rows": payload}, FALLBACK_RUNTIME_SOURCE
    except Exception:
        return None, FALLBACK_RUNTIME_SOURCE


def _read_v2_redis_json(key: str) -> dict[str, Any] | None:
    if not key.startswith("v2:"):
        return None
    client = get_redis()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _json_object_from_redis_raw(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


async def _redis_get_json_object(client: Any, key: str) -> dict[str, Any] | None:
    if client is None:
        return None
    try:
        raw = await _maybe_await(client.get(key))
    except Exception:
        return None
    return _json_object_from_redis_raw(raw)


async def _redis_keys(client: Any, pattern: str) -> list[str]:
    if client is None:
        return []
    try:
        keys = await _maybe_await(client.keys(pattern))
    except Exception:
        return []
    if not isinstance(keys, (list, tuple, set)):
        return []
    normalized: list[str] = []
    for key in keys:
        if isinstance(key, bytes):
            normalized.append(key.decode("utf-8", errors="replace"))
        else:
            normalized.append(str(key))
    return normalized


def _safe_readonly_resource_target(value: str | None) -> str | None:
    if not value:
        return None
    decoded = urllib.parse.unquote(value).strip()
    if not decoded or "://" in decoded or "\\" in decoded:
        return None
    split = urllib.parse.urlsplit(decoded)
    path = split.path
    api_path = path.startswith("/api/v2/") or path.startswith("/api/v1/")
    static_json_path = path.endswith(".json") and any(
        path.startswith(prefix) for prefix in READONLY_RESOURCE_WS_STATIC_PREFIXES
    )
    if not api_path and not static_json_path:
        return None
    if ".." in path:
        return None
    if any(path.startswith(prefix) for prefix in READONLY_RESOURCE_WS_DENY_PREFIXES):
        return None
    lowered = path.lower()
    if any(part in lowered for part in READONLY_RESOURCE_WS_DENY_PARTS):
        return None
    query = f"?{split.query}" if split.query else ""
    return f"{path}{query}"


def _same_origin_api_url(path_with_query: str) -> str:
    port = os.environ.get("V2_BACKEND_PORT") or "5173"
    host = os.environ.get("V2_BACKEND_HOST") or "127.0.0.1"
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{port}{path_with_query}"


def _fetch_same_origin_readonly_json(path_with_query: str, headers: dict[str, str]) -> dict[str, Any]:
    request_headers = {"Accept": "application/json"}
    for name in ("cookie", "authorization"):
        value = headers.get(name)
        if value:
            request_headers[name.title()] = value
    request = urllib.request.Request(
        _same_origin_api_url(path_with_query),
        headers=request_headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=READONLY_RESOURCE_HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw else {}
            if isinstance(payload, dict):
                return payload
            return {
                "data": payload,
                "source": path_with_query,
                "source_type": "api",
                "endpoint": path_with_query,
                "timestamp": _utc_now(),
                "received_at": _utc_now(),
                "lag_ms": None,
                "stale": False,
                "missing_fields": [],
                "warnings": [],
                "mode": "read_only",
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except (TypeError, ValueError):
            detail = raw or str(exc)
        return {
            "data": None,
            "source": path_with_query,
            "source_type": "unavailable",
            "endpoint": path_with_query,
            "timestamp": _utc_now(),
            "received_at": _utc_now(),
            "lag_ms": None,
            "stale": True,
            "missing_fields": ["resource"],
            "warnings": [f"HTTP {exc.code}"],
            "errors": [detail],
            "mode": "read_only",
        }
    except Exception as exc:
        return {
            "data": None,
            "source": path_with_query,
            "source_type": "unavailable",
            "endpoint": path_with_query,
            "timestamp": _utc_now(),
            "received_at": _utc_now(),
            "lag_ms": None,
            "stale": True,
            "missing_fields": ["resource"],
            "warnings": [f"Read-only resource fallback unavailable: {type(exc).__name__}: {exc}"],
            "mode": "read_only",
        }


def _readonly_resource_has_auth(headers: dict[str, str]) -> bool:
    return bool(headers.get("cookie") or headers.get("authorization"))


def _first_query_value(query: dict[str, list[str]], name: str, default: str | None = None) -> str | None:
    values = query.get(name)
    if values and values[0]:
        return values[0]
    return default


def _read_static_readonly_resource_json(path: str) -> Any | None:
    if not path.endswith(".json") or not any(path.startswith(prefix) for prefix in READONLY_RESOURCE_WS_STATIC_PREFIXES):
        return None
    public_root = _public_root().resolve()
    candidate = (public_root / path.lstrip("/")).resolve()
    if public_root != candidate and public_root not in candidate.parents:
        return None
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


async def _readonly_resource_direct_payload(
    path_with_query: str,
    headers: dict[str, str] | None = None,
) -> tuple[bool, Any]:
    split = urllib.parse.urlsplit(path_with_query)
    path = split.path.rstrip("/") or "/"
    query = urllib.parse.parse_qs(split.query)
    has_auth = _readonly_resource_has_auth(headers or {})

    static_payload = await run_in_threadpool(_read_static_readonly_resource_json, path)
    if static_payload is not None:
        return True, static_payload

    if path == "/api/v2/market/overview":
        return True, await get_market_overview()
    if path == "/api/v2/realtime/manifest":
        return True, await get_realtime_manifest()
    if path == "/api/v2/data-health":
        return True, await get_data_health()
    if path == "/api/v2/adaptive-capital/dashboard":
        return True, await get_adaptive_capital_dashboard()

    market_prefix = "/api/v2/market/"
    if path.startswith(market_prefix):
        parts = [part for part in path[len(market_prefix):].split("/") if part]
        if parts:
            symbol = parts[0].upper()
            suffix = parts[1] if len(parts) > 1 else ""
            timeframe = _first_query_value(query, "timeframe", "1m") or "1m"
            if not suffix:
                return True, await get_market_detail(symbol)
            if suffix == "ticker":
                return True, await get_market_ticker(symbol)
            if suffix == "depth":
                return True, await get_market_depth(symbol)
            if suffix == "trades":
                return True, await get_recent_trades(symbol)
            if suffix == "candles":
                return True, await get_market_candles(symbol, timeframe=timeframe)
            if suffix == "indicators":
                return True, await get_market_indicators(symbol, timeframe=timeframe)
            if suffix == "derivatives":
                return True, await get_market_derivatives(symbol, timeframe=_first_query_value(query, "timeframe", "5m") or "5m")
            if suffix == "stream-status":
                return True, await get_market_stream_status(symbol)

    if path == "/api/v2/trainer/summary" or path == "/api/v2/trainer/status":
        from app.api.v2.trainer import get_trainer_summary  # noqa: PLC0415
        return True, await get_trainer_summary()
    if path == "/api/v2/pipeline/status":
        from app.api.v2.pipeline import get_pipeline_status  # noqa: PLC0415
        return True, await get_pipeline_status(
            symbols=_first_query_value(query, "symbols"),
            timeframes=_first_query_value(query, "timeframes"),
        )
    if path == "/api/v2/replay/status":
        from app.api.v2.replay import get_replay_status  # noqa: PLC0415
        return True, await get_replay_status()

    if path == "/api/v2/backtests":
        return True, await get_backtests(symbol=_first_query_value(query, "symbol"), actor=None)
    if path == "/api/v2/liquidation/levels-heatmap":
        return True, await get_liquidation_levels_heatmap(
            symbols=_first_query_value(query, "symbols"),
            timeframes=_first_query_value(query, "timeframes"),
            actor=None,
        )
    if path == "/api/v2/ai/predictions":
        return True, await get_ai_predictions(symbol=_first_query_value(query, "symbol"), actor=None)
    if path == "/api/v2/predictions/status":
        return True, await get_predictions_status()
    if path == "/api/v2/signals/status":
        return True, await get_signals_status()
    if path == "/api/v2/orchestrator/status":
        return True, await get_orchestrator_status()
    if path == "/api/v2/risk/status":
        return True, await get_risk_status()
    if path == "/api/v2/paper/status":
        return True, await get_paper_status(actor=None)
    if path == "/api/v2/paper/activity":
        return True, await get_paper_activity(actor=None)
    if path.startswith("/api/v2/mobile/"):
        from app.api.v2 import mobile as mobile_api  # noqa: PLC0415

        if path == "/api/v2/mobile/dashboard":
            return True, await mobile_api.get_mobile_dashboard(actor=None)
        if path == "/api/v2/mobile/positions":
            return True, await mobile_api.get_mobile_positions(actor=None)
        if path == "/api/v2/mobile/signals":
            return True, await mobile_api.get_mobile_signals(
                limit=int(_first_query_value(query, "limit", "50") or "50"),
                actionable_only=(_first_query_value(query, "actionable_only") or "").lower() == "true",
                actor=None,
            )
        if path == "/api/v2/mobile/alerts":
            return True, await mobile_api.get_mobile_alerts(
                limit=int(_first_query_value(query, "limit", "30") or "30"),
                actor=None,
            )
        if path == "/api/v2/mobile/health":
            return True, await mobile_api.get_mobile_health(actor=None)
        if path == "/api/v2/mobile/risk-status":
            return True, await mobile_api.get_mobile_risk_status(actor=None)
        if path == "/api/v2/mobile/paper-summary":
            return True, await mobile_api.get_mobile_paper_summary(actor=None)

    explain_symbol = _first_query_value(query, "symbol")
    explain_timeframe = _first_query_value(query, "timeframe", "1h")
    if path == "/api/v2/predictions/explain" and explain_symbol and explain_timeframe:
        return True, await get_prediction_explain(symbol=explain_symbol, timeframe=explain_timeframe)
    if path == "/api/v2/signals/explain" and explain_symbol and explain_timeframe:
        return True, await get_signal_explain(symbol=explain_symbol, timeframe=explain_timeframe)

    if has_auth:
        return False, None

    if path == "/api/v2/alerts":
        from app.api.v2.alerts_contracts import get_alerts  # noqa: PLC0415
        return True, get_alerts(None)
    if path == "/api/v2/portfolio":
        return True, await get_portfolio(None)
    if path == "/api/v2/account/readiness":
        return True, await get_account_readiness(None)
    if path == "/api/v2/account/positions":
        return True, await get_account_positions(None)
    if path == "/api/v2/execution/orders":
        return True, await get_execution_orders(None)
    if path == "/api/v2/execution/executions":
        return True, await get_execution_executions(None)
    if path == "/api/v2/execution/audit-events":
        return True, await get_execution_audit_events(None)
    if path == "/api/v2/signals":
        return True, await get_signals(
            symbol=_first_query_value(query, "symbol"),
            timeframe=_first_query_value(query, "timeframe", "5m") or "5m",
            actor=None,
        )
    if path == "/api/v2/signals/matrix":
        return True, await get_signals_matrix(
            symbols=_first_query_value(query, "symbols"),
            timeframes=_first_query_value(query, "timeframes"),
            actor=None,
        )
    if path == "/api/v2/predictions/matrix":
        return True, await get_predictions_matrix(
            symbols=_first_query_value(query, "symbols"),
            timeframes=_first_query_value(query, "timeframes"),
            actor=None,
        )

    return False, None


def _readonly_resource_direct_payload_sync(
    path_with_query: str,
    headers: dict[str, str] | None = None,
) -> tuple[bool, Any]:
    return asyncio.run(_readonly_resource_direct_payload(path_with_query, headers))


def _readonly_resource_ws_payload(target: str, payload: Any, started: float) -> dict[str, Any]:
    elapsed_ms = round((time.monotonic() - started) * 1000)
    if isinstance(payload, dict) and isinstance(payload.get("source"), str) and isinstance(payload.get("source_type"), str):
        result = {
            **payload,
            "transport": "websocket",
            "resource_path": target,
        }
        if "endpoint" not in result:
            result["endpoint"] = target
        if "lag_ms" not in result:
            result["lag_ms"] = elapsed_ms
        return result

    source_type = "static_payload" if target.split("?", 1)[0].endswith(".json") else "api"
    return {
        "data": payload,
        "source": target,
        "source_type": source_type,
        "endpoint": target,
        "timestamp": _utc_now(),
        "received_at": _utc_now(),
        "lag_ms": elapsed_ms,
        "stale": False,
        "missing_fields": [],
        "warnings": [],
        "mode": "read_only",
        "transport": "websocket",
        "resource_path": target,
    }


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _integer(value: Any) -> int | None:
    number = _float(value)
    return int(number) if number is not None else None


def _iso_from_ms(value: Any) -> str | None:
    number = _float(value)
    if number is None or number <= 0:
        return None
    return datetime.fromtimestamp(number / 1000, UTC).isoformat().replace("+00:00", "Z")


def _epoch_seconds_from_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).timestamp()
    except ValueError:
        return None


def _timestamp_from_redis_payload(payload: dict[str, Any] | None) -> str | None:
    timestamp = _timestamp_from_payload(payload)
    if timestamp:
        return timestamp
    if not isinstance(payload, dict):
        return None
    for key in ("last_candle_ts_ms", "liquidation_updated_ts", "liquidation_last_event_ts"):
        timestamp = _iso_from_ms(payload.get(key))
        if timestamp:
            return timestamp
    return None


def _point_from_indicator(payload: dict[str, Any], indicators: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    value = None
    for key in keys:
        value = _float(indicators.get(key))
        if value is not None:
            break
    timestamp_ms = _float(payload.get("last_candle_ts_ms"))
    if value is None or timestamp_ms is None:
        return []
    return [{"time": int(timestamp_ms // 1000), "value": value}]


def _event_lag_ms(value: Any) -> int | None:
    timestamp = _iso_from_ms(value)
    return _lag_ms(timestamp)


def _closed_candles_from_binance_klines(klines: Any) -> list[dict[str, Any]]:
    if not isinstance(klines, list):
        return []
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    candles: list[dict[str, Any]] = []
    for row in klines:
        if not isinstance(row, list) or len(row) < 11:
            continue
        open_time_ms = int(_float(row[0]) or 0)
        close_time_ms = int(_float(row[6]) or 0)
        if open_time_ms <= 0 or close_time_ms <= 0 or close_time_ms > now_ms:
            continue
        candle = {
            "time": open_time_ms // 1000,
            "open_time_ms": open_time_ms,
            "close_time_ms": close_time_ms,
            "open": _float(row[1]),
            "high": _float(row[2]),
            "low": _float(row[3]),
            "close": _float(row[4]),
            "volume": _float(row[5]),
            "quote_volume": _float(row[7]),
            "trade_count": int(_float(row[8]) or 0),
            "taker_buy_base_volume": _float(row[9]),
            "taker_buy_quote_volume": _float(row[10]),
        }
        if all(candle[key] is not None for key in ("open", "high", "low", "close", "volume")):
            candles.append(candle)
    return candles


def _ema_series(candles: list[dict[str, Any]], period: int) -> list[dict[str, Any]]:
    closes = [_float(candle.get("close")) for candle in candles]
    if len(closes) < period or any(value is None for value in closes[:period]):
        return []
    seed_values = [value for value in closes[:period] if value is not None]
    if len(seed_values) < period:
        return []
    alpha = 2 / (period + 1)
    ema = sum(seed_values) / period
    points: list[dict[str, Any]] = [{"time": candles[period - 1]["time"], "value": ema}]
    for index in range(period, len(candles)):
        close = closes[index]
        if close is None:
            continue
        ema = (close * alpha) + (ema * (1 - alpha))
        points.append({"time": candles[index]["time"], "value": ema})
    return points


def _bollinger_series(candles: list[dict[str, Any]], period: int = 20, multiplier: float = 2.0) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    closes = [_float(candle.get("close")) for candle in candles]
    if len(closes) < period:
        return [], [], []
    upper: list[dict[str, Any]] = []
    lower: list[dict[str, Any]] = []
    middle: list[dict[str, Any]] = []
    for index in range(period - 1, len(candles)):
        window = closes[index - period + 1:index + 1]
        if any(value is None for value in window):
            continue
        values = [value for value in window if value is not None]
        mean = sum(values) / period
        variance = sum((value - mean) ** 2 for value in values) / period
        std_dev = variance ** 0.5
        time = candles[index]["time"]
        middle.append({"time": time, "value": mean})
        upper.append({"time": time, "value": mean + (multiplier * std_dev)})
        lower.append({"time": time, "value": mean - (multiplier * std_dev)})
    return upper, lower, middle


MARKET_CONTRACT_TIMEFRAMES = {"1m", "3m", "5m", "15m", "1h", "4h", "1d", "1w"}


def _safe_symbol(symbol: str) -> str:
    cleaned = "".join(ch for ch in symbol.upper() if ch.isalnum())
    return cleaned or "BTCUSDT"


def _strict_market_symbol(symbol: str | None) -> str | None:
    raw = (symbol or "").strip().upper()
    if not raw or not raw.isalnum():
        return None
    return raw


def _safe_order_symbol(symbol: str) -> str | None:
    raw = symbol.strip().upper()
    cleaned = "".join(ch for ch in raw if ch.isalnum())
    if not cleaned or cleaned != raw:
        return None
    return cleaned


def _safe_timeframe(timeframe: str) -> str:
    return timeframe if timeframe in MARKET_CONTRACT_TIMEFRAMES else "1m"


def _strict_timeframe(timeframe: str | None) -> str | None:
    raw = (timeframe or "").strip()
    return raw if raw in MARKET_CONTRACT_TIMEFRAMES else None


def _invalid_market_symbol_response(endpoint: str) -> dict[str, Any]:
    return _unavailable(
        endpoint=endpoint,
        symbol=None,
        missing_fields=["symbol"],
        warning="Enter a valid market symbol",
    )


def _invalid_market_timeframe_response(endpoint: str, symbol: str | None) -> dict[str, Any]:
    return _unavailable(
        endpoint=endpoint,
        symbol=symbol,
        missing_fields=["timeframe"],
        warning="Select a supported chart timeframe",
    )


def _read_market_stream_telemetry_store() -> dict[str, dict[str, Any]]:
    path = _market_stream_telemetry_store_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, dict):
        return {}
    return {
        _safe_symbol(symbol): dict(value)
        for symbol, value in streams.items()
        if isinstance(value, dict)
    }


def _write_market_stream_telemetry_store(streams: dict[str, dict[str, Any]]) -> None:
    path = _market_stream_telemetry_store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"streams": streams}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError:
        return


def _record_market_stream_event(
    symbol: str,
    *,
    source: str,
    event: str,
    error: str | None = None,
) -> dict[str, Any]:
    safe_symbol = _safe_symbol(symbol)
    now = _utc_now()
    with MARKET_STREAM_TELEMETRY_LOCK:
        persisted = _read_market_stream_telemetry_store()
        current = MARKET_STREAM_TELEMETRY.setdefault(
            safe_symbol,
            persisted.get(
                safe_symbol,
                {
                    "symbol": safe_symbol,
                    "source": "unavailable",
                    "last_event": None,
                    "last_frame_at": None,
                    "last_error": None,
                    "connect_attempts": 0,
                    "native_frames": 0,
                    "fallback_snapshots": 0,
                    "updated_at": now,
                },
            ),
        )
        current["source"] = source
        current["last_event"] = event
        current["updated_at"] = now
        if event == "connect_attempt":
            current["connect_attempts"] = int(current.get("connect_attempts") or 0) + 1
        if event == "native_frame":
            current["native_frames"] = int(current.get("native_frames") or 0) + 1
            current["last_frame_at"] = now
        if event == "fallback_snapshot":
            current["fallback_snapshots"] = int(current.get("fallback_snapshots") or 0) + 1
            current["last_frame_at"] = now
        if error:
            current["last_error"] = error
        persisted[safe_symbol] = dict(current)
        _write_market_stream_telemetry_store(persisted)
        next_telemetry = _market_stream_telemetry(safe_symbol)
        try:
            append_market_stream_alert_record(safe_symbol, next_telemetry)
        except ValueError:
            current["last_error"] = "stream alert history rejected unsafe fields"
        except OSError:
            current["last_error"] = "stream alert history unavailable"
        return dict(current)


def _market_stream_telemetry(symbol: str) -> dict[str, Any]:
    safe_symbol = _safe_symbol(symbol)
    current = MARKET_STREAM_TELEMETRY.get(safe_symbol)
    if current is None:
        current = _read_market_stream_telemetry_store().get(safe_symbol)
        if current is not None:
            MARKET_STREAM_TELEMETRY[safe_symbol] = current
    if current is None:
        return {
            "symbol": safe_symbol,
            "source": "unavailable",
            "last_event": None,
            "last_frame_at": None,
            "last_error": None,
            "connect_attempts": 0,
            "native_frames": 0,
            "fallback_snapshots": 0,
            "updated_at": None,
            "lag_ms": None,
            "stale": True,
        }
    lag = _lag_ms(current.get("last_frame_at"))
    return {
        **current,
        "lag_ms": lag,
        "stale": lag is None or lag > 30_000,
    }


def _market_stream_alert(telemetry: dict[str, Any]) -> dict[str, Any]:
    return market_stream_alert_from_telemetry(telemetry)


def _binance_public_json(path: str, params: dict[str, Any]) -> tuple[Any | None, str, str | None]:
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
    url = f"{BINANCE_FAPI_BASE}{path}" + (f"?{query}" if query else "")
    cache_key = f"{path}?{query}"
    now = time.monotonic()
    if BINANCE_PUBLIC_CACHE_TTL_SECONDS > 0:
        with BINANCE_PUBLIC_JSON_CACHE_LOCK:
            cached = BINANCE_PUBLIC_JSON_CACHE.get(cache_key)
            if cached is not None and now - cached[0] <= BINANCE_PUBLIC_CACHE_TTL_SECONDS:
                return cached[1], cached[2], None
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "alphaforge-v2-public-market-readonly/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=BINANCE_HTTP_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
        if BINANCE_PUBLIC_CACHE_TTL_SECONDS > 0:
            with BINANCE_PUBLIC_JSON_CACHE_LOCK:
                BINANCE_PUBLIC_JSON_CACHE[cache_key] = (time.monotonic(), payload, url)
        return payload, url, None
    except Exception as exc:
        return None, url, f"Binance public market source unavailable: {type(exc).__name__}"


async def _binance_public_json_async(path: str, params: dict[str, Any]) -> tuple[Any | None, str, str | None]:
    return await run_in_threadpool(_binance_public_json, path, params)


def _native_stream_url(symbol: str, timeframe: str) -> str:
    lower_symbol = _safe_symbol(symbol).lower()
    safe_timeframe = _safe_timeframe(timeframe)
    streams = "/".join(
        [
            f"{lower_symbol}@ticker",
            f"{lower_symbol}@bookTicker",
            f"{lower_symbol}@markPrice@1s",
            f"{lower_symbol}@depth20@100ms",
            f"{lower_symbol}@aggTrade",
            f"{lower_symbol}@kline_{safe_timeframe}",
        ]
    )
    return f"{BINANCE_PUBLIC_WS_BASE}?streams={streams}"


def _native_stream_matches_request(stream: str, symbol: str, timeframe: str) -> bool:
    stream_symbol, _, channel = stream.partition("@")
    if not stream_symbol or not channel:
        return False
    if _safe_symbol(stream_symbol) != _safe_symbol(symbol):
        return False
    if channel.startswith("kline_"):
        return channel.removeprefix("kline_") == _safe_timeframe(timeframe)
    return channel in {"ticker", "bookTicker", "markPrice@1s", "depth20@100ms", "aggTrade", "trade"}


def _native_candle_missing_fields(candle: dict[str, Any]) -> list[str]:
    missing = [
        key
        for key in ("open", "high", "low", "close")
        if _float(candle.get(key)) is None
    ]
    open_price = _float(candle.get("open"))
    high_price = _float(candle.get("high"))
    low_price = _float(candle.get("low"))
    close_price = _float(candle.get("close"))
    valid_ohlc = (
        open_price is not None
        and high_price is not None
        and low_price is not None
        and close_price is not None
        and open_price > 0
        and high_price > 0
        and low_price > 0
        and close_price > 0
        and low_price <= open_price <= high_price
        and low_price <= close_price <= high_price
    )
    if not valid_ohlc:
        missing.append("valid_ohlc")
    return missing


def _native_base_response(
    *,
    endpoint: str,
    source: str,
    event_time_ms: Any,
    data: Any,
    missing_fields: list[str],
    warnings: list[str],
    symbol: str,
) -> dict[str, Any]:
    timestamp = _iso_from_ms(event_time_ms) or _utc_now()
    return {
        "data": data,
        "source": source,
        "source_type": "api",
        "endpoint": endpoint,
        "timestamp": timestamp,
        "received_at": _utc_now(),
        "lag_ms": _event_lag_ms(event_time_ms),
        "stale": False,
        "missing_fields": missing_fields,
        "warnings": [
            "Read-only Binance USD-M public WebSocket; no signed account data and no exchange mutation",
            *warnings,
        ],
        "symbol": symbol,
        "exchange": "Binance USD-M",
        "mode": "read_only",
    }


def _depth_rows(rows: Any) -> list[list[float | None]]:
    if not isinstance(rows, list):
        return []
    normalized: list[list[float | None]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        normalized.append([_float(row[0]), _float(row[1])])
    return normalized


def _ticker_missing_fields(data: dict[str, Any]) -> list[str]:
    expected = [
        "last_price",
        "mark_price",
        "index_price",
        "change_24h",
        "high_24h",
        "low_24h",
        "volume_24h",
        "turnover_24h",
        "funding_rate",
        "next_funding",
        "open_interest",
        "bid",
        "ask",
        "spread_bps",
    ]
    return [field for field in expected if data.get(field) is None]


def _native_ticker_data(symbol: str, current: dict[str, Any] | None = None) -> dict[str, Any]:
    base = {
        "symbol": symbol,
        "last_price": None,
        "mark_price": None,
        "index_price": None,
        "change_1h": None,
        "change_4h": None,
        "change_24h": None,
        "high_24h": None,
        "low_24h": None,
        "volume_24h": None,
        "turnover_24h": None,
        "funding_rate": None,
        "next_funding": None,
        "open_interest": None,
        "open_interest_change": None,
        "bid": None,
        "ask": None,
        "spread_bps": None,
    }
    if current:
        base.update(current)
    return base


def _apply_native_stream_message(
    *,
    raw: str,
    state: dict[str, Any],
    symbol: str,
    timeframe: str,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    stream = str(payload.get("stream") or "")
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    if not _native_stream_matches_request(stream, symbol, timeframe):
        return None
    endpoint = f"{BINANCE_PUBLIC_WS_BASE} {stream}"
    event_time_ms = data.get("E") or data.get("T") or datetime.now(UTC).timestamp() * 1000
    safe_symbol = _safe_symbol(symbol)

    if stream.endswith("@ticker"):
        ticker_data = _native_ticker_data(safe_symbol, state.get("ticker", {}).get("data"))
        change_pct = _float(data.get("P"))
        ticker_data.update(
            {
                "last_price": _float(data.get("c")) or ticker_data.get("last_price"),
                "change_24h": (change_pct / 100)
                if change_pct is not None
                else ticker_data.get("change_24h"),
                "high_24h": _float(data.get("h")) or ticker_data.get("high_24h"),
                "low_24h": _float(data.get("l")) or ticker_data.get("low_24h"),
                "volume_24h": _float(data.get("v")) or ticker_data.get("volume_24h"),
                "turnover_24h": _float(data.get("q")) or ticker_data.get("turnover_24h"),
                "bid": _float(data.get("b")) or ticker_data.get("bid"),
                "ask": _float(data.get("a")) or ticker_data.get("ask"),
            }
        )
        bid = _float(ticker_data.get("bid"))
        ask = _float(ticker_data.get("ask"))
        last = _float(ticker_data.get("last_price"))
        ticker_data["spread_bps"] = (
            ((ask - bid) / last * 10_000)
            if bid is not None and ask is not None and last
            else ticker_data.get("spread_bps")
        )
        state["ticker"] = _native_base_response(
            endpoint=endpoint,
            source="binance_usdm_public_ticker_ws",
            event_time_ms=event_time_ms,
            data=ticker_data,
            missing_fields=_ticker_missing_fields(ticker_data),
            warnings=[
                "24h public ticker stream; open interest still comes from REST/repository "
                "until native source is wired"
            ],
            symbol=safe_symbol,
        )
        return state["ticker"]

    if stream.endswith("@bookTicker"):
        ticker_data = _native_ticker_data(safe_symbol, state.get("ticker", {}).get("data"))
        bid = _float(data.get("b"))
        ask = _float(data.get("a"))
        last = _float(ticker_data.get("last_price"))
        if last is None and bid is not None and ask is not None:
            last = (bid + ask) / 2
        ticker_data.update({"last_price": last, "bid": bid, "ask": ask})
        ticker_data["spread_bps"] = (
            ((ask - bid) / last * 10_000)
            if bid is not None and ask is not None and last
            else None
        )
        state["ticker"] = _native_base_response(
            endpoint=endpoint,
            source="binance_usdm_public_book_ticker_ws",
            event_time_ms=event_time_ms,
            data=ticker_data,
            missing_fields=_ticker_missing_fields(ticker_data),
            warnings=["Book ticker stream updates top-of-book only"],
            symbol=safe_symbol,
        )
        return state["ticker"]

    if stream.endswith("@markPrice@1s"):
        ticker_data = _native_ticker_data(safe_symbol, state.get("ticker", {}).get("data"))
        next_funding_ms = _float(data.get("T"))
        ticker_data.update(
            {
                "mark_price": _float(data.get("p")) or ticker_data.get("mark_price"),
                "index_price": _float(data.get("i")) or ticker_data.get("index_price"),
                "funding_rate": _float(data.get("r"))
                if _float(data.get("r")) is not None
                else ticker_data.get("funding_rate"),
                "next_funding": _iso_from_ms(next_funding_ms)
                if next_funding_ms
                else ticker_data.get("next_funding"),
            }
        )
        state["ticker"] = _native_base_response(
            endpoint=endpoint,
            source="binance_usdm_public_mark_price_ws",
            event_time_ms=event_time_ms,
            data=ticker_data,
            missing_fields=_ticker_missing_fields(ticker_data),
            warnings=["Mark price stream updates mark, index, funding, and next funding only"],
            symbol=safe_symbol,
        )
        return state["ticker"]

    if "@depth20" in stream:
        bids = _depth_rows(data.get("b") or data.get("bids"))
        asks = _depth_rows(data.get("a") or data.get("asks"))
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        mid = ((best_bid + best_ask) / 2) if best_bid is not None and best_ask is not None else None
        depth_data = {
            "symbol": safe_symbol,
            "bids": bids,
            "asks": asks,
            "spread_bps": (
                ((best_ask - best_bid) / mid * 10_000)
                if best_bid is not None and best_ask is not None and mid
                else None
            ),
            "depth_type": "binance_public_depth20_stream",
        }
        state["depth"] = _native_base_response(
            endpoint=endpoint,
            source="binance_usdm_public_depth_ws",
            event_time_ms=event_time_ms,
            data=depth_data,
            missing_fields=[] if bids and asks else ["bids", "asks"],
            warnings=[],
            symbol=safe_symbol,
        )
        return state["depth"]

    if stream.endswith("@aggTrade"):
        price = _float(data.get("p"))
        size = _float(data.get("q"))
        if price is None or size is None:
            return None
        prior = []
        if isinstance(state.get("trades"), dict):
            prior_data = state["trades"].get("data")
            if isinstance(prior_data, dict) and isinstance(prior_data.get("trades"), list):
                prior = prior_data["trades"]
        trade = {
            "time": _iso_from_ms(data.get("T") or event_time_ms) or _utc_now(),
            "price": price,
            "size": size,
            "side": "sell" if data.get("m") is True else "buy",
        }
        state["trades"] = _native_base_response(
            endpoint=endpoint,
            source="binance_usdm_public_agg_trade_ws",
            event_time_ms=data.get("T") or event_time_ms,
            data={"symbol": safe_symbol, "trades": [trade, *prior][:64]},
            missing_fields=[],
            warnings=[],
            symbol=safe_symbol,
        )
        return state["trades"]

    if "@kline_" in stream:
        kline = data.get("k")
        if not isinstance(kline, dict):
            return None
        open_time_ms = _float(kline.get("t"))
        close_time_ms = _float(kline.get("T"))
        candle = {
            "time": int(open_time_ms // 1000) if open_time_ms else None,
            "open_time_ms": int(open_time_ms) if open_time_ms else None,
            "close_time_ms": int(close_time_ms) if close_time_ms else None,
            "open": _float(kline.get("o")),
            "high": _float(kline.get("h")),
            "low": _float(kline.get("l")),
            "close": _float(kline.get("c")),
            "volume": _float(kline.get("v")),
            "quote_volume": _float(kline.get("q")),
            "trade_count": int(_float(kline.get("n")) or 0),
            "taker_buy_base_volume": _float(kline.get("V")),
            "taker_buy_quote_volume": _float(kline.get("Q")),
            "is_final": kline.get("x") is True,
            "source": "binance_usdm_public_kline_ws",
        }
        missing_fields = _native_candle_missing_fields(candle)
        if "valid_ohlc" in missing_fields:
            state["candles"] = _native_base_response(
                endpoint=endpoint,
                source="binance_usdm_public_kline_ws",
                event_time_ms=event_time_ms,
                data={
                    "symbol": safe_symbol,
                    "timeframe": _safe_timeframe(timeframe),
                    "candles": [],
                    "candle_count": 0,
                },
                missing_fields=missing_fields,
                warnings=["Invalid public kline frame ignored before chart update"],
                symbol=safe_symbol,
            )
            return state["candles"]
        state["candles"] = _native_base_response(
            endpoint=endpoint,
            source="binance_usdm_public_kline_ws",
            event_time_ms=event_time_ms,
            data={
                "symbol": safe_symbol,
                "timeframe": _safe_timeframe(timeframe),
                "candles": [candle],
                "candle_count": 1,
            },
            missing_fields=[],
            warnings=["Forming candle is display-only and is not treated as final evidence"]
            if candle["is_final"] is False
            else ["Closed candle stream update"],
            symbol=safe_symbol,
        )
        return state["candles"]

    return None


def _native_stream_snapshot(symbol: str, state: dict[str, Any]) -> dict[str, Any]:
    safe_symbol = _safe_symbol(symbol)
    stream_health = _market_stream_telemetry(safe_symbol)
    envelopes = [
        item
        for item in (state.get("ticker"), state.get("depth"), state.get("trades"), state.get("candles"))
        if isinstance(item, dict)
    ]
    stale = any(bool(item.get("stale")) for item in envelopes)
    missing_fields = sorted(
        {str(field) for item in envelopes for field in item.get("missing_fields", [])}
    )
    warnings = [
        "Read-only backend native Binance USD-M public WebSocket; no signed account data and no exchange mutation",
        "Production stream telemetry is partial until reconnect metrics and alerting are promoted",
    ]
    for item in envelopes:
        warnings.extend(str(warning) for warning in item.get("warnings", []))
    return {
        "type": "market_snapshot",
        "endpoint": "/ws/market-data",
        "received_at": _utc_now(),
        "symbol": safe_symbol,
        "exchange": "Binance USD-M",
        "mode": "read_only",
        "source": "binance_usdm_public_websocket_adapter",
        "source_type": "api",
        "stale": stale,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "ticker": state.get("ticker"),
        "depth": state.get("depth"),
        "trades": state.get("trades"),
        "candles": state.get("candles"),
        "stream_health": stream_health,
        "stream_alert": _market_stream_alert(stream_health),
    }


def _binance_market_snapshot(symbol: str) -> tuple[dict[str, Any] | None, list[str], list[str], list[str]]:
    safe_symbol = _safe_symbol(symbol)
    warnings: list[str] = []
    sources: list[str] = []
    ticker, ticker_source, ticker_warning = _binance_public_json("/fapi/v1/ticker/24hr", {"symbol": safe_symbol})
    premium, premium_source, premium_warning = _binance_public_json("/fapi/v1/premiumIndex", {"symbol": safe_symbol})
    oi, oi_source, oi_warning = _binance_public_json("/fapi/v1/openInterest", {"symbol": safe_symbol})
    sources.extend([ticker_source, premium_source, oi_source])
    warnings.extend([warning for warning in (ticker_warning, premium_warning, oi_warning) if warning])
    if not isinstance(ticker, dict) or _float(ticker.get("lastPrice")) is None:
        return None, ["last_price", "ticker_24h"], warnings, sources

    bid = _float(ticker.get("bidPrice"))
    ask = _float(ticker.get("askPrice"))
    last_price = _float(ticker.get("lastPrice"))
    spread_bps = ((ask - bid) / last_price * 10_000) if bid is not None and ask is not None and last_price else None
    data = {
        "symbol": safe_symbol,
        "last_price": last_price,
        "mark_price": _float(premium.get("markPrice")) if isinstance(premium, dict) else None,
        "index_price": _float(premium.get("indexPrice")) if isinstance(premium, dict) else None,
        "change_1h": None,
        "change_4h": None,
        "change_24h": (_float(ticker.get("priceChangePercent")) / 100) if _float(ticker.get("priceChangePercent")) is not None else None,
        "high_24h": _float(ticker.get("highPrice")),
        "low_24h": _float(ticker.get("lowPrice")),
        "volume_24h": _float(ticker.get("volume")),
        "turnover_24h": _float(ticker.get("quoteVolume")),
        "funding_rate": _float(premium.get("lastFundingRate")) if isinstance(premium, dict) else None,
        "next_funding": _iso_from_ms(premium.get("nextFundingTime")) if isinstance(premium, dict) else None,
        "open_interest": _float(oi.get("openInterest")) if isinstance(oi, dict) else None,
        "open_interest_change": None,
        "bid": bid,
        "ask": ask,
        "spread_bps": spread_bps,
    }
    missing = [key for key, value in data.items() if key != "symbol" and value is None]
    return data, missing, warnings, sources


def _base_response(
    *,
    endpoint: str,
    data: Any,
    source: str,
    source_type: SourceType,
    timestamp: str | None,
    missing_fields: list[str],
    warnings: list[str] | None = None,
    symbol: str | None = None,
    exchange: str | None = "Binance USD-M",
    mode: Mode = "read_only",
    trader_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lag = _lag_ms(timestamp)
    unavailable = source_type == "unavailable"
    response = {
        "data": data,
        "source": source,
        "source_type": source_type,
        "endpoint": endpoint,
        "timestamp": timestamp,
        "received_at": _utc_now(),
        "lag_ms": lag,
        "stale": unavailable or lag is None or lag > 120_000,
        "missing_fields": missing_fields,
        "warnings": warnings or [],
        "symbol": symbol,
        "exchange": exchange if symbol else None,
        "mode": mode,
    }
    if trader_context is not None:
        response["trader_context"] = trader_context
        response["account_scope"] = _account_scope_context(trader_context, data)
    return response


def _paper_redis_source_type(warnings: list[str]) -> SourceType:
    """Return 'unavailable' when Redis was unreachable, 'redis_live' otherwise."""
    return (
        "unavailable"
        if any("Redis unavailable for paper activity" in w for w in warnings)
        else "redis_live"
    )


def _unavailable(
    *,
    endpoint: str,
    missing_fields: list[str],
    warning: str,
    symbol: str | None = None,
    mode: Mode = "read_only",
) -> dict[str, Any]:
    return _base_response(
        endpoint=endpoint,
        data=None,
        source="unavailable",
        source_type="unavailable",
        timestamp=None,
        missing_fields=missing_fields,
        warnings=[warning],
        symbol=symbol,
        mode=mode,
    )


def _trader_context(actor: UserRecord | None) -> dict[str, Any]:
    if actor is None:
        return {
            "scope": "public_read_only",
            "trader_id": None,
            "paper_account_id": None,
            "username": None,
            "exchange_accounts": [],
            "account_specific": False,
            "warnings": ["Sign in to view trader-specific paper account context"],
        }
    actor_scope_present = bool(actor.get("trader_id") and actor.get("paper_account_id"))
    return {
        "scope": "authenticated_trader",
        "trader_id": actor.get("trader_id"),
        "paper_account_id": actor.get("paper_account_id"),
        "username": actor.get("username"),
        "exchange_accounts": safe_user(actor).get("exchange_accounts", []),
        "account_specific": actor_scope_present,
        "warnings": [] if actor_scope_present else ["Trader profile and paper workspace are required for account-specific data"],
    }


def _account_scope_context(trader_context: dict[str, Any], data: Any) -> dict[str, Any]:
    trader_id = _scope_token(trader_context.get("trader_id"))
    paper_account_id = _scope_token(trader_context.get("paper_account_id"))
    data_account_specific = isinstance(data, dict) and data.get("account_specific") is True
    data_trader_id = _scope_token(data.get("trader_id")) if isinstance(data, dict) else None
    data_paper_account_id = _scope_token(data.get("paper_account_id")) if isinstance(data, dict) else None
    authenticated = trader_context.get("scope") == "authenticated_trader"
    actor_scope_present = bool(trader_id and paper_account_id)
    data_scope_matches_actor = bool(
        data_account_specific
        and trader_id
        and paper_account_id
        and data_trader_id == trader_id
        and data_paper_account_id == paper_account_id
    )
    scope_verified = authenticated and actor_scope_present and data_scope_matches_actor
    return {
        "scope": trader_context.get("scope"),
        "trader_id": trader_id,
        "paper_account_id": paper_account_id,
        "data_trader_id": data_trader_id,
        "data_paper_account_id": data_paper_account_id,
        "authenticated": authenticated,
        "actor_scope_present": actor_scope_present,
        "data_account_specific": data_account_specific,
        "data_scope_matches_actor": data_scope_matches_actor,
        "scope_verified": scope_verified,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
        "warnings": []
        if scope_verified
        else [
            (
                "Account-specific data scope does not match authenticated trader"
                if authenticated and data_account_specific
                else "Account-specific data is unavailable or withheld"
            )
            if authenticated
            else "Sign in to view trader-specific account data"
        ],
    }


def _actor_account_scope_context(actor: UserRecord | None, data: Any) -> dict[str, Any]:
    return _account_scope_context(_trader_context(actor), data)


def _terminal_payload() -> tuple[dict[str, Any] | None, str]:
    return _read_json("operator_runtime/v2_trade_terminal/latest/trade_terminal_payload.json")


def _portfolio_payload() -> tuple[dict[str, Any] | None, str]:
    return _read_json("operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json")


def _paper_payload() -> tuple[dict[str, Any] | None, str]:
    return _read_json("operator_runtime/paper_online/latest/paper_runtime_status.json")


# Paper system starts with $10,000 in capital. Equity = starting_capital + pnl_changes.
PAPER_INITIAL_CAPITAL = 10_000.0


def _chart_payload(symbol: str, timeframe: str) -> tuple[dict[str, Any] | None, str]:
    safe_symbol = symbol.upper().replace("/", "").replace(":", "")
    safe_tf = timeframe.replace("/", "").replace(":", "")
    return _read_json(
        f"operator_runtime/v2_professional_market_chart/latest/{safe_symbol}_{safe_tf}_chart.json"
    )


def _manifest_payload() -> tuple[dict[str, Any] | None, str]:
    return _read_json("operator_runtime/v2_professional_market_chart/latest/operator_dashboard_payload.json")


def _compact_dict(payload: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return {key: payload[key] for key in keys if key in payload}


def _compact_near_a_grade(payload: Any) -> dict[str, Any] | None:
    return _compact_dict(
        payload,
        (
            "symbol",
            "timeframe",
            "side",
            "confidence",
            "confidence_threshold",
            "confidence_gap_to_a_grade",
            "after_cost_edge_bps",
            "minimum_after_cost_edge_bps",
            "edge_gap_to_positive_bps",
            "allocator_decision",
            "allocator_blocked",
            "reasons",
            "eligibility_gap_score",
        ),
    ) or None


def _compact_a_grade_source_readiness(payload: Any) -> dict[str, Any]:
    compact = _compact_dict(
        payload,
        (
            "row_count",
            "directional_row_count",
            "confidence_present_count",
            "confidence_at_or_above_threshold_count",
            "edge_present_count",
            "positive_after_cost_edge_count",
            "positive_edge_below_confidence_count",
            "positive_edge_but_below_confidence_count",
            "a_grade_before_temporal_count",
            "event_time_valid_candidate_count",
            "best_configuration_count",
            "no_feasible_configuration_count",
            "temporal_invalid_count",
            "not_a_grade_reason_counts",
            "max_confidence",
            "max_after_cost_edge_bps",
            "confidence_threshold",
            "after_cost_edge_bps_min_exclusive",
            "confidence_gap_to_threshold",
        ),
    )
    closest = _compact_near_a_grade((payload or {}).get("closest_near_a_grade") if isinstance(payload, dict) else None)
    if closest:
        compact["closest_near_a_grade"] = closest
    return compact


def _compact_a_grade_readiness(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    compact = _compact_dict(
        payload,
        (
            "confidence_threshold",
            "after_cost_edge_bps_min_exclusive",
            "source_row_count",
            "source_kind_counts",
            "a_grade_before_temporal_count",
            "event_time_valid_candidate_count",
            "best_configuration_count",
            "readiness_blocker_reasons",
        ),
    )
    source_readiness = payload.get("source_kind_readiness")
    if isinstance(source_readiness, dict):
        compact["source_kind_readiness"] = {
            str(key): _compact_a_grade_source_readiness(value)
            for key, value in source_readiness.items()
            if isinstance(value, dict)
        }
    closest_by_source = payload.get("closest_near_a_grade_by_source_kind")
    if isinstance(closest_by_source, dict):
        compact["closest_near_a_grade_by_source_kind"] = {
            str(key): closest
            for key, value in closest_by_source.items()
            if (closest := _compact_near_a_grade(value))
        }
    return compact


def _compact_prediction_probe(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    compact = _compact_dict(
        payload,
        (
            "status",
            "prediction_row_count",
            "probe_participates_in_counterfactual_pass_gate",
            "source_coverage_required_for_pass",
            "a_grade_before_temporal_count",
            "event_time_valid_candidate_count",
            "best_configuration_count",
            "skipped_not_a_grade_count",
            "skipped_not_a_grade_reason_counts",
            "skipped_temporal_invalid_count",
            "skipped_no_feasible_configuration_count",
            "skipped_no_feasible_configuration_reason_counts",
            "sweep_result_count",
            "efficient_frontier_ready",
            "total_expected_log_growth",
            "notes",
        ),
    )
    readiness = _compact_a_grade_readiness(payload.get("a_grade_readiness"))
    if readiness:
        compact["a_grade_readiness"] = readiness
    return compact


def _compact_counterfactual_replay(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    compact = _compact_dict(
        payload,
        (
            "a_grade_replay_evidence_deficit",
            "a_grade_replay_progress_pct",
            "a_grade_source_kind_counts",
            "best_configuration_deficit_to_frontier",
            "closest_confidence_gap_to_a_grade",
            "closest_edge_gap_to_positive_bps",
            "configuration_count_reconciled",
            "configurations_considered_count",
            "theoretical_configuration_count",
            "feasible_configuration_count",
            "pruned_configuration_count",
            "historical_a_grade_signal_count",
            "a_grade_before_temporal_count",
            "event_time_valid_candidate_count",
            "best_configuration_count",
            "counterfactual_source_row_count",
            "not_a_grade_reason_counts",
            "source_coverage_status",
        ),
    )
    source_readiness = payload.get("a_grade_source_kind_readiness")
    if isinstance(source_readiness, dict):
        compact["a_grade_source_kind_readiness"] = {
            str(key): _compact_a_grade_source_readiness(value)
            for key, value in source_readiness.items()
            if isinstance(value, dict)
        }
    closest = _compact_near_a_grade(payload.get("closest_near_a_grade"))
    if closest:
        compact["closest_near_a_grade"] = closest
    closest_by_source = payload.get("closest_near_a_grade_by_source_kind")
    if isinstance(closest_by_source, dict):
        compact["closest_near_a_grade_by_source_kind"] = {
            str(key): row
            for key, value in closest_by_source.items()
            if (row := _compact_near_a_grade(value))
        }
    for key in ("prediction_a_grade_readiness",):
        readiness = _compact_a_grade_readiness(payload.get(key))
        if readiness:
            compact[key] = readiness
    for key in ("prediction_counterfactual_probe", "near_a_grade_counterfactual_probe"):
        probe = _compact_prediction_probe(payload.get(key))
        if probe:
            compact[key] = probe
    return compact


def _compact_field_selection_evidence(payload: Any) -> dict[str, Any] | None:
    compact = _compact_dict(
        payload,
        (
            "row_count",
            "required_selection_field_coverage",
            "gross_notional_unique_count",
            "allocated_margin_unique_count",
            "recommended_leverage_values",
            "effective_leverage_values",
            "recommended_margin_modes",
            "hedge_budget_unique_count",
            "positive_hedge_budget_count",
            "leverage_selection_model_input_count",
            "leverage_selection_model_input_coverage",
            "margin_mode_selection_model_input_count",
            "margin_mode_selection_model_input_coverage",
            "hedge_budget_selection_model_input_count",
            "hedge_budget_selection_model_input_coverage",
            "complete_selection_model_input_count",
            "complete_selection_model_input_coverage",
            "selection_model_input_missing_counts",
            "leverage_selection_reason_counts",
            "margin_mode_selection_reason_counts",
            "hedge_budget_selection_reason_counts",
        ),
    )
    return compact or None


def _compact_selection_attribution(payload: Any) -> dict[str, Any] | None:
    compact = _compact_dict(
        payload,
        (
            "status",
            "blocker_reasons",
            "row_count",
            "required_selection_field_coverage",
            "leverage_selection_model_input_coverage",
            "margin_mode_selection_model_input_coverage",
            "hedge_budget_selection_model_input_coverage",
            "complete_selection_model_input_count",
            "complete_selection_model_input_coverage",
            "selection_model_input_missing_counts",
            "required_runtime_selection_model_input_coverage",
            "selection_scope",
        ),
    )
    return compact or None


def _compact_accuracy(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return _compact_dict(
        payload,
        (
            "schema_version",
            "goal_id",
            "generated_utc",
            "status",
            "source",
            "accuracy_definition",
            "required_timeframes",
            "timeframes",
            "timeframe_count",
            "symbol_universe",
            "symbol_universe_count",
            "required_symbol_timeframe_cell_count",
            "symbol_timeframe_cell_count",
            "evaluated_symbol_timeframe_cell_count",
            "required_symbol_timeframe_cells_without_evaluated_outcomes_count",
            "missing_evaluated_symbol_timeframe_cell_count",
            "source_row_count",
            "prediction_rows_count",
            "evaluated_row_count",
            "unevaluated_row_count",
            "non_directional_row_count",
            "correct_count",
            "incorrect_count",
            "flat_count",
            "overall_accuracy",
            "evaluated_realized_pnl_usd",
            "latest_evaluated_event_time",
            "by_timeframe",
            "by_symbol",
            "by_symbol_timeframe",
        ),
    )


def _accuracy_source_row_count(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    for key in ("source_row_count", "prediction_rows_count", "prediction_count", "current_prediction_count"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    rows = payload.get("by_symbol_timeframe")
    return len(rows) if isinstance(rows, list) else 0


def _signal_runtime_prediction_accuracy_fallback() -> dict[str, Any] | None:
    signal_payload, _ = _read_json("operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json")
    if not isinstance(signal_payload, dict):
        signal_payload, _ = _read_json("operator_runtime/v2_signals/latest/signals_payload.json")
        if isinstance(signal_payload, dict):
            signal_payload = signal_payload.get("cuda_prediction_contract")
    if not isinstance(signal_payload, dict):
        return None
    rows = signal_payload.get("prediction_rows")
    if not isinstance(rows, list) or not rows:
        return None

    cells: dict[tuple[str, str], dict[str, Any]] = {}
    symbol_rows: dict[str, dict[str, Any]] = {}
    timeframe_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        timeframe = str(row.get("timeframe") or "")
        if not symbol or not timeframe:
            continue
        status = str(row.get("status") or signal_payload.get("status") or "PREDICTION_ROW_AVAILABLE_UNEVALUATED")
        cell = cells.setdefault(
            (symbol, timeframe),
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "signal_count": 0,
                "prediction_count": 0,
                "evaluated_count": 0,
                "correct_count": 0,
                "incorrect_count": 0,
                "flat_count": 0,
                "realized_pnl_usd": None,
                "accuracy": None,
                "status": status,
            },
        )
        cell["prediction_count"] += 1
        if cell["status"] == "PREDICTION_ROW_AVAILABLE_UNEVALUATED" and status:
            cell["status"] = status

    for cell in cells.values():
        symbol_row = symbol_rows.setdefault(
            cell["symbol"],
            {
                "symbol": cell["symbol"],
                "symbol_timeframe_cell_count": 0,
                "source_symbol_timeframe_cell_count": 0,
                "evaluated_symbol_timeframe_cell_count": 0,
                "signal_count": 0,
                "prediction_count": 0,
                "evaluated_count": 0,
                "correct_count": 0,
                "incorrect_count": 0,
                "flat_count": 0,
                "realized_pnl_usd": None,
                "accuracy": None,
                "status": "PREDICTION_ROWS_AVAILABLE_UNEVALUATED",
            },
        )
        timeframe_row = timeframe_rows.setdefault(
            cell["timeframe"],
            {
                "timeframe": cell["timeframe"],
                "symbol_timeframe_cell_count": 0,
                "source_symbol_timeframe_cell_count": 0,
                "evaluated_symbol_timeframe_cell_count": 0,
                "signal_count": 0,
                "prediction_count": 0,
                "evaluated_count": 0,
                "correct_count": 0,
                "incorrect_count": 0,
                "flat_count": 0,
                "realized_pnl_usd": None,
                "accuracy": None,
                "status": "PREDICTION_ROWS_AVAILABLE_UNEVALUATED",
            },
        )
        for aggregate in (symbol_row, timeframe_row):
            aggregate["symbol_timeframe_cell_count"] += 1
            aggregate["source_symbol_timeframe_cell_count"] += 1
            aggregate["prediction_count"] += int(cell.get("prediction_count") or 0)

    symbols = sorted(symbol_rows)
    timeframes = sorted(timeframe_rows, key=lambda tf: ("1m", "5m", "15m", "1h", "4h").index(tf) if tf in {"1m", "5m", "15m", "1h", "4h"} else 99)
    status = str(signal_payload.get("status") or "PREDICTION_ROWS_AVAILABLE_UNEVALUATED")
    return {
        "schema_version": "v2_signal_runtime_prediction_accuracy_fallback_v1",
        "generated_utc": _timestamp_from_payload(signal_payload),
        "status": status,
        "source": "operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json",
        "accuracy_definition": "Prediction rows are live telemetry only; evaluated accuracy requires closed outcomes.",
        "required_timeframes": timeframes,
        "timeframes": timeframes,
        "timeframe_count": len(timeframes),
        "symbol_universe": symbols,
        "symbol_universe_count": len(symbols),
        "required_symbol_timeframe_cell_count": len(cells),
        "symbol_timeframe_cell_count": len(cells),
        "evaluated_symbol_timeframe_cell_count": 0,
        "required_symbol_timeframe_cells_without_evaluated_outcomes_count": len(cells),
        "missing_evaluated_symbol_timeframe_cell_count": len(cells),
        "source_row_count": len(rows),
        "prediction_rows_count": len(rows),
        "evaluated_row_count": 0,
        "unevaluated_row_count": len(rows),
        "non_directional_row_count": len(rows),
        "correct_count": 0,
        "incorrect_count": 0,
        "flat_count": 0,
        "overall_accuracy": None,
        "evaluated_realized_pnl_usd": None,
        "latest_evaluated_event_time": None,
        "by_timeframe": [timeframe_rows[timeframe] for timeframe in timeframes],
        "by_symbol": [symbol_rows[symbol] for symbol in symbols],
        "by_symbol_timeframe": sorted(cells.values(), key=lambda cell: (cell["symbol"], cell["timeframe"])),
    }


def _compact_pnl_history(payload: Any) -> dict[str, Any] | None:
    return _compact_dict(
        payload,
        (
            "status",
            "source",
            "closed_trade_count",
            "timestamped_closed_trade_count",
            "untimestamped_or_future_closed_trade_count",
            "timestamp_coverage",
            "windows",
        ),
    ) or None


def _compact_capital_status(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    compact = _compact_dict(
        payload,
        (
            "schema_version",
            "goal_id",
            "generated_utc",
            "status",
            "capital_utilization_classification",
            "capital_productivity_blocker_reasons",
            "paper_equity_usd",
            "available_margin_usd",
            "allocated_margin_usd",
            "gross_open_notional_usd",
            "effective_portfolio_leverage",
            "capital_utilization_pct",
            "return_on_deployed_margin",
            "capital_turnover",
            "after_cost_expectancy_bps",
            "positive_edge_non_a_grade_opportunity_count",
        ),
    )
    progress = _compact_dict(
        payload.get("capital_productivity_progress"),
        (
            "current_closed_outcome_count",
            "minimum_required_closed_outcomes",
            "long_closed_outcome_count",
            "short_closed_outcome_count",
            "both_long_short_evidence",
            "current_symbol_count",
            "minimum_required_symbol_count",
            "symbol_diversity_deficit",
            "capital_utilization_classification",
            "allocated_margin_usd",
            "gross_open_notional_usd",
            "effective_portfolio_leverage",
            "capital_utilization_pct",
            "return_on_deployed_margin",
            "after_cost_expectancy_bps",
            "positive_edge_non_a_grade_opportunity_count",
            "near_a_grade_positive_edge_count",
            "closest_positive_edge_confidence_gap_to_a_grade",
        ),
    )
    if progress:
        compact["capital_productivity_progress"] = progress
    diagnostics = _compact_dict(
        payload.get("positive_edge_non_a_grade_diagnostics"),
        (
            "row_count",
            "confidence_threshold",
            "near_a_grade_confidence_threshold",
            "near_a_grade_positive_edge_count",
            "reason_counts",
            "side_counts",
            "timeframe_counts",
            "max_confidence",
            "max_after_cost_edge_bps",
            "min_confidence_gap_to_a_grade",
            "closest_positive_edge_to_a_grade",
            "top_after_cost_edge_not_a_grade",
        ),
    )
    if diagnostics:
        compact["positive_edge_non_a_grade_diagnostics"] = diagnostics
    pnl_history = _compact_pnl_history(payload.get("pnl_history"))
    if pnl_history:
        compact["pnl_history"] = pnl_history
    accuracy = _compact_accuracy(payload.get("signal_prediction_accuracy_status"))
    if accuracy:
        compact["signal_prediction_accuracy_status"] = accuracy
    return compact


def _compact_policy_status(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    compact = _compact_dict(
        payload,
        (
            "schema_version",
            "goal_id",
            "generated_utc",
            "status",
            "policy_evidence_blocker_reasons",
            "post_allocator_closed_outcome_count",
            "minimum_required_closed_outcomes",
            "long_closed_outcome_count",
            "short_closed_outcome_count",
            "both_long_short_evidence",
            "missing_directional_sides",
            "symbol_count",
            "minimum_required_symbol_count",
            "minimum_required_symbols",
            "symbol_diversity_deficit",
        ),
    )
    for key, compact_fn in (
        ("adaptive_field_selection_evidence", _compact_field_selection_evidence),
        ("adaptive_selection_attribution_status", _compact_selection_attribution),
        ("pre_submit_adaptive_field_selection_evidence", _compact_field_selection_evidence),
    ):
        value = compact_fn(payload.get(key))
        if value:
            compact[key] = value
    return compact


def _compact_counterfactual_status(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    compact = _compact_dict(payload, ("schema_version", "goal_id", "generated_utc", "status", "prediction_row_count"))
    readiness = _compact_a_grade_readiness(payload.get("a_grade_readiness"))
    if readiness:
        compact["a_grade_readiness"] = readiness
    replay = _compact_counterfactual_replay(payload.get("counterfactual_replay_progress"))
    if replay:
        compact["counterfactual_replay_progress"] = replay
    for key in ("prediction_counterfactual_probe", "near_a_grade_counterfactual_probe"):
        probe = _compact_prediction_probe(payload.get(key))
        if probe:
            compact[key] = probe
    return compact


def _compact_pass_conditions(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    compact = _compact_dict(payload, ("schema_version", "goal_id", "status", "condition_status_counts", "failed_conditions"))
    conditions = payload.get("conditions")
    if isinstance(conditions, list):
        compact["conditions"] = [
            _compact_dict(condition, ("id", "label", "status", "blocker_reasons"))
            for condition in conditions
            if isinstance(condition, dict)
        ]
    return compact


def _compact_operator_go_readiness(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    compact = _compact_dict(
        payload,
        (
            "schema_version",
            "goal_id",
            "generated_utc",
            "status",
            "overall_status",
            "remaining_blockers",
            "failed_conditions",
            "pass_condition_status_counts",
            "evidence_to_go",
        ),
    )
    progress = _compact_capital_status({"capital_productivity_progress": payload.get("capital_productivity_progress")})
    if progress and progress.get("capital_productivity_progress"):
        compact["capital_productivity_progress"] = progress["capital_productivity_progress"]
    replay = _compact_counterfactual_replay(payload.get("counterfactual_replay_progress"))
    if replay:
        compact["counterfactual_replay_progress"] = replay
    for key, compact_fn in (
        ("adaptive_field_selection_evidence", _compact_field_selection_evidence),
        ("adaptive_selection_attribution_status", _compact_selection_attribution),
        ("pre_submit_adaptive_field_selection_evidence", _compact_field_selection_evidence),
    ):
        value = compact_fn(payload.get(key))
        if value:
            compact[key] = value
    return compact


def _redis_pnl_windows() -> dict[str, Any] | None:
    """Build real PnL windows from v2:paper:closed_trades when static files show zeros."""
    r = get_redis()
    if r is None:
        return None
    try:
        raw = r.get("v2:paper:closed_trades")
        if not raw:
            return None
        trades = json.loads(raw)
        if not isinstance(trades, list) or not trades:
            return None
    except Exception:
        return None

    from datetime import UTC, datetime, timedelta  # noqa: PLC0415
    now = datetime.now(UTC)
    WINDOWS = [("1d", 86400), ("7d", 604800), ("30d", 2592000)]
    windows_out: list[dict[str, Any]] = []
    for wname, secs in WINDOWS:
        cutoff = now - timedelta(seconds=secs)
        bucket: list[dict[str, Any]] = []
        for t in trades:
            if t.get("realized_pnl_usd") is None:
                continue
            exit_time_raw = t.get("exit_price_utc") or t.get("close_time") or t.get("exit_time")
            if not exit_time_raw:
                continue
            try:
                ts = datetime.fromisoformat(str(exit_time_raw).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts > cutoff:
                    bucket.append(t)
            except Exception:
                continue
        pnl = sum(float(t.get("realized_pnl_usd") or 0) for t in bucket)
        wins = [t for t in bucket if t.get("winner") is True]
        losses = [t for t in bucket if t.get("winner") is False]
        win_rate = len(wins) / len(bucket) if bucket else None
        gross_profit = sum(float(t.get("realized_pnl_usd") or 0) for t in wins)
        gross_loss = abs(sum(float(t.get("realized_pnl_usd") or 0) for t in losses))
        profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else None
        windows_out.append({
            "window": wname,
            "realized_pnl_usd": round(pnl, 4),
            "closed_trade_count": len(bucket),
            "winning_trade_count": len(wins),
            "losing_trade_count": len(losses),
            "win_rate": round(win_rate, 4) if win_rate is not None else None,
            "profit_factor": profit_factor,
        })

    if not windows_out:
        return None
    total = len([t for t in trades if t.get("realized_pnl_usd") is not None])
    return {
        "status": "READY_REDIS_LIVE",
        "source": "v2:paper:closed_trades",
        "closed_trade_count": total,
        "windows": windows_out,
    }


def _redis_accuracy_status() -> dict[str, Any] | None:
    """Build signal prediction accuracy from v2:paper:closed_trades."""
    r = get_redis()
    if r is None:
        return None
    try:
        raw = r.get("v2:paper:closed_trades")
        if not raw:
            return None
        trades = json.loads(raw)
        if not isinstance(trades, list) or not trades:
            return None
    except Exception:
        return None

    evaluated = [t for t in trades if t.get("winner") is not None and t.get("confidence_calibrated") is not None]
    if not evaluated:
        return None
    wins = [t for t in evaluated if t.get("winner")]
    losses = [t for t in evaluated if not t.get("winner")]
    win_rate = len(wins) / len(evaluated)
    total_pnl = sum(float(t.get("realized_pnl_usd") or 0) for t in evaluated)
    gross_profit = sum(float(t.get("realized_pnl_usd") or 0) for t in wins if t.get("realized_pnl_usd"))
    gross_loss = abs(sum(float(t.get("realized_pnl_usd") or 0) for t in losses if t.get("realized_pnl_usd")))

    # Build by-timeframe breakdown from trades
    by_tf: dict[str, dict[str, Any]] = {}
    for t in evaluated:
        tf = t.get("timeframe") or "unknown"
        if tf not in by_tf:
            by_tf[tf] = {"evaluated_count": 0, "correct_count": 0, "incorrect_count": 0, "realized_pnl_usd": 0.0}
        by_tf[tf]["evaluated_count"] += 1
        if t.get("winner"):
            by_tf[tf]["correct_count"] += 1
        else:
            by_tf[tf]["incorrect_count"] += 1
        by_tf[tf]["realized_pnl_usd"] += float(t.get("realized_pnl_usd") or 0)
    for tf, row in by_tf.items():
        c = row["evaluated_count"]
        row["accuracy"] = round(row["correct_count"] / c, 4) if c > 0 else None
        row["timeframe"] = tf

    return {
        "status": "EVALUATED_REDIS_LIVE",
        "source": "v2:paper:closed_trades",
        "accuracy_definition": "winner_rate",
        "evaluated_row_count": len(evaluated),
        "correct_count": len(wins),
        "incorrect_count": len(losses),
        "overall_accuracy": round(win_rate, 4),
        "evaluated_realized_pnl_usd": round(total_pnl, 4),
        "by_timeframe": list(by_tf.values()),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else None,
    }


def _adaptive_capital_file_signature() -> tuple[tuple[str, int, int], ...]:
    root = _public_root()
    relatives = (
        f"{ADAPTIVE_CAPITAL_BASE_REL}/operator_dashboard_payload.json",
        f"{ADAPTIVE_CAPITAL_BASE_REL}/capital_productivity_runtime_status.json",
        f"{ADAPTIVE_CAPITAL_BASE_REL}/adaptive_capital_policy_status.json",
        f"{ADAPTIVE_CAPITAL_BASE_REL}/counterfactual_capital_sweep_status.json",
        "operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json",
        "operator_runtime/v2_signals/latest/signals_payload.json",
    )
    signature: list[tuple[str, int, int]] = []
    for relative in relatives:
        path = root / relative
        try:
            stat = path.stat()
        except OSError:
            signature.append((relative, 0, 0))
        else:
            signature.append((relative, stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def _adaptive_capital_compact_payload() -> tuple[dict[str, Any] | None, str, str | None]:
    signature = _adaptive_capital_file_signature()
    with ADAPTIVE_CAPITAL_COMPACT_CACHE_LOCK:
        if ADAPTIVE_CAPITAL_COMPACT_CACHE.get("signature") == signature:
            cached = ADAPTIVE_CAPITAL_COMPACT_CACHE.get("payload")
            if isinstance(cached, dict):
                return cached, f"{ADAPTIVE_CAPITAL_BASE_REL}/compact", ADAPTIVE_CAPITAL_COMPACT_CACHE.get("timestamp")

    dashboard, _ = _read_json(f"{ADAPTIVE_CAPITAL_BASE_REL}/operator_dashboard_payload.json")
    capital, _ = _read_json(f"{ADAPTIVE_CAPITAL_BASE_REL}/capital_productivity_runtime_status.json")
    policy, _ = _read_json(f"{ADAPTIVE_CAPITAL_BASE_REL}/adaptive_capital_policy_status.json")
    counterfactual, _ = _read_json(f"{ADAPTIVE_CAPITAL_BASE_REL}/counterfactual_capital_sweep_status.json")

    if not any(isinstance(payload, dict) for payload in (dashboard, capital, policy, counterfactual)):
        return None, f"{ADAPTIVE_CAPITAL_BASE_REL}/compact", None

    dashboard = dashboard if isinstance(dashboard, dict) else {}
    capital_source = dashboard.get("capital_productivity_runtime_status") if isinstance(dashboard.get("capital_productivity_runtime_status"), dict) else capital
    policy_source = dashboard.get("adaptive_capital_policy_status") if isinstance(dashboard.get("adaptive_capital_policy_status"), dict) else policy
    counterfactual_source = (
        dashboard.get("counterfactual_capital_sweep_status")
        if isinstance(dashboard.get("counterfactual_capital_sweep_status"), dict)
        else counterfactual
    )
    accuracy_source = (
        dashboard.get("signal_prediction_accuracy_status")
        or (capital_source or {}).get("signal_prediction_accuracy_status")
    )
    prediction_accuracy_fallback = _signal_runtime_prediction_accuracy_fallback()
    _used_prediction_fallback = False
    if _accuracy_source_row_count(accuracy_source) == 0 and _accuracy_source_row_count(prediction_accuracy_fallback) > 0:
        accuracy_source = prediction_accuracy_fallback
        _used_prediction_fallback = True
    # Redis fallback: use real evaluated outcome data when static file has 0 evaluated rows.
    # Skip if we already chose the signal prediction fallback (it has source_row_count but no evaluated rows yet).
    def _acc_evaluated_count(src: Any) -> int:
        if not isinstance(src, dict):
            return 0
        v = src.get("evaluated_row_count") or src.get("correct_count", 0) or 0
        return int(v) if isinstance(v, (int, float)) else 0
    if not _used_prediction_fallback and _acc_evaluated_count(accuracy_source) == 0:
        _redis_acc = _redis_accuracy_status()
        if _redis_acc and _redis_acc.get("evaluated_row_count", 0) > 0:
            accuracy_source = _redis_acc
            # Also inject into capital_source so capital_productivity_runtime_status uses live data
            if isinstance(capital_source, dict):
                capital_source = {**capital_source, "signal_prediction_accuracy_status": _redis_acc}
    using_prediction_accuracy_fallback = accuracy_source is prediction_accuracy_fallback
    pnl_source = dashboard.get("pnl_history_status") or (capital_source or {}).get("pnl_history")
    # Redis PnL fallback: use real trade data when static files show zero PnL
    _file_pnl_total = sum(
        float((w.get("realized_pnl_usd") or 0))
        for w in ((pnl_source or {}).get("windows") or [])
        if isinstance(w, dict)
    )
    if _file_pnl_total == 0.0:
        _redis_pnl = _redis_pnl_windows()
        if _redis_pnl and _redis_pnl.get("closed_trade_count", 0) > 0:
            pnl_source = _redis_pnl
            # Also inject Redis PnL into capital_source so _compact_capital_status
            # uses the live data for capital_productivity_runtime_status.pnl_history
            if isinstance(capital_source, dict):
                capital_source = {**capital_source, "pnl_history": _redis_pnl}

    compact: dict[str, Any] = {
        "generated_utc": dashboard.get("generated_utc")
        or (capital_source or {}).get("generated_utc")
        or (policy_source or {}).get("generated_utc")
        or (counterfactual_source or {}).get("generated_utc"),
        "overall_status": dashboard.get("overall_status")
        or (dashboard.get("operator_go_readiness") or {}).get("overall_status")
        or (capital_source or {}).get("status")
        or (policy_source or {}).get("status")
        or (counterfactual_source or {}).get("status"),
    }
    for key, value in (
        ("operator_go_readiness", _compact_operator_go_readiness(dashboard.get("operator_go_readiness"))),
        ("capital_productivity_runtime_status", _compact_capital_status(capital_source)),
        ("adaptive_capital_policy_status", _compact_policy_status(policy_source)),
        ("counterfactual_capital_sweep_status", _compact_counterfactual_status(counterfactual_source)),
        ("pass_condition_status", _compact_pass_conditions(dashboard.get("pass_condition_status"))),
        ("pnl_history_status", _compact_pnl_history(pnl_source)),
        ("signal_prediction_accuracy_status", _compact_accuracy(accuracy_source)),
        ("dashboard_web_status", _compact_dict(dashboard.get("dashboard_web_status"), (
            "status",
            "source",
            "blocker_reasons",
            "required_pnl_windows",
            "published_pnl_windows",
            "missing_pnl_windows",
            "all_required_pnl_windows_published",
            "required_accuracy_timeframes",
            "published_accuracy_timeframes",
            "missing_accuracy_timeframes",
            "symbol_universe_count",
            "required_symbol_timeframe_cell_count",
            "published_symbol_timeframe_cell_count",
            "published_symbol_timeframe_matrix_row_count",
            "evaluated_symbol_timeframe_cell_count",
            "missing_evaluated_symbol_timeframe_cell_count",
            "all_symbol_timeframe_accuracy_cells_published",
            "all_symbol_timeframe_accuracy_cells_evaluated",
            "web_surface_count",
            "surfaces",
        ))),
    ):
        if value:
            compact[key] = value
    if (
        using_prediction_accuracy_fallback
        and isinstance(compact.get("signal_prediction_accuracy_status"), dict)
        and isinstance(compact.get("capital_productivity_runtime_status"), dict)
    ):
        compact["capital_productivity_runtime_status"]["signal_prediction_accuracy_status"] = compact["signal_prediction_accuracy_status"]

    timestamp = compact.get("generated_utc") if isinstance(compact.get("generated_utc"), str) else None
    with ADAPTIVE_CAPITAL_COMPACT_CACHE_LOCK:
        ADAPTIVE_CAPITAL_COMPACT_CACHE["signature"] = signature
        ADAPTIVE_CAPITAL_COMPACT_CACHE["payload"] = compact
        ADAPTIVE_CAPITAL_COMPACT_CACHE["timestamp"] = timestamp
    return compact, f"{ADAPTIVE_CAPITAL_BASE_REL}/compact", timestamp


def _scope_token(value: Any) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None


def _actor_scope(actor: UserRecord | None) -> tuple[str | None, str | None]:
    if actor is None:
        return None, None
    return _scope_token(actor.get("trader_id")), _scope_token(actor.get("paper_account_id"))


def _payload_scope_values(payload: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None
    account = payload.get("paper_account")
    account_dict = account if isinstance(account, dict) else {}
    return (
        _scope_token(payload.get("trader_id") or account_dict.get("trader_id")),
        _scope_token(payload.get("paper_account_id") or account_dict.get("paper_account_id")),
    )


def _payload_matches_actor(payload: dict[str, Any] | None, actor: UserRecord | None) -> bool:
    actor_trader_id, actor_paper_account_id = _actor_scope(actor)
    if not actor_trader_id or not actor_paper_account_id:
        return False
    payload_trader_id, payload_paper_account_id = _payload_scope_values(payload)
    return payload_trader_id == actor_trader_id and payload_paper_account_id == actor_paper_account_id


def _row_matches_actor(row: Any, actor: UserRecord | None) -> bool:
    if not isinstance(row, dict):
        return False
    actor_trader_id, actor_paper_account_id = _actor_scope(actor)
    if not actor_trader_id or not actor_paper_account_id:
        return False
    row_trader_id = _scope_token(row.get("trader_id"))
    row_paper_account_id = _scope_token(row.get("paper_account_id"))
    return row_trader_id == actor_trader_id and row_paper_account_id == actor_paper_account_id


def _scoped_rows(rows: Any, actor: UserRecord | None) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return [row for row in rows if _row_matches_actor(row, actor)]


def _repository_scoped_rows(
    repository_account: TraderPaperAccount,
    actor: UserRecord | None,
    field: str,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    rows = repository_account.get(field, [])
    if not isinstance(rows, list):
        return [], [field], [f"{field.replace('_', ' ').title()} are not stored as a scoped list"]
    scoped = _scoped_rows(rows, actor)
    if rows and not scoped:
        return [], [f"{field}_scope"], [f"Stored {field.replace('_', ' ')} were withheld because row scope did not match the authenticated trader"]
    if len(scoped) != len(rows):
        return scoped, [f"{field}_scope"], [f"Some stored {field.replace('_', ' ')} were withheld because row scope did not match the authenticated trader"]
    return scoped, [], []


def _runtime_portfolio_state() -> tuple[dict[str, Any], str, SourceType, list[str]]:
    warnings: list[str] = []
    try:
        client = get_redis()
        raw = client.get("v2:portfolio:state") if client is not None else None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        payload = json.loads(raw) if raw else None
        if isinstance(payload, dict):
            return payload, "redis:v2:portfolio:state", "redis_live", warnings
    except Exception as exc:
        warnings.append(f"Redis portfolio state unavailable: {exc}")

    payload, _source = _portfolio_payload()
    if isinstance(payload, dict):
        return (
            payload,
            "operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json",
            "static_payload",
            warnings,
        )
    return {}, "", "unavailable", warnings


def _payload_has_scope(payload: dict[str, Any] | None) -> bool:
    trader_id, paper_account_id = _payload_scope_values(payload)
    return bool(trader_id or paper_account_id)


def _row_has_scope(row: dict[str, Any]) -> bool:
    return bool(_scope_token(row.get("trader_id")) or _scope_token(row.get("paper_account_id")))


def _runtime_payload_available_to_actor(payload: dict[str, Any], actor: UserRecord | None) -> bool:
    if actor is None:
        return True
    return not _payload_has_scope(payload) or _payload_matches_actor(payload, actor)


def _runtime_row_available_to_actor(
    row: dict[str, Any],
    *,
    payload_has_scope: bool,
    payload_matches_actor: bool,
    actor: UserRecord | None,
) -> bool:
    if actor is None:
        return True
    if _row_has_scope(row):
        return _row_matches_actor(row, actor)
    if payload_has_scope:
        return False
    return payload_matches_actor or not payload_has_scope


def _with_actor_scope(row: dict[str, Any], actor: UserRecord | None) -> dict[str, Any]:
    if actor is None:
        return dict(row)
    scoped = dict(row)
    scoped["trader_id"] = actor.get("trader_id")
    scoped["paper_account_id"] = actor.get("paper_account_id")
    return scoped


def _runtime_portfolio_positions(
    portfolio_state: dict[str, Any],
    actor: UserRecord | None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    raw_rows = portfolio_state.get("open_positions")
    if not isinstance(raw_rows, list):
        raw_rows = portfolio_state.get("positions") if isinstance(portfolio_state.get("positions"), list) else []
    payload_has_scope = _payload_has_scope(portfolio_state)
    payload_matches_actor = _payload_matches_actor(portfolio_state, actor) if actor is not None else True
    rows: list[dict[str, Any]] = []
    withheld = 0
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        if not _runtime_row_available_to_actor(
            raw,
            payload_has_scope=payload_has_scope,
            payload_matches_actor=payload_matches_actor,
            actor=actor,
        ):
            withheld += 1
            continue
        row = _with_actor_scope(raw, actor)
        row["position_id"] = (
            row.get("position_id")
            or row.get("id")
            or (row.get("source_fill_ids") or [None])[0]
            or f"paper-runtime-{row.get('symbol') or len(rows)}"
        )
        if row.get("quantity") is None:
            row["quantity"] = row.get("net_quantity")
        if row.get("net_quantity") is None:
            row["net_quantity"] = row.get("quantity")
        row["entry_price"] = row.get("entry_price") or row.get("avg_entry_price") or row.get("fill_price")
        row["last_mark_price"] = row.get("last_mark_price") or row.get("mark_price") or row.get("latest_price")
        row["current_price"] = row.get("current_price") or row.get("mark_price") or row.get("latest_price")
        row["mark_price_source"] = row.get("mark_price_source") or row.get("latest_price_source")
        row["unrealized_pnl"] = row.get("unrealized_pnl") if row.get("unrealized_pnl") is not None else row.get("unrealized_pnl_usd")
        row["realized_pnl"] = row.get("realized_pnl") if row.get("realized_pnl") is not None else row.get("realized_pnl_usd")
        rows.append(row)
    missing = [] if rows or not raw_rows else ["positions"]
    warnings = []
    if rows:
        warnings.append("Projected paper runtime portfolio positions into authenticated paper account view")
    if withheld:
        missing.append("positions_scope")
        warnings.append("Some paper runtime positions were withheld because row scope did not match the authenticated trader")
    return rows, missing, warnings


def _runtime_signal_rows() -> tuple[list[dict[str, Any]], str, str | None]:
    for relative in (
        "operator_runtime/v2_signals/latest/signals_payload.json",
        "operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json",
    ):
        payload, _source = _read_json(relative)
        if not isinstance(payload, dict):
            continue
        containers = [
            payload,
            payload.get("cuda_prediction_contract") if isinstance(payload.get("cuda_prediction_contract"), dict) else {},
            payload.get("prediction_contract") if isinstance(payload.get("prediction_contract"), dict) else {},
            payload.get("signal_publisher") if isinstance(payload.get("signal_publisher"), dict) else {},
        ]
        for container in containers:
            if not isinstance(container, dict):
                continue
            for key in ("prediction_rows", "published_signals", "signals", "active_signals"):
                rows = container.get(key)
                if isinstance(rows, list) and rows:
                    return [row for row in rows if isinstance(row, dict)], relative, _timestamp_from_payload(payload)
    return [], "", None


def _runtime_signal_response(
    *,
    symbol: str,
    timeframe: str,
    endpoint: str,
    actor: UserRecord | None,
    strict_symbol: bool = False,
) -> dict[str, Any] | None:
    rows, source, timestamp = _runtime_signal_rows()
    if not rows:
        return None
    symbol_upper = symbol.upper()
    exact = [
        row for row in rows
        if str(row.get("symbol") or "").upper() == symbol_upper
        and str(row.get("timeframe") or "").lower() == timeframe.lower()
    ]
    symbol_rows = [row for row in rows if str(row.get("symbol") or "").upper() == symbol_upper]
    if strict_symbol and not exact and not symbol_rows:
        return None
    candidates = exact or symbol_rows or rows
    candidates.sort(
        key=lambda row: str(row.get("available_at") or row.get("decision_time") or row.get("generated_utc") or row.get("generated_at") or ""),
        reverse=True,
    )
    row = candidates[0]
    action = _prediction_action(row)
    generated_at = (
        row.get("available_at")
        or row.get("decision_time")
        or row.get("generated_utc")
        or row.get("generated_at")
        or row.get("generated_est")
    )
    generated_at = generated_at if isinstance(generated_at, str) else timestamp
    confidence = _float(row.get("confidence_calibrated") or row.get("confidence") or row.get("confidence_raw"))
    target_after_cost = _float(row.get("price_target_after_cost"))
    target = target_after_cost if target_after_cost is not None else _float(row.get("price_target"))
    active_signal = {
        "id": row.get("signal_id") or row.get("prediction_id"),
        "signal_id": row.get("signal_id"),
        "prediction_id": row.get("prediction_id"),
        "symbol": str(row.get("symbol") or symbol_upper).upper(),
        "timeframe": row.get("timeframe") or timeframe,
        "direction": action.upper() if action else None,
        "side": action.title() if action else None,
        "entry": _float(row.get("entry") or row.get("entry_price") or row.get("last_price")),
        "target_1": target,
        "price_target": _float(row.get("price_target")),
        "price_target_after_cost": target_after_cost,
        "stop": _float(row.get("stop") or row.get("stop_reference")),
        "confidence": confidence,
        "confidence_calibrated": confidence,
        "expected_move": _float(row.get("expected_move_bps")),
        "expected_move_after_cost_bps": _float(row.get("expected_move_after_cost_bps")),
        "risk_reward": None,
        "status": row.get("paper_fill_gate_status") or row.get("status"),
        "strategy": "All-timeframe paper signal",
        "model_version": row.get("model_version") or row.get("checkpoint_id"),
        "risk_decision": row.get("paper_fill_gate_status") or row.get("market_cost_evidence_status"),
        "created_at": generated_at,
        "evidence": [
            item for item in (
                row.get("feature_snapshot_id"),
                row.get("market_state_id"),
                row.get("prediction_redis_key"),
            )
            if item
        ],
        "paper_fill_allowed": row.get("paper_fill_allowed"),
        "exchange_action_taken": False,
        "exchange_call_invariant": "LIVE_TRADING_BLOCKED",
    }
    missing_fields = [
        field
        for field in ("symbol", "timeframe", "direction", "confidence")
        if active_signal.get(field) is None
    ]
    if target is None:
        missing_fields.append("target_1")
    return _base_response(
        endpoint=endpoint,
        data={
            "active_signal": active_signal,
            "trader_id": actor.get("trader_id") if actor else None,
            "paper_account_id": actor.get("paper_account_id") if actor else None,
            "account_scope": "authenticated_trader" if actor else "public_read_only",
            "account_specific": bool(actor),
            "paper_runtime_projection": True,
        },
        source=source,
        source_type="static_payload",
        symbol=str(active_signal.get("symbol") or symbol_upper),
        timestamp=generated_at,
        missing_fields=missing_fields,
        warnings=[
            "Paper-runtime signal projection; no exchange state was read or mutated",
            "Live trading remains disabled",
        ],
        mode="paper",
        trader_context=_trader_context(actor),
    )


def _redis_risk_max_leverage(client: Any) -> float:
    try:
        raw = client.get("v2:risk:active_profile")
        payload = json.loads(raw) if raw else {}
        fields = payload.get("fields") if isinstance(payload, dict) else {}
        return float((fields or {}).get("max_leverage") or 1.0)
    except Exception:
        return 1.0


def _enrich_position_rows_for_read_response(
    positions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[str], list[str], str]:
    if not positions:
        return positions, None, [], [], ""
    client: Any | None = None
    redis_warning: str | None = None
    try:
        client = get_redis()
    except Exception as exc:
        redis_warning = f"Realtime mark-price Redis unavailable: {exc}; using stored paper marks only"
    if client is None and redis_warning is None:
        redis_warning = "Realtime mark-price Redis is not configured; using stored paper marks only"

    enriched, metrics = _enrich_paper_positions(
        client,
        positions,
        max_leverage=_redis_risk_max_leverage(client),
    )
    missing: list[str] = []
    warnings: list[str] = ["Trader-scoped positions enriched with read-only realtime mark-price projection"]
    if redis_warning:
        warnings.append(redis_warning)
    if metrics.get("missing_mark_price_count"):
        missing.append("mark_price_realtime")
        warnings.append("One or more positions are missing realtime mark price; UI must show unavailable state")
    if metrics.get("stale_mark_price_count"):
        warnings.append("One or more position mark prices are stale and must show stale age")
    return enriched, metrics, missing, warnings, " + read-only realtime mark projection"


def _account_scope_warning(actor: UserRecord | None) -> str:
    return (
        "Trader-specific paper repository is pending; unscoped fallback account data is withheld"
        if actor
        else "Sign in to view trader-specific paper account data"
    )


def _paper_account(actor: UserRecord | None = None) -> dict[str, Any] | None:
    paper, _ = _paper_payload()
    account = paper.get("paper_account") if isinstance(paper, dict) else None
    if not isinstance(account, dict):
        return None
    if actor is None:
        return None
    return account if _payload_matches_actor(paper, actor) else None


def _repository_account(actor: UserRecord | None) -> TraderPaperAccount | None:
    if actor is None:
        return None
    trader_id, paper_account_id = _actor_scope(actor)
    return get_trader_account_repository().get_account(
        trader_id=trader_id,
        paper_account_id=paper_account_id,
    )


def _safe_trader_account_readiness_data(
    *,
    actor: UserRecord | None,
    repository_account: TraderPaperAccount | None,
    readiness: dict[str, Any] | None,
) -> dict[str, Any]:
    readiness_data = readiness if isinstance(readiness, dict) else {}
    return {
        "trader_id": actor.get("trader_id") if actor else None,
        "paper_account_id": actor.get("paper_account_id") if actor else None,
        "account_scope": "authenticated_trader" if actor else "public_read_only",
        "account_specific": bool(actor and repository_account is not None),
        "account_present": repository_account is not None,
        "repository_status": readiness_data.get("status") or "unavailable",
        "repository_kind": readiness_data.get("repository_kind") or "unavailable",
        "tenant_isolation_status": readiness_data.get("tenant_isolation_status") or "unavailable",
        "unique_paper_account_scope": readiness_data.get("unique_paper_account_scope") is True,
        "paper_account_uniqueness_enforced": readiness_data.get("paper_account_uniqueness_enforced") is True,
        "trader_scope_required": readiness_data.get("trader_scope_required") is True,
        "production_repository": readiness_data.get("production_repository") is True,
        "durable_database_repository": readiness_data.get("durable_database_repository") is True,
        "production_writer_validation": readiness_data.get("production_writer_validation") or "pending",
        "migration_status": readiness_data.get("migration_status") or "pending",
        "backup_restore_status": readiness_data.get("backup_restore_status") or "missing",
        "retention_policy_status": readiness_data.get("retention_policy_status") or "missing",
        "trader_account_scope_smoke_status": readiness_data.get("trader_account_scope_smoke_status") or "missing",
        "trader_account_scope_smoke_artifact_valid": readiness_data.get("trader_account_scope_smoke_artifact_valid") is True,
        "production_trader_repository_smoke_status": readiness_data.get("production_trader_repository_smoke_status") or "missing",
        "production_trader_repository_smoke_artifact_valid": readiness_data.get("production_trader_repository_smoke_artifact_valid") is True,
        "supported_local_domains": readiness_data.get("supported_local_domains") if isinstance(readiness_data.get("supported_local_domains"), list) else [],
        "contains_credentials": False,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
    }


def _active_signal() -> dict[str, Any] | None:
    paper, _ = _paper_payload()
    lineage = paper.get("current_signal_lineage") if isinstance(paper, dict) else None
    if isinstance(lineage, dict):
        signal = lineage.get("signal")
        if isinstance(signal, dict):
            return signal
    return None


def _signal_symbol(signal: dict[str, Any] | None) -> str | None:
    if not isinstance(signal, dict):
        return None
    value = signal.get("symbol") or signal.get("market_symbol")
    return _safe_symbol(str(value)) if value else None


def _signal_matches_requested_symbol(signal: dict[str, Any] | None, requested_symbol: str | None) -> bool:
    if requested_symbol is None:
        return True
    return _signal_symbol(signal) == requested_symbol


def _friendly_signal_status(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("PAPER_FILL_GATE_BLOCKED:", "Paper fill blocked:")
    return text.replace("_", " ").title()


def _redis_paper_signal_response(
    *,
    symbol: str,
    timeframe: str,
    endpoint: str,
    actor: UserRecord | None,
) -> dict[str, Any] | None:
    key = f"v2:signals:paper:{symbol}:{timeframe}"
    payload = _read_v2_redis_json(key)
    if not isinstance(payload, dict):
        return None
    payload_symbol = _signal_symbol(payload)
    if payload_symbol != symbol:
        return None
    action = str(payload.get("action") or "").strip().upper()
    confidence = _float(payload.get("confidence"))
    target_after_cost = _float(payload.get("price_target_after_cost"))
    target = target_after_cost if target_after_cost is not None else _float(payload.get("price_target"))
    generated_at = _timestamp_from_redis_payload(payload)
    lag = _lag_ms(generated_at)
    is_actionable = payload.get("paper_fill_allowed") is True
    lineage_ids = payload.get("lineage_ids") or {}
    active_signal = {
        "symbol": symbol,
        "timeframe": timeframe,
        # Canonical frontend field names
        "action": action.lower() if action else None,
        "side": action.title() if action else None,
        "proposed_action": action or None,
        "actionable": is_actionable,
        "actionable_reason_code": payload.get("paper_fill_status") or payload.get("paper_fill_gate_status"),
        "live_gate": payload.get("live_gate"),
        "generated_at": generated_at,
        "signal_id": payload.get("signal_id"),
        "prediction_id": payload.get("prediction_id"),
        "feature_snapshot_id": payload.get("market_state_id"),
        "source_freshness": "STALE" if lag is not None and lag > 3_600_000 else ("CURRENT" if lag is not None else "UNKNOWN"),
        "market_age_seconds": round(lag / 1000) if lag is not None else None,
        "exchange_action_taken": False,
        "exchange_call_invariant": "LIVE_TRADING_BLOCKED",
        "confidence_floor": None,
        "service_id": None,
        "explanation": (
            _friendly_signal_status(payload.get("orchestrator_state"))
            or _friendly_signal_status(payload.get("paper_fill_status"))
            or ("Paper fill gate open — no ledger yet" if is_actionable else "Signal blocked by risk gate")
        ),
        # Legacy / backward-compat names also kept
        "selected_action": action or None,
        "direction": action.title() if action else None,
        "confidence_calibrated": confidence,
        "confidence": confidence,
        "strategy": "All-timeframe paper signal",
        "model_version": payload.get("prediction_id"),
        "price_target": _float(payload.get("price_target")),
        "price_target_after_cost": target_after_cost,
        "target_1": target,
        "target_label": "Target after estimated cost" if target_after_cost is not None else "Model target",
        "expected_move_after_cost_bps": _float(payload.get("expected_move_after_cost_bps")),
        "data_coverage_percent": _float(payload.get("data_coverage_percent")),
        "market_state_integrity_score": _float(payload.get("market_state_integrity_score")),
        "paper_fill_allowed": is_actionable,
        "risk_result": (
            _friendly_signal_status(payload.get("blocked_reason"))
            or ("Paper Fill Open" if is_actionable else _friendly_signal_status(payload.get("paper_fill_status") or payload.get("risk_status_label")))
            or "Risk result unavailable"
        ),
        "blocked_reason": _friendly_signal_status(payload.get("blocked_reason")),
        "lineage_summary": {
            "signal_id": payload.get("signal_id"),
            "prediction_id": payload.get("prediction_id"),
            "trainer_prediction_id": lineage_ids.get("trainer_prediction_id"),
            "market_state_id": payload.get("market_state_id"),
            "orchestrator_decision": _friendly_signal_status(payload.get("orchestrator_state")),
            "risk_state": _friendly_signal_status(payload.get("risk_state")),
            "paper_state": _friendly_signal_status(payload.get("paper_state")),
        },
    }
    # Only flag truly required fields; optional levels (entry, target_2/3, stop, invalidation)
    # are not required for a valid paper signal and should not trigger the "incomplete" banner.
    missing_fields = [
        field
        for field in ("target_1",)
        if active_signal.get(field) is None
    ]
    # Use current time as envelope timestamp so stale=False — the signal IS the latest
    # the system has. Signal age is captured in active_signal.market_age_seconds.
    return _base_response(
        endpoint=endpoint,
        data={
            "active_signal": active_signal,
            "trader_id": actor.get("trader_id") if actor else None,
            "paper_account_id": actor.get("paper_account_id") if actor else None,
            "account_scope": "authenticated_trader" if actor else "public_read_only",
            "account_specific": False,
            "public_paper_signal": True,
        },
        source=f"Redis paper signal publisher {key}",
        source_type="repository",
        symbol=symbol,
        timestamp=_utc_now(),
        missing_fields=missing_fields,
        warnings=[
            "V2 Redis paper signal loaded before marking active signal unavailable",
            "Signal is public paper evidence and is not trader-account-specific",
            f"Signal generated {round(lag / 60000) if lag else '?'}m ago — latest available",
            "Live trading and exchange mutation remain disabled",
        ],
        mode="paper",
        trader_context=_trader_context(actor),
    )


def _symbol_from_payload(symbol: str | None, terminal: dict[str, Any] | None) -> str:
    if symbol:
        return symbol.upper()
    if terminal and isinstance(terminal.get("symbol"), str) and terminal["symbol"]:
        return terminal["symbol"].upper()
    return "BTCUSDT"


@router.get("/market/overview")
async def get_market_overview() -> dict[str, Any]:
    endpoint = "/api/v2/market/overview"
    tickers, api_source, api_warning = await _binance_public_json_async("/fapi/v1/ticker/24hr", {})
    if isinstance(tickers, list):
        ticker_rows = sorted(
            [
                {
                    "symbol": safe_symbol,
                    "last_price": _float(row.get("lastPrice")),
                    "change_24h": (_float(row.get("priceChangePercent")) / 100) if _float(row.get("priceChangePercent")) is not None else None,
                    "high_24h": _float(row.get("highPrice")),
                    "low_24h": _float(row.get("lowPrice")),
                    "volume_24h": _float(row.get("volume")),
                    "turnover_24h": _float(row.get("quoteVolume")),
                    "trade_count_24h": int(_float(row.get("count")) or 0),
                    "weighted_avg_price": _float(row.get("weightedAvgPrice")),
                }
                for row in tickers
                if isinstance(row, dict)
                for safe_symbol in [_strict_market_symbol(str(row.get("symbol") or ""))]
                if safe_symbol and safe_symbol.endswith("USDT")
            ],
            key=lambda item: item["symbol"],
        )
        symbols = [row["symbol"] for row in ticker_rows]
        ticker_missing = [
            "tickers"
            for row in ticker_rows
            if row.get("last_price") is None
        ]
        return _base_response(
            endpoint=endpoint,
            data={
                "symbols": symbols,
                "count": len(symbols),
                "timeframes": ["1m", "3m", "5m", "15m", "1h", "4h", "1d", "1w"],
                "tickers": ticker_rows,
            },
            source=api_source,
            source_type="api",
            timestamp=_utc_now(),
            missing_fields=[] if symbols and not ticker_missing else [*([] if symbols else ["symbols"]), *ticker_missing[:1]],
            warnings=[
                "Binance public USD-M 24h ticker inventory and public 24h ticker rows; read-only source",
                "Realtime symbol stream is still pending; this endpoint refreshes per request",
                *([api_warning] if api_warning else []),
            ],
            mode="read_only",
        )
    manifest, source = _manifest_payload()
    if not manifest:
        return _unavailable(
            endpoint=endpoint,
            missing_fields=["symbols", "markets"],
            warning="Market overview source is not wired yet",
        )
    symbols = sorted(
        {
            safe_symbol
            for symbol in manifest.get("symbols", [])
            if isinstance(symbol, str)
            for safe_symbol in [_strict_market_symbol(symbol)]
            if safe_symbol
        }
    )
    data = {
        "symbols": symbols,
        "count": len(symbols),
        "timeframes": manifest.get("timeframes") or [manifest.get("timeframe")],
        "tickers": [],
    }
    return _base_response(
        endpoint=endpoint,
        data=data,
        source=source,
        source_type="static_payload",
        timestamp=_timestamp_from_payload(manifest),
        missing_fields=[] if symbols else ["symbols"],
        warnings=["Static payload fallback; ticker prices unavailable; not a live stream"],
        mode="read_only",
    )


@router.get("/realtime/manifest")
async def get_realtime_manifest() -> dict[str, Any]:
    """Returns the list of known realtime data sources and their wiring status."""
    endpoint = "/api/v2/realtime/manifest"
    sources = [
        {"id": "binance_ticker_24hr", "type": "api", "endpoint": "/fapi/v1/ticker/24hr", "status": "wired", "description": "Binance USD-M 24h ticker for all symbols"},
        {"id": "binance_klines", "type": "api", "endpoint": "/fapi/v1/klines", "status": "wired", "description": "Binance candle/OHLCV data per symbol"},
        {"id": "binance_depth", "type": "api", "endpoint": "/fapi/v1/depth", "status": "wired", "description": "Binance order book depth per symbol"},
        {"id": "binance_trades", "type": "api", "endpoint": "/fapi/v1/trades", "status": "wired", "description": "Binance recent trades per symbol"},
        {"id": "binance_funding_rate", "type": "api", "endpoint": "/fapi/v1/fundingRate", "status": "wired", "description": "Binance funding rate history per symbol"},
        {"id": "binance_premium_index", "type": "api", "endpoint": "/fapi/v1/premiumIndex", "status": "wired", "description": "Binance mark/index price + funding per symbol"},
        {"id": "binance_open_interest", "type": "api", "endpoint": "/fapi/v1/openInterest", "status": "wired", "description": "Binance open interest per symbol"},
        {"id": "binance_long_short", "type": "api", "endpoint": "/futures/data/globalLongShortAccountRatio", "status": "wired", "description": "Long/short ratio per symbol"},
        {"id": "binance_liquidations", "type": "api", "endpoint": "/fapi/v1/allForceOrders", "status": "wired", "description": "Recent forced liquidation orders"},
        {"id": "v2_signals_repository", "type": "repository", "endpoint": "/api/v2/signals", "status": "wired", "description": "V2 signal store"},
        {"id": "v2_portfolio_repository", "type": "repository", "endpoint": "/api/v2/portfolio", "status": "wired", "description": "V2 paper portfolio"},
        {"id": "v2_alerts_repository", "type": "repository", "endpoint": "/api/v2/alerts", "status": "wired", "description": "V2 paper alert store"},
        {"id": "v2_trainer_status", "type": "repository", "endpoint": "/api/v2/trainer/summary", "status": "wired", "description": "Trainer runtime status"},
        {"id": "redis_live_data", "type": "cache", "endpoint": "redis://localhost:6379", "status": "partial", "description": "Redis realtime cache for market data"},
        {"id": "websocket_market_data", "type": "websocket", "endpoint": "/api/v2/ws/market-data", "status": "wired", "description": "WebSocket market stream per symbol"},
        {"id": "backtests", "type": "repository", "endpoint": "/api/v2/backtests", "status": "pending", "description": "Backtest results — engine not yet connected"},
        {"id": "ai_predictions_stream", "type": "repository", "endpoint": "/api/v2/ai/predictions", "status": "partial", "description": "AI model predictions from trainer"},
    ]
    return _base_response(
        endpoint=endpoint,
        data={"sources": sources, "count": len(sources)},
        source="v2_source_manifest",
        source_type="api",
        timestamp=_utc_now(),
        missing_fields=[],
        warnings=[],
        mode="read_only",
    )


@router.get("/data-health")
async def get_data_health() -> dict[str, Any]:
    """Public-safe data health summary. Shows freshness and availability of each major data surface."""
    endpoint = "/api/v2/data-health"
    market_ok = False
    signal_ok = False
    try:
        overview = await get_market_overview()
        market_ok = overview.get("source_type") in ("api", "repository") and not overview.get("stale", True)
    except Exception:
        pass
    try:
        sig = _active_signal()
        signal_ok = sig is not None
    except Exception:
        pass
    surfaces = [
        {"name": "Market data", "endpoint": "/api/v2/market/overview", "status": "ok" if market_ok else "degraded", "description": "Live ticker + candle data from exchange"},
        {"name": "Signal feed", "endpoint": "/api/v2/signals", "status": "ok" if signal_ok else "degraded", "description": "AI signal stream"},
        {"name": "Portfolio", "endpoint": "/api/v2/portfolio", "status": "partial", "description": "Paper portfolio repository"},
        {"name": "Alerts", "endpoint": "/api/v2/alerts", "status": "partial", "description": "Paper alert store"},
        {"name": "Trainer", "endpoint": "/api/v2/trainer/summary", "status": "partial", "description": "ML trainer runtime"},
        {"name": "Backtests", "endpoint": "/api/v2/backtests", "status": "pending", "description": "Backtest engine not connected"},
        {"name": "WebSocket", "endpoint": "/api/v2/ws/market-data", "status": "partial", "description": "Realtime WebSocket stream"},
    ]
    overall = "ok" if market_ok else ("degraded" if any(s["status"] == "ok" for s in surfaces) else "offline")
    return _base_response(
        endpoint=endpoint,
        data={"overall": overall, "surfaces": surfaces, "count": len(surfaces)},
        source="v2_health_check",
        source_type="api",
        timestamp=_utc_now(),
        missing_fields=[],
        warnings=[],
        mode="read_only",
    )


@router.get("/adaptive-capital/dashboard")
async def get_adaptive_capital_dashboard() -> dict[str, Any]:
    payload, source, timestamp = _adaptive_capital_compact_payload()
    if not payload:
        return _unavailable(
            endpoint="/api/v2/adaptive-capital/dashboard",
            missing_fields=["adaptive_capital_dashboard"],
            warning="Adaptive capital productivity runtime payload is unavailable",
            mode="read_only",
        )
    missing_fields = [
        field
        for field in (
            "capital_productivity_runtime_status",
            "adaptive_capital_policy_status",
            "counterfactual_capital_sweep_status",
            "signal_prediction_accuracy_status",
        )
        if field not in payload
    ]
    response = _base_response(
        endpoint="/api/v2/adaptive-capital/dashboard",
        data=payload,
        source=source,
        source_type="static_payload",
        timestamp=timestamp,
        missing_fields=missing_fields,
        warnings=[
            "Read-only compact telemetry projection from operator runtime payloads",
            "Exchange execution remains operator-gated",
        ],
        exchange=None,
        mode="read_only",
    )
    if isinstance(response.get("lag_ms"), int) and response["lag_ms"] <= 900_000:
        response["stale"] = False
    return response


@router.get("/backtests")
async def get_backtests(
    symbol: str | None = Query(default=None),
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Returns backtest results. Engine is not yet connected — returns explicit not-ready state."""
    endpoint = "/api/v2/backtests"
    return _base_response(
        endpoint=endpoint,
        data={
            "backtests": [],
            "count": 0,
            "engine_status": "not_connected",
            "engine_message": "Backtest engine is not connected to a durable compute service yet. No simulated or fabricated results are returned.",
            "supported_when_ready": ["equity_curve", "drawdown", "win_rate", "profit_factor", "expectancy", "trade_by_trade", "benchmark", "signal_overlays"],
        },
        source="backtest_service",
        source_type="unavailable",
        timestamp=_utc_now(),
        missing_fields=["backtests", "equity_curve", "drawdown", "win_rate"],
        warnings=["Backtest engine not connected — no fabricated results returned"],
        mode="read_only",
    )


@router.get("/ai/predictions")
async def get_ai_predictions(
    symbol: str | None = Query(default=None),
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Returns the latest AI/model predictions from the trainer service."""
    from app.api.v2.trainer import get_trainer_summary  # noqa: PLC0415
    endpoint = "/api/v2/ai/predictions"
    try:
        trainer_data = await get_trainer_summary()
        # Trainer returns a flat shape (no "data" wrapper), fall back to it directly
        trainer_state = trainer_data.get("data") or trainer_data or {}
        prediction = trainer_state.get("prediction") or trainer_state.get("latest_prediction")
        action = None
        confidence = None
        model_version = None
        checkpoint_id = trainer_state.get("checkpoint_id")
        if isinstance(prediction, dict):
            action = prediction.get("action") or prediction.get("direction") or prediction.get("selected_action")
            confidence = prediction.get("confidence")
            model_version = prediction.get("model_version")
        # Fall back to reading latest prediction from Redis when trainer is in stub mode
        if not action and not confidence:
            safe_sym = _strict_market_symbol(symbol or "BTCUSDT") or "BTCUSDT"
            _pred_raw = _read_v2_redis_json(f"v2:prediction:{safe_sym}:1h")
            if isinstance(_pred_raw, dict):
                action = _pred_raw.get("action") or _pred_raw.get("selected_action")
                confidence = _pred_raw.get("confidence") or _pred_raw.get("confidence_calibrated")
                model_version = _pred_raw.get("model_version")
                checkpoint_id = checkpoint_id or _pred_raw.get("checkpoint_id")
        predictions = []
        if action or confidence:
            predictions = [{
                "action": action,
                "confidence": confidence,
                "model_version": model_version or trainer_state.get("model_version"),
                "checkpoint_id": checkpoint_id,
                "strategy": trainer_state.get("strategy"),
                "horizon": trainer_state.get("horizon") or "1h",
                "symbol": symbol or "BTCUSDT",
                "timestamp": _utc_now(),
                "source": "trainer_redis_evidence",
            }]
        return _base_response(
            endpoint=endpoint,
            data={
                "predictions": predictions,
                "count": len(predictions),
                "trainer_status": trainer_state.get("state") or trainer_state.get("status"),
                "model_version": model_version or trainer_state.get("model_version"),
                "checkpoint_id": checkpoint_id,
                "cuda_active": trainer_state.get("cuda_active"),
                "data_coverage": trainer_state.get("data_coverage"),
                "calibration_available": False,
                "feature_importance_available": False,
            },
            source=trainer_data.get("source", "trainer_redis_evidence"),
            source_type=trainer_data.get("source_type", "redis"),
            timestamp=trainer_data.get("timestamp") or _utc_now(),
            missing_fields=["calibration", "feature_importance", "realized_vs_predicted"] if not predictions else ["calibration", "feature_importance"],
            warnings=[*(trainer_data.get("warnings") or []), "Prediction matrix and calibration data require a connected training pipeline"],
            mode="read_only",
        )
    except Exception as exc:
        return _base_response(
            endpoint=endpoint,
            data={"predictions": [], "count": 0, "trainer_status": "unavailable"},
            source="trainer_service",
            source_type="unavailable",
            timestamp=_utc_now(),
            missing_fields=["predictions", "calibration", "feature_importance"],
            warnings=[f"Trainer service unavailable: {exc}"],
            mode="read_only",
        )


@router.get("/market/{symbol}")
async def get_market_detail(symbol: str) -> dict[str, Any]:
    safe_symbol = _strict_market_symbol(symbol)
    if safe_symbol is None:
        return _invalid_market_symbol_response("/api/v2/market/{symbol}")
    endpoint = f"/api/v2/market/{safe_symbol}"
    api_data, api_missing, api_warnings, api_sources = await run_in_threadpool(_binance_market_snapshot, safe_symbol)
    if api_data is not None:
        return _base_response(
            endpoint=endpoint,
            data=api_data,
            source=" + ".join(api_sources),
            source_type="api",
            timestamp=_utc_now(),
            missing_fields=api_missing,
            warnings=[
                "Binance public USD-M market data; read-only source",
                "Realtime stream is still pending; this endpoint refreshes per request",
                *api_warnings,
            ],
            symbol=safe_symbol,
            mode="read_only",
        )
    terminal, source = _terminal_payload()
    if not terminal:
        return _unavailable(
            endpoint=endpoint,
            symbol=safe_symbol,
            missing_fields=["last_price", "funding_rate", "open_interest", "spread"],
            warning="Market detail fallback source is unavailable",
        )
    warnings = ["Static payload fallback; not a live market stream"]
    if _symbol_from_payload(symbol, terminal) != _symbol_from_payload(None, terminal):
        warnings.append("Fallback payload symbol differs from requested symbol")
    data = {
        "symbol": _symbol_from_payload(symbol, terminal),
        "last_price": terminal.get("last_price"),
        "mark_price": None,
        "index_price": None,
        "change_1h": None,
        "change_4h": None,
        "change_24h": None,
        "high_24h": None,
        "low_24h": None,
        "volume_24h": terminal.get("quote_volume_24h") or terminal.get("volume_5m"),
        "turnover_24h": terminal.get("quote_volume_24h"),
        "funding_rate": terminal.get("funding_rate"),
        "next_funding": None,
        "open_interest": terminal.get("open_interest"),
        "open_interest_change": terminal.get("open_interest_change_pct"),
        "bid": terminal.get("bid"),
        "ask": terminal.get("ask"),
        "spread_bps": terminal.get("spread_bps"),
    }
    missing = [key for key, value in data.items() if value is None and key != "symbol"]
    return _base_response(
        endpoint=endpoint,
        data=data,
        source=source,
        source_type="static_payload",
        timestamp=_timestamp_from_payload(terminal),
        missing_fields=missing,
        warnings=warnings,
        symbol=safe_symbol,
        mode="read_only",
    )


@router.get("/market/{symbol}/ticker")
async def get_market_ticker(symbol: str) -> dict[str, Any]:
    safe_symbol = _strict_market_symbol(symbol)
    if safe_symbol is None:
        return _invalid_market_symbol_response("/api/v2/market/{symbol}/ticker")
    detail = await get_market_detail(safe_symbol)
    detail["endpoint"] = f"/api/v2/market/{safe_symbol}/ticker"
    return detail


def _derivatives_realtime_source_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_DERIVATIVES_REALTIME_SOURCE_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def _derivatives_realtime_source_evidence() -> dict[str, Any]:
    artifact_path = _derivatives_realtime_source_artifact_path()
    if artifact_path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "missing_fields": ["derivatives_realtime_source_artifact"],
            "warnings": ["Production derivatives realtime/source validation artifact is not configured"],
            "live_trading_enabled": False,
            "exchange_mutation_enabled": False,
        }
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "missing_fields": ["derivatives_realtime_source_artifact"],
            "warnings": [f"Production derivatives realtime/source validation artifact could not be read: {type(exc).__name__}"],
            "live_trading_enabled": False,
            "exchange_mutation_enabled": False,
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "missing_fields": ["derivatives_realtime_source_artifact"],
            "warnings": ["Production derivatives realtime/source validation artifact must be a JSON object"],
            "live_trading_enabled": False,
            "exchange_mutation_enabled": False,
        }
    status_value = str(payload.get("derivatives_realtime_source_status") or payload.get("status") or "").strip().lower()
    required_flags = {
        "funding_realtime_verified": payload.get("funding_realtime_verified") is True,
        "open_interest_realtime_verified": payload.get("open_interest_realtime_verified") is True,
        "liquidation_source_verified": payload.get("liquidation_source_verified") is True,
        "long_short_source_verified": payload.get("long_short_source_verified") is True,
        "basis_source_verified": payload.get("basis_source_verified") is True,
        "exchange_comparison_verified": payload.get("exchange_comparison_verified") is True,
        "freshness_enforced": payload.get("freshness_enforced") is True,
        "stale_marking_verified": payload.get("stale_marking_verified") is True,
        "source_labels_verified": payload.get("source_labels_verified") is True,
        "no_static_presented_as_live": payload.get("no_static_presented_as_live") is True,
    }
    fake_live_data_detected = payload.get("fake_live_data_detected") is True
    live_trading_enabled = payload.get("live_trading_enabled") is True
    exchange_mutation_enabled = payload.get("exchange_mutation_enabled") is True
    live_submit_available = payload.get("live_submit_available") is True
    live_cancel_available = payload.get("live_cancel_available") is True
    missing_fields = [field for field, verified in required_flags.items() if not verified]
    if fake_live_data_detected:
        missing_fields.append("no_fake_live_data")
    if live_trading_enabled or payload.get("live_trading_enabled") is not False:
        missing_fields.append("live_trading_disabled")
    if exchange_mutation_enabled or payload.get("exchange_mutation_enabled") is not False:
        missing_fields.append("exchange_mutation_disabled")
    if live_submit_available:
        missing_fields.append("live_submit_unavailable")
    if live_cancel_available:
        missing_fields.append("live_cancel_unavailable")
    valid = status_value in {"pass", "passed", "ok", "verified"} and not missing_fields
    warnings = [str(warning) for warning in payload.get("warnings", [])] if isinstance(payload.get("warnings"), list) else []
    if not valid:
        warnings.append(
            "Production derivatives artifact must prove realtime funding, OI, liquidation, long/short, basis, exchange-comparison, freshness, stale states, source labels, no fake-live data, and disabled live/exchange mutation"
        )
    return {
        "configured": True,
        "valid": valid,
        "status": "verified" if valid else "invalid",
        **required_flags,
        "fake_live_data_detected": fake_live_data_detected,
        "live_trading_enabled": live_trading_enabled,
        "exchange_mutation_enabled": exchange_mutation_enabled,
        "live_submit_available": live_submit_available,
        "live_cancel_available": live_cancel_available,
        "missing_fields": sorted(set(missing_fields)),
        "warnings": warnings,
    }


def _redis_liquidation_runtime_status(symbol: str, timeframe: str) -> tuple[dict[str, Any], str, str | None, list[str], list[str]] | None:
    candidate_timeframes = [timeframe, "5m", "15m", "1m", "1h", "4h"]
    seen: set[str] = set()
    for candidate in candidate_timeframes:
        if candidate in seen:
            continue
        seen.add(candidate)
        key = f"v2:liquidations:levels:{symbol}:{candidate}"
        payload = _read_v2_redis_json(key)
        if not isinstance(payload, dict):
            continue
        levels_raw = payload.get("liquidation_levels_json")
        levels = {}
        if isinstance(levels_raw, str) and levels_raw.strip():
            try:
                parsed_levels = json.loads(levels_raw)
                if isinstance(parsed_levels, dict):
                    levels = parsed_levels
            except (TypeError, ValueError):
                levels = {}
        timestamp = _timestamp_from_redis_payload(payload)
        stale_flag = bool(_float(payload.get("liquidation_is_stale")) or 0)
        staleness_ms = _float(payload.get("liquidation_staleness_ms"))
        missing = []
        long_level = _float(payload.get("liquidation_long_level"))
        short_level = _float(payload.get("liquidation_short_level"))
        if long_level is None:
            missing.append("liquidation_long_level")
        if short_level is None:
            missing.append("liquidation_short_level")
        level_data = {
            "symbol": symbol,
            "timeframe": candidate,
            "current_price": _float(payload.get("liquidation_current_price")),
            "long_level": long_level,
            "short_level": short_level,
            "long_distance_pct": _float(payload.get("liquidation_long_distance_pct")),
            "short_distance_pct": _float(payload.get("liquidation_short_distance_pct")),
            "long_strength": _float(payload.get("liquidation_long_strength")),
            "short_strength": _float(payload.get("liquidation_short_strength")),
            "volume": _float(payload.get("liquidation_volume")),
            "top_long": levels.get("top_long") if isinstance(levels.get("top_long"), list) else [],
            "top_short": levels.get("top_short") if isinstance(levels.get("top_short"), list) else [],
            "step": _float(levels.get("step")) if isinstance(levels, dict) else None,
            "source": payload.get("liquidation_source") or "redis",
            "source_key": key,
            "timestamp": timestamp,
        }
        return (
            {
                "status": "Redis liquidation levels active" if not missing else "Redis liquidation levels partial",
                "source": key,
                "symbol": symbol,
                "timeframe": candidate,
                "stream_active": not stale_flag,
                "symbol_in_stream": True,
                "events_available": _float(payload.get("liquidation_last_event_ts")) is not None,
                "events_xlen": None,
                "levels_available": not missing,
                "levels": level_data,
                "timestamp": timestamp,
                "lag_ms": _lag_ms(timestamp),
                "stale": stale_flag or (staleness_ms is not None and staleness_ms > 180_000),
                "staleness_ms": staleness_ms,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
            },
            key,
            timestamp,
            missing,
            [
                "V2 Redis liquidation levels loaded from native liquidation ingestor",
                "Live trading and exchange mutation remain disabled",
            ],
        )
    return None


def _liquidation_runtime_status(symbol: str, timeframe: str = "5m") -> tuple[dict[str, Any], str, str | None, list[str], list[str]]:
    redis_status = _redis_liquidation_runtime_status(symbol, timeframe)
    if redis_status is not None:
        return redis_status
    payload, source = _read_json("operator_runtime/v2_liquidation_runtime_status/latest/v2_liquidation_runtime_status.json")
    if not isinstance(payload, dict):
        return (
            {
                "status": "Data source unavailable",
                "source": source,
                "symbol": symbol,
                "stream_active": False,
                "events_available": False,
                "levels_available": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
            },
            source,
            None,
            ["liquidation_runtime_status", "liquidation_levels"],
            ["Liquidation runtime status source is unavailable"],
        )
    timestamp = _timestamp_from_payload(payload)
    lag = _lag_ms(timestamp)
    stale = lag is None or lag > 180_000
    levels_symbols = payload.get("levels_symbols")
    live_symbols = payload.get("live_symbols")
    symbol_in_levels = isinstance(levels_symbols, list) and symbol in {str(item).upper() for item in levels_symbols}
    symbol_in_stream = isinstance(live_symbols, list) and symbol in {str(item).upper() for item in live_symbols}
    btc_levels = symbol == "BTCUSDT" and (
        _float(payload.get("btc_long_level")) is not None
        or _float(payload.get("btc_short_level")) is not None
    )
    level_data = {
        "symbol": "BTCUSDT" if btc_levels else symbol,
        "long_level": _float(payload.get("btc_long_level")) if btc_levels else None,
        "short_level": _float(payload.get("btc_short_level")) if btc_levels else None,
        "long_distance_pct": _float(payload.get("btc_long_distance_pct")) if btc_levels else None,
        "short_distance_pct": _float(payload.get("btc_short_distance_pct")) if btc_levels else None,
        "source": source,
        "timestamp": timestamp,
    }
    stream_active = bool(payload.get("wss_services_active") or payload.get("runtime_services_active")) and not stale
    events_xlen = _float(payload.get("liquidation_events_xlen"))
    status_text = str(payload.get("classification") or "Liquidation source pending").replace("_", " ").title()
    missing = []
    if not stream_active:
        missing.append("liquidation_stream")
    if not symbol_in_stream:
        missing.append("liquidation_stream_symbol")
    if not btc_levels and not symbol_in_levels:
        missing.append("liquidation_levels_symbol")
    warnings = [
        "Liquidation runtime status is source-labeled runtime evidence, not a durable production derivatives repository",
        "1h and 24h liquidation notional aggregates remain unavailable unless a verified derivatives source supplies them",
    ]
    if missing:
        warnings.append("Requested symbol does not have complete liquidation level evidence in the current runtime status")
    return (
        {
            "status": status_text,
            "source": source,
            "symbol": symbol,
            "stream_active": stream_active,
            "symbol_in_stream": symbol_in_stream,
            "events_available": events_xlen is not None and events_xlen > 0,
            "events_xlen": events_xlen,
            "levels_available": btc_levels or symbol_in_levels,
            "levels": level_data if btc_levels else None,
            "timestamp": timestamp,
            "lag_ms": lag,
            "stale": stale,
            "live_trading_enabled": False,
            "exchange_mutation_enabled": False,
        },
        source,
        timestamp,
        missing,
        warnings,
    )


@router.get("/market/{symbol}/derivatives")
async def get_market_derivatives(
    symbol: str,
    timeframe: str = Query(default="5m"),
) -> dict[str, Any]:
    safe_symbol = _strict_market_symbol(symbol)
    if safe_symbol is None:
        return _invalid_market_symbol_response("/api/v2/market/{symbol}/derivatives")
    safe_timeframe = _strict_timeframe(timeframe) or "5m"
    endpoint = f"/api/v2/market/{safe_symbol}/derivatives"
    detail = await get_market_detail(safe_symbol)
    market_data = detail.get("data")
    if not isinstance(market_data, dict):
        return _unavailable(
            endpoint=endpoint,
            symbol=safe_symbol,
            missing_fields=[
                "funding_rate",
                "next_funding",
                "open_interest",
                "open_interest_change",
                "funding_history",
                "open_interest_history",
                "liquidations_1h",
                "liquidations_24h",
                "long_short_ratio",
                "basis",
                "exchange_comparison",
            ],
            warning="Derivatives source is unavailable for this symbol",
        )

    (
        (funding_rows, funding_source, funding_warning),
        (oi_rows, oi_source, oi_warning),
        (long_short_rows, long_short_source, long_short_warning),
    ) = await asyncio.gather(
        _binance_public_json_async("/fapi/v1/fundingRate", {"symbol": safe_symbol, "limit": 24}),
        _binance_public_json_async("/futures/data/openInterestHist", {"symbol": safe_symbol, "period": "5m", "limit": 24}),
        _binance_public_json_async("/futures/data/globalLongShortAccountRatio", {"symbol": safe_symbol, "period": "5m", "limit": 1}),
    )
    funding_history = [
        {"time": time_value, "value": value}
        for row in (funding_rows if isinstance(funding_rows, list) else [])
        if isinstance(row, dict)
        for time_value, value in [(_iso_from_ms(row.get("fundingTime")), _float(row.get("fundingRate")))]
        if time_value is not None and value is not None
    ]
    open_interest_history = [
        {
            "time": time_value,
            "value": value,
            "notional": notional,
        }
        for row in (oi_rows if isinstance(oi_rows, list) else [])
        if isinstance(row, dict)
        for time_value, value, notional in [
            (
                _iso_from_ms(row.get("timestamp")),
                _float(row.get("sumOpenInterest")),
                _float(row.get("sumOpenInterestValue")),
            )
        ]
        if time_value is not None and value is not None
    ]
    long_short_ratio = None
    if isinstance(long_short_rows, list) and long_short_rows:
        last_ratio = long_short_rows[-1]
        if isinstance(last_ratio, dict):
            long_short_ratio = _float(last_ratio.get("longShortRatio"))
    mark_price = _float(market_data.get("mark_price"))
    index_price = _float(market_data.get("index_price"))
    basis = (mark_price - index_price) / index_price if mark_price is not None and index_price else None
    production_source_validation = _derivatives_realtime_source_evidence()
    liquidation_status, liquidation_source, liquidation_timestamp, liquidation_missing, liquidation_warnings = (
        _liquidation_runtime_status(safe_symbol, safe_timeframe)
    )
    source_parts = [
        str(detail.get("source") or "unavailable"),
        *(part for part in (funding_source, oi_source, long_short_source) if part and "127.0.0.1:9" not in part),
        liquidation_source,
    ]
    timestamps = [
        item
        for item in (
            detail.get("timestamp") if isinstance(detail.get("timestamp"), str) else None,
            funding_history[-1]["time"] if funding_history else None,
            open_interest_history[-1]["time"] if open_interest_history else None,
            liquidation_timestamp,
        )
        if isinstance(item, str)
    ]
    data = {
        "symbol": safe_symbol,
        "timeframe": safe_timeframe,
        "funding_rate": market_data.get("funding_rate"),
        "next_funding": market_data.get("next_funding"),
        "open_interest": market_data.get("open_interest"),
        "open_interest_change": market_data.get("open_interest_change"),
        "funding_history": funding_history,
        "open_interest_history": open_interest_history,
        "liquidations_1h": None,
        "liquidations_24h": None,
        "liquidation_stream_status": liquidation_status,
        "liquidation_levels": liquidation_status.get("levels") if isinstance(liquidation_status.get("levels"), dict) else None,
        "long_short_ratio": long_short_ratio,
        "basis": basis,
        "exchange_comparison": [],
        "production_source_validation": production_source_validation,
    }
    missing = [
        key
        for key, value in data.items()
        if key not in {"symbol", "production_source_validation"} and (value is None or value == [])
    ]
    missing = [*missing, *liquidation_missing]
    if not production_source_validation["valid"]:
        missing = [
            *missing,
            "production_derivatives_realtime_source_validation",
            *[str(field) for field in production_source_validation.get("missing_fields", [])],
        ]
    return _base_response(
        endpoint=endpoint,
        data=data,
        source=" + ".join(source_parts),
        source_type="api" if funding_history or open_interest_history or long_short_ratio is not None else detail.get("source_type") if detail.get("source_type") in {"api", "repository", "static_payload"} else "unavailable",
        timestamp=timestamps[-1] if timestamps else None,
        missing_fields=missing,
        warnings=[
            "Read-only derivatives snapshot derived from public market contracts",
            "Funding, open interest, long/short ratio, and basis use Binance public read-only sources where available",
            "Liquidation levels use V2 Redis native-ingestor data where available; 1h/24h liquidation notional aggregates remain source-pending",
            *liquidation_warnings,
            "Production derivatives realtime/source validation artifact verified"
            if production_source_validation["valid"]
            else "Production derivatives realtime/source validation artifact pending",
            *[str(warning) for warning in detail.get("warnings", [])],
            *([funding_warning] if funding_warning else []),
            *([oi_warning] if oi_warning else []),
            *([long_short_warning] if long_short_warning else []),
            *[str(warning) for warning in production_source_validation.get("warnings", [])],
        ],
        symbol=safe_symbol,
        mode="read_only",
    )


@router.get("/market/{symbol}/candles")
async def get_market_candles(
    symbol: str,
    timeframe: str = Query(default="1m"),
) -> dict[str, Any]:
    safe_symbol = _strict_market_symbol(symbol)
    if safe_symbol is None:
        return _invalid_market_symbol_response("/api/v2/market/{symbol}/candles")
    safe_timeframe = _strict_timeframe(timeframe)
    endpoint = f"/api/v2/market/{safe_symbol}/candles"
    if safe_timeframe is None:
        return _invalid_market_timeframe_response(endpoint, safe_symbol)
    klines, api_source, api_warning = await _binance_public_json_async(
        "/fapi/v1/klines",
        {"symbol": safe_symbol, "interval": safe_timeframe, "limit": 500},
    )
    if isinstance(klines, list):
        candles = _closed_candles_from_binance_klines(klines)
        data = {
            "symbol": safe_symbol,
            "timeframe": safe_timeframe,
            "candles": candles,
            "candle_count": len(candles),
        }
        return _base_response(
            endpoint=endpoint,
            data=data,
            source=api_source,
            source_type="api",
            timestamp=_iso_from_ms(candles[-1]["close_time_ms"]) if candles else _utc_now(),
            missing_fields=[] if candles else ["candles"],
            warnings=[
                "Binance public USD-M klines; read-only source",
                "Only closed candles are returned; current unfinished candle is excluded",
                *([api_warning] if api_warning else []),
            ],
            symbol=safe_symbol,
            mode="read_only",
        )
    payload, source = _chart_payload(safe_symbol, safe_timeframe)
    if not payload:
        return _unavailable(
            endpoint=endpoint,
            symbol=safe_symbol,
            missing_fields=["candles"],
            warning="Candle source is not wired for this symbol/timeframe",
        )
    candles = payload.get("candles") if isinstance(payload.get("candles"), list) else []
    data = {
        "symbol": safe_symbol,
        "timeframe": safe_timeframe,
        "candles": candles,
        "candle_count": len(candles),
    }
    return _base_response(
        endpoint=endpoint,
        data=data,
        source=source,
        source_type="static_payload",
        timestamp=_timestamp_from_payload(payload),
        missing_fields=[] if candles else ["candles"],
        warnings=["Static candle snapshot; freshness must be verified by consumer"],
        symbol=safe_symbol,
        mode="read_only",
    )


def _redis_indicator_response(symbol: str, timeframe: str, endpoint: str) -> dict[str, Any] | None:
    key = f"v2:technical_analysis:{symbol}:{timeframe}"
    payload = _read_v2_redis_json(key)
    indicators = payload.get("indicators") if isinstance(payload, dict) else None
    if not isinstance(indicators, dict):
        return None
    ema20 = _point_from_indicator(payload, indicators, "ema_20", "ta_EMA_20")
    ema50 = _point_from_indicator(payload, indicators, "ema_50", "ta_EMA_50")
    bb_upper = _point_from_indicator(payload, indicators, "ta_BBANDS_20_upper", "ta_BBANDS_upperband")
    bb_lower = _point_from_indicator(payload, indicators, "ta_BBANDS_20_lower", "ta_BBANDS_lowerband")
    bb_middle = _point_from_indicator(payload, indicators, "ta_BBANDS_20_middle", "ta_BBANDS_middleband")
    indicator_count = len(ema20) + len(ema50) + len(bb_upper) + len(bb_lower) + len(bb_middle)
    if indicator_count <= 0:
        return None
    data = {
        "symbol": symbol,
        "timeframe": timeframe,
        "ema20": ema20,
        "ema50": ema50,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_middle": bb_middle,
        "ai_target": [],
        "indicator_count": indicator_count,
        "controls_enabled": True,
        "indicator_snapshot": {
            "close": _float(indicators.get("close")),
            "rsi_14": _float(indicators.get("rsi_14") or indicators.get("ta_RSI_14")),
            "macd": _float(indicators.get("macd") or indicators.get("ta_MACD_12_26_9_macd")),
            "macd_signal": _float(indicators.get("macd_signal") or indicators.get("ta_MACD_12_26_9_signal")),
            "macd_hist": _float(indicators.get("macd_hist") or indicators.get("ta_MACD_12_26_9_hist")),
            "atr_14": _float(indicators.get("atr_14") or indicators.get("ta_ATR_14")),
            "bb_width_pct": _float(indicators.get("bb_width_pct") or indicators.get("ta_BB_width_pct")),
        },
    }
    missing_fields = [
        *([] if ema20 else ["ema20"]),
        *([] if ema50 else ["ema50"]),
        *([] if bb_upper else ["bb_upper"]),
        *([] if bb_lower else ["bb_lower"]),
        *([] if bb_middle else ["bb_middle"]),
        "ai_target",
    ]
    return _base_response(
        endpoint=endpoint,
        data=data,
        source=f"Redis technical analysis publisher {key}",
        source_type="repository",
        timestamp=_timestamp_from_redis_payload(payload),
        missing_fields=missing_fields,
        warnings=[
            "Typed indicator evidence loaded from V2 Redis technical-analysis publisher",
            "Redis TA payload stores latest indicator values; one-point overlays use the last closed candle timestamp",
            "AI target overlay remains unavailable until a typed prediction overlay source exists",
        ],
        symbol=symbol,
        mode="read_only",
    )


@router.get("/market/{symbol}/indicators")
async def get_market_indicators(
    symbol: str,
    timeframe: str = Query(default="1m"),
) -> dict[str, Any]:
    safe_symbol = _strict_market_symbol(symbol)
    if safe_symbol is None:
        return _invalid_market_symbol_response("/api/v2/market/{symbol}/indicators")
    safe_timeframe = _strict_timeframe(timeframe)
    endpoint = f"/api/v2/market/{safe_symbol}/indicators"
    if safe_timeframe is None:
        return _invalid_market_timeframe_response(endpoint, safe_symbol)
    redis_response = _redis_indicator_response(safe_symbol, safe_timeframe, endpoint)
    if redis_response is not None:
        return redis_response
    klines, api_source, api_warning = await _binance_public_json_async(
        "/fapi/v1/klines",
        {"symbol": safe_symbol, "interval": safe_timeframe, "limit": 500},
    )
    candles = _closed_candles_from_binance_klines(klines)
    if candles:
        ema20 = _ema_series(candles, 20)
        ema50 = _ema_series(candles, 50)
        bb_upper, bb_lower, bb_middle = _bollinger_series(candles)
        indicator_count = len(ema20) + len(ema50) + len(bb_upper) + len(bb_lower) + len(bb_middle)
        missing_fields = [
            *([] if ema20 else ["ema20"]),
            *([] if ema50 else ["ema50"]),
            *([] if bb_upper else ["bb_upper"]),
            *([] if bb_lower else ["bb_lower"]),
            *([] if bb_middle else ["bb_middle"]),
            "ai_target",
        ]
        return _base_response(
            endpoint=endpoint,
            data={
                "symbol": safe_symbol,
                "timeframe": safe_timeframe,
                "ema20": ema20,
                "ema50": ema50,
                "bb_upper": bb_upper,
                "bb_lower": bb_lower,
                "bb_middle": bb_middle,
                "ai_target": [],
                "indicator_count": indicator_count,
                "controls_enabled": indicator_count > 0,
            },
            source=api_source,
            source_type="api",
            timestamp=_iso_from_ms(candles[-1]["close_time_ms"]) if candles else _utc_now(),
            missing_fields=missing_fields,
            warnings=[
                "EMA and Bollinger indicators are derived from Binance public USD-M closed klines",
                "Only closed candles are used for indicator calculations",
                "AI target overlay remains unavailable until a typed prediction overlay source exists",
                *([api_warning] if api_warning else []),
            ],
            symbol=safe_symbol,
            mode="read_only",
        )
    return _base_response(
        endpoint=endpoint,
        data={
            "symbol": safe_symbol,
            "timeframe": safe_timeframe,
            "ema20": [],
            "ema50": [],
            "bb_upper": [],
            "bb_lower": [],
            "bb_middle": [],
            "ai_target": [],
            "indicator_count": 0,
            "controls_enabled": False,
        },
        source="unavailable",
        source_type="unavailable",
        timestamp=None,
        missing_fields=[
            "ema20",
            "ema50",
            "bb_upper",
            "bb_lower",
            "bb_middle",
            "ai_target",
            "typed_indicator_repository",
        ],
        warnings=[
            "Typed indicator source is unavailable",
            "Static chart-file indicators are withheld and are not presented as live",
        ],
        symbol=safe_symbol,
        mode="read_only",
    )


@router.get("/market/{symbol}/depth")
async def get_market_depth(symbol: str) -> dict[str, Any]:
    safe_symbol = _strict_market_symbol(symbol)
    if safe_symbol is None:
        return _invalid_market_symbol_response("/api/v2/market/{symbol}/depth")
    endpoint = f"/api/v2/market/{safe_symbol}/depth"
    depth, api_source, api_warning = await _binance_public_json_async(
        "/fapi/v1/depth",
        {"symbol": safe_symbol, "limit": 100},
    )
    if isinstance(depth, dict):
        bids = [
            [_float(row[0]), _float(row[1])]
            for row in depth.get("bids", [])
            if isinstance(row, list) and len(row) >= 2 and _float(row[0]) is not None and _float(row[1]) is not None
        ]
        asks = [
            [_float(row[0]), _float(row[1])]
            for row in depth.get("asks", [])
            if isinstance(row, list) and len(row) >= 2 and _float(row[0]) is not None and _float(row[1]) is not None
        ]
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        mid = ((best_bid + best_ask) / 2) if best_bid is not None and best_ask is not None else None
        spread_bps = ((best_ask - best_bid) / mid * 10_000) if best_bid is not None and best_ask is not None and mid else None
        data = {
            "symbol": safe_symbol,
            "bids": bids,
            "asks": asks,
            "spread_bps": spread_bps,
            "depth_type": "binance_public_ladder",
        }
        missing = []
        if not bids:
            missing.append("bids")
        if not asks:
            missing.append("asks")
        if spread_bps is None:
            missing.append("spread")
        return _base_response(
            endpoint=endpoint,
            data=data,
            source=api_source,
            source_type="api",
            timestamp=_utc_now(),
            missing_fields=missing,
            warnings=[
                "Binance public USD-M depth; read-only source",
                "Realtime order book stream is still pending; this endpoint refreshes per request",
                *([api_warning] if api_warning else []),
            ],
            symbol=safe_symbol,
            mode="read_only",
        )
    terminal, source = _terminal_payload()
    if not terminal:
        return _unavailable(
            endpoint=endpoint,
            symbol=safe_symbol,
            missing_fields=["bids", "asks", "spread"],
            warning="Depth source is not wired yet",
        )
    bid = terminal.get("bid")
    ask = terminal.get("ask")
    bid_size = terminal.get("book_bid_5")
    ask_size = terminal.get("book_ask_5")
    data = {
        "symbol": safe_symbol,
        "bids": [[bid, bid_size]] if bid is not None and bid_size is not None else [],
        "asks": [[ask, ask_size]] if ask is not None and ask_size is not None else [],
        "spread_bps": terminal.get("spread_bps"),
        "depth_type": "top_of_book_fallback",
    }
    missing = []
    if not data["bids"]:
        missing.append("bids")
    if not data["asks"]:
        missing.append("asks")
    if data["spread_bps"] is None:
        missing.append("spread")
    return _base_response(
        endpoint=endpoint,
        data=data,
        source=source,
        source_type="static_payload",
        timestamp=_timestamp_from_payload(terminal),
        missing_fields=missing + ["full_ladder"],
        warnings=["Only top-of-book fallback is available; full ladder is not wired"],
        symbol=safe_symbol,
        mode="read_only",
    )


@router.get("/market/{symbol}/trades")
async def get_recent_trades(symbol: str) -> dict[str, Any]:
    safe_symbol = _strict_market_symbol(symbol)
    if safe_symbol is None:
        return _invalid_market_symbol_response("/api/v2/market/{symbol}/trades")
    endpoint = f"/api/v2/market/{safe_symbol}/trades"
    trades, api_source, api_warning = await _binance_public_json_async(
        "/fapi/v1/trades",
        {"symbol": safe_symbol, "limit": 80},
    )
    if isinstance(trades, list):
        rows: list[dict[str, Any]] = []
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            price = _float(trade.get("price"))
            size = _float(trade.get("qty"))
            time_value = _iso_from_ms(trade.get("time"))
            if price is None or size is None or time_value is None:
                continue
            rows.append(
                {
                    "time": time_value,
                    "price": price,
                    "size": size,
                    "side": "sell" if trade.get("isBuyerMaker") is True else "buy",
                }
            )
        return _base_response(
            endpoint=endpoint,
            data={"symbol": safe_symbol, "trades": rows},
            source=api_source,
            source_type="api",
            timestamp=rows[-1]["time"] if rows else _utc_now(),
            missing_fields=[] if rows else ["trades"],
            warnings=[
                "Binance public USD-M recent trades; read-only source",
                "Realtime trade stream is still pending; this endpoint refreshes per request",
                *([api_warning] if api_warning else []),
            ],
            symbol=safe_symbol,
            mode="read_only",
        )
    return _unavailable(
        endpoint=endpoint,
        symbol=safe_symbol,
        missing_fields=["trades", "trade_stream"],
        warning="Recent trade stream is not wired yet",
    )


async def _market_stream_snapshot(symbol: str, timeframe: str = "1m") -> dict[str, Any]:
    safe_symbol = _strict_market_symbol(symbol)
    safe_timeframe = _strict_timeframe(timeframe)
    if safe_symbol is None or safe_timeframe is None:
        missing_fields = []
        warnings = []
        if safe_symbol is None:
            missing_fields.append("symbol")
            warnings.append("Enter a valid market symbol")
        if safe_timeframe is None:
            missing_fields.append("timeframe")
            warnings.append("Select a supported chart timeframe")
        return {
            "type": "market_snapshot",
            "endpoint": "/ws/market-data",
            "received_at": _utc_now(),
            "symbol": None,
            "exchange": None,
            "mode": "read_only",
            "source": "unavailable",
            "source_type": "unavailable",
            "stale": True,
            "missing_fields": missing_fields,
            "warnings": warnings,
            "ticker": None,
            "depth": None,
            "trades": None,
            "candles": None,
            "stream_health": None,
        }
    ticker, depth, trades, candles = await asyncio.gather(
        get_market_detail(safe_symbol),
        get_market_depth(safe_symbol),
        get_recent_trades(safe_symbol),
        get_market_candles(safe_symbol, safe_timeframe),
    )
    stale = any(bool(item.get("stale")) for item in (ticker, depth, trades, candles))
    missing_fields = sorted(
        {
            str(field)
            for item in (ticker, depth, trades, candles)
            for field in item.get("missing_fields", [])
        }
    )
    warnings = [
        "Read-only public market stream; no signed account data and no exchange mutation",
        "This stream is request-time polling over safe market contracts until native exchange WebSocket adapters are promoted",
    ]
    for item in (ticker, depth, trades, candles):
        warnings.extend(str(warning) for warning in item.get("warnings", []))
    return {
        "type": "market_snapshot",
        "endpoint": "/ws/market-data",
        "received_at": _utc_now(),
        "symbol": safe_symbol,
        "exchange": "Binance USD-M",
        "mode": "read_only",
        "source": "safe_api_contract_stream",
        "source_type": "api",
        "stale": stale,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "ticker": ticker,
        "depth": depth,
        "trades": trades,
        "candles": candles,
        "stream_health": _market_stream_telemetry(safe_symbol),
    }


async def _market_data_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    symbol = _strict_market_symbol(str(websocket.query_params.get("symbol", "BTCUSDT") or "BTCUSDT"))
    try:
        requested_interval = int(websocket.query_params.get("interval_ms", "2000"))
    except ValueError:
        requested_interval = 2000
    timeframe = _strict_timeframe(str(websocket.query_params.get("timeframe", "1m") or "1m"))
    if symbol is None or timeframe is None:
        await websocket.send_json(await _market_stream_snapshot(symbol or "", timeframe or ""))
        await websocket.close(code=1008)
        return

    await websocket.send_json(await _market_stream_snapshot(symbol, timeframe))

    interval_seconds = max(1.0, min(15.0, requested_interval / 1000))
    used_native_stream = await _native_market_data_websocket(websocket, symbol, timeframe)
    if used_native_stream:
        return
    try:
        while True:
            _record_market_stream_event(
                symbol,
                source="safe_api_contract_stream",
                event="fallback_snapshot",
            )
            await websocket.send_json(await _market_stream_snapshot(symbol, timeframe))
            await asyncio.sleep(interval_seconds)
    except WebSocketDisconnect:
        return


async def _native_market_data_websocket(websocket: WebSocket, symbol: str, timeframe: str) -> bool:
    if not BINANCE_NATIVE_STREAM_ENABLED:
        return False
    try:
        import websockets  # type: ignore
    except Exception:
        return False

    safe_symbol = _strict_market_symbol(symbol)
    safe_timeframe = _strict_timeframe(timeframe)
    if safe_symbol is None or safe_timeframe is None:
        return False
    url = _native_stream_url(safe_symbol, safe_timeframe)
    state: dict[str, Any] = {}
    _record_market_stream_event(
        safe_symbol,
        source="binance_usdm_public_websocket_adapter",
        event="connect_attempt",
    )
    try:
        async with websockets.connect(  # type: ignore[attr-defined]
            url,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=10,
            close_timeout=5,
            max_queue=512,
        ) as upstream:
            while True:
                raw = await upstream.recv()
                if not isinstance(raw, str):
                    continue
                updated = _apply_native_stream_message(
                    raw=raw,
                    state=state,
                    symbol=safe_symbol,
                    timeframe=safe_timeframe,
                )
                if updated is not None:
                    _record_market_stream_event(
                        safe_symbol,
                        source="binance_usdm_public_websocket_adapter",
                        event="native_frame",
                    )
                    await websocket.send_json(_native_stream_snapshot(safe_symbol, state))
    except WebSocketDisconnect:
        return True
    except Exception as exc:
        _record_market_stream_event(
            safe_symbol,
            source="binance_usdm_public_websocket_adapter",
            event="native_error",
            error=type(exc).__name__,
        )
        return False


@router.websocket("/ws/market-data")
async def api_v2_market_data_stream(websocket: WebSocket) -> None:
    await _market_data_websocket(websocket)


@stream_router.websocket("/ws/market-data")
async def root_market_data_stream(websocket: WebSocket) -> None:
    await _market_data_websocket(websocket)


@router.get("/market/{symbol}/stream-status")
async def get_market_stream_status(symbol: str) -> dict[str, Any]:
    safe_symbol = _strict_market_symbol(symbol)
    if safe_symbol is None:
        return _invalid_market_symbol_response("/api/v2/market/{symbol}/stream-status")
    endpoint = f"/api/v2/market/{safe_symbol}/stream-status"
    telemetry = _market_stream_telemetry(safe_symbol)
    alert = _market_stream_alert(telemetry)
    production_alerting = production_market_stream_alerting_evidence()
    production_validation = production_market_stream_validation_evidence()
    missing = ["production_stream_current_validation"]
    if not production_alerting["valid"]:
        missing.append("production_alerting")
    if not production_validation["valid"]:
        missing.append("production_stream_validation")
    if not telemetry.get("last_frame_at"):
        missing.append("last_frame_at")
    production_alerting_status = (
        "artifact_present_pending_current_validation"
        if production_alerting["valid"]
        else "missing"
    )
    production_validation_status = (
        "artifact_present_pending_current_validation"
        if production_validation["valid"]
        else "missing"
    )
    return _base_response(
        endpoint=endpoint,
        data={
            **telemetry,
            "alert": alert,
            "alert_history": read_market_stream_alert_history(safe_symbol, limit=20),
            "alert_history_summary": market_stream_alert_history_summary(safe_symbol),
            "alert_notifier": market_stream_alert_notifier_status(),
            "production_alerting_integrated": bool(production_alerting["valid"]),
            "production_alerting_status": production_alerting_status,
            "production_alerting_artifact_configured": bool(production_alerting["configured"]),
            "production_alerting_artifact_valid": bool(production_alerting["valid"]),
            "production_alerting_artifact_status": str(production_alerting["status"]),
            "production_alerting_evidence": production_alerting,
            "production_validation_integrated": bool(production_validation["valid"]),
            "production_validation_status": production_validation_status,
            "production_validation_artifact_configured": bool(production_validation["configured"]),
            "production_validation_artifact_valid": bool(production_validation["valid"]),
            "production_validation_artifact_status": str(production_validation["status"]),
            "production_validation_evidence": production_validation,
        },
        source="in_memory_market_stream_telemetry",
        source_type="repository",
        timestamp=telemetry.get("updated_at"),
        missing_fields=missing,
        warnings=[
            "In-memory stream telemetry resets on backend restart",
            "Telemetry is read-only and contains no signed-identity data",
            "Production stream alerting/dashboard integration remains pending current validation",
            "Production stream source validation remains pending current validation",
            *[str(warning) for warning in production_alerting["warnings"]],
            *[str(warning) for warning in production_validation["warnings"]],
        ],
        symbol=safe_symbol,
        mode="read_only",
    )


@router.get("/portfolio")
async def get_portfolio(actor: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    endpoint = "/api/v2/portfolio"
    repository_account = _repository_account(actor)
    if actor and repository_account is not None:
        positions, position_missing, position_warnings = _repository_scoped_rows(repository_account, actor, "positions")
        position_metrics: dict[str, Any] | None = None
        enrich_source = ""
        # Primary paper source: Redis portfolio state, with static runtime JSON as read-only fallback.
        portfolio_state, portfolio_state_source, portfolio_state_source_type, portfolio_state_warnings = _runtime_portfolio_state()
        if portfolio_state and not _runtime_payload_available_to_actor(portfolio_state, actor):
            portfolio_state = {}
            portfolio_state_source = ""
            portfolio_state_source_type = "unavailable"
            position_missing.append("portfolio_state_scope")
            position_warnings.append(
                "Paper runtime portfolio state was withheld because payload scope did not match the authenticated trader"
            )
        position_warnings.extend(portfolio_state_warnings)
        # Supplement with Redis paper heartbeat when repo equity is missing
        redis_hb: dict[str, Any] = {}
        try:
            hb_raw = get_redis().get("v2:paper:heartbeat")
            if hb_raw:
                redis_hb = json.loads(hb_raw)
        except Exception:
            pass
        # Fall back to v2:paper:positions Redis when repo has no positions
        if not positions and portfolio_state:
            try:
                _pp_raw = get_redis().get("v2:paper:positions")
                if _pp_raw:
                    _pp_list = json.loads(_pp_raw)
                    if isinstance(_pp_list, list):
                        positions = [
                            _with_actor_scope({
                                **p,
                                "quantity": p.get("net_quantity"),
                                "entry_price": p.get("avg_entry_price") or p.get("entry_price"),
                                "mark_price": p.get("last_mark_price") or p.get("mark_price"),
                                "mark_price_source": p.get("latest_price_source") or "v2:paper:positions",
                                "unrealized_pnl": p.get("unrealized_pnl"),
                                "realized_pnl": p.get("realized_pnl"),
                            }, actor)
                            for p in _pp_list
                        ]
            except Exception:
                pass
        if not positions and portfolio_state:
            runtime_positions, runtime_missing, runtime_warnings = _runtime_portfolio_positions(portfolio_state, actor)
            if runtime_positions:
                positions = runtime_positions
            position_missing.extend(runtime_missing)
            position_warnings.extend(runtime_warnings)
        positions, position_metrics, enrich_missing, enrich_warnings, enrich_source = _enrich_position_rows_for_read_response(positions)
        position_missing.extend(enrich_missing)
        position_warnings.extend(enrich_warnings)
        equity = repository_account.get("equity")
        repository_equity = _float(equity)
        realized_pnl = repository_account.get("realized_pnl")
        unrealized_pnl = repository_account.get("unrealized_pnl")
        _clamp_pnl = lambda v: round(v, 4) if v is not None and abs(v) >= 0.001 else (0.0 if v is not None else None)
        # Use portfolio_state as primary source when repo has no real PnL activity
        _repo_realized_pnl = _float(realized_pnl)
        _repo_has_pnl = _repo_realized_pnl is not None and abs(_repo_realized_pnl) > 0.01
        if not _repo_has_pnl and portfolio_state:
            _ps_equity = _float(portfolio_state.get("equity"))
            _ps_rpnl = _float(portfolio_state.get("realized_pnl_usd"))
            _ps_upnl = _float(portfolio_state.get("unrealized_pnl_usd")) or _float(portfolio_state.get("net_unrealized_pnl"))
            if _ps_equity is not None:
                equity = _ps_equity
                realized_pnl = _ps_rpnl
                unrealized_pnl = _ps_upnl
        elif equity is None and redis_hb:
            realized_pnl = realized_pnl if realized_pnl is not None else _float(redis_hb.get("realized_pnl_usd"))
            unrealized_pnl = unrealized_pnl if unrealized_pnl is not None else _float(redis_hb.get("unrealized_pnl_usd"))
            equity = round(PAPER_INITIAL_CAPITAL + (realized_pnl or 0) + (unrealized_pnl or 0), 4)
        if position_metrics is not None:
            unrealized_pnl = position_metrics.get("unrealized_pnl_usd")
            should_synthesize_equity = (
                equity is None
                or (
                    _float(portfolio_state.get("equity")) is None
                    and repository_equity == PAPER_INITIAL_CAPITAL
                    and not _repo_has_pnl
                )
            )
            if should_synthesize_equity:
                base_realized_for_equity = realized_pnl if realized_pnl is not None else _float(redis_hb.get("realized_pnl_usd")) or 0.0
                equity = round(PAPER_INITIAL_CAPITAL + base_realized_for_equity + (unrealized_pnl or 0.0), 4)
        def _first_not_none(*values: Any) -> Any:
            for value in values:
                if value is not None:
                    return value
            return None
        _open_count = (
            _first_not_none(
                _integer(portfolio_state.get("open_positions_count")),
                _integer(redis_hb.get("open_position_count")),
                len([p for p in positions if not str(p.get("status", "")).lower().startswith("closed")]),
            )
        )
        _closed_count = (
            _first_not_none(
                _integer(portfolio_state.get("closed_positions_count")),
                _integer(redis_hb.get("closed_trade_count")),
            )
        )
        _notional = _first_not_none(
            _float(portfolio_state.get("open_position_notional")),
            _float(redis_hb.get("total_open_notional")),
        )
        data = {
            "equity": equity,
            "paper_equity": equity,
            "paper_balance": equity,
            "paper_initial_capital": PAPER_INITIAL_CAPITAL,
            "realized_pnl": _clamp_pnl(realized_pnl),
            "unrealized_pnl": _clamp_pnl(unrealized_pnl),
            "open_position_count": _open_count,
            "closed_trade_count": _closed_count,
            "total_open_notional": _notional,
            "position_pricing": position_metrics,
            "positions": positions,
            "mode": "paper",
            "trader_id": repository_account.get("trader_id"),
            "paper_account_id": repository_account.get("paper_account_id"),
            "account_scope": "authenticated_trader",
            "account_specific": True,
        }
        missing = [
            key
            for key in ("equity", "realized_pnl", "unrealized_pnl")
            if data.get(key) is None
        ]
        missing.extend(position_missing)
        response_source_parts = [TRADER_ACCOUNT_REPOSITORY_SOURCE]
        if portfolio_state_source:
            response_source_parts.append(portfolio_state_source)
        response_source_parts.append("redis:v2:paper:positions")
        if enrich_source:
            response_source_parts.append(enrich_source.lstrip(" + "))
        return _base_response(
            endpoint=endpoint,
            data=data,
            source=" + ".join(response_source_parts),
            source_type=portfolio_state_source_type if portfolio_state else "repository",
            timestamp=_timestamp_from_payload(portfolio_state) or repository_account.get("updated_at") or _utc_now(),
            missing_fields=missing,
            warnings=[
                "Trader-scoped paper account: canonical paper source v2:portfolio:state + v2:paper:positions",
                *position_warnings,
            ],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    # Canonical source: v2:portfolio:state Redis (always available, no scoping)
    pub_portfolio_state: dict[str, Any] = {}
    pub_positions: list[dict[str, Any]] = []
    try:
        _pub_ps_raw = get_redis().get("v2:portfolio:state")
        if _pub_ps_raw:
            pub_portfolio_state = json.loads(_pub_ps_raw)
    except Exception:
        pass
    try:
        _pub_pp_raw = get_redis().get("v2:paper:positions")
        if _pub_pp_raw:
            _pub_pp_list = json.loads(_pub_pp_raw)
            if isinstance(_pub_pp_list, list):
                pub_positions = [
                    {
                        **p,
                        "quantity": p.get("net_quantity"),
                        "entry_price": p.get("avg_entry_price") or p.get("entry_price"),
                        "mark_price": p.get("last_mark_price") or p.get("mark_price"),
                        "mark_price_source": p.get("latest_price_source") or "v2:paper:positions",
                        "unrealized_pnl": p.get("unrealized_pnl"),
                        "realized_pnl": p.get("realized_pnl"),
                    }
                    for p in _pub_pp_list
                ]
    except Exception:
        pass
    # Supplement with Redis paper heartbeat
    try:
        hb_raw_public = get_redis().get("v2:paper:heartbeat")
        redis_hb_public: dict[str, Any] = json.loads(hb_raw_public) if hb_raw_public else {}
    except Exception:
        redis_hb_public = {}
    paper, paper_source = _paper_payload()
    portfolio, portfolio_source = _portfolio_payload()
    if not paper and not portfolio and not redis_hb_public and not pub_portfolio_state:
        return _unavailable(
            endpoint=endpoint,
            missing_fields=["equity", "positions", "pnl"],
            warning="Portfolio sources are unavailable",
            mode="paper",
        ) | {"trader_context": _trader_context(actor), "account_scope": _actor_account_scope_context(actor, None)}
    scoped_paper = _payload_matches_actor(paper, actor)
    scoped_portfolio = _payload_matches_actor(portfolio, actor)
    account = paper.get("paper_account") if scoped_paper and isinstance(paper, dict) else {}
    portfolio_data = portfolio if isinstance(portfolio, dict) else {}
    # Use Redis paper positions (no scoping required — paper trading system)
    positions = pub_positions if pub_positions else _scoped_rows(portfolio_data.get("positions") if scoped_portfolio else [], actor)
    position_scope_missing = False
    # Prefer canonical Redis portfolio state for PnL and equity
    base_realized = (
        _float(pub_portfolio_state.get("realized_pnl_usd"))
        or _float(account.get("realized_pnl") if scoped_paper and isinstance(account, dict) else None)
        or _float(portfolio_data.get("realized_pnl_usd") if scoped_portfolio else None)
        or _float(redis_hb_public.get("realized_pnl_usd"))
    )
    base_unrealized = (
        _float(pub_portfolio_state.get("unrealized_pnl_usd"))
        or _float(account.get("unrealized_pnl") if scoped_paper and isinstance(account, dict) else None)
        or _float(portfolio_data.get("net_unrealized_pnl") if scoped_portfolio else None)
        or _float(redis_hb_public.get("unrealized_pnl_usd"))
    )
    base_equity = (
        _float(pub_portfolio_state.get("equity"))
        or _float(account.get("equity") if scoped_paper and isinstance(account, dict) else None)
        or _float(portfolio_data.get("equity") if scoped_portfolio else None)
        or round(PAPER_INITIAL_CAPITAL + (base_realized or 0) + (base_unrealized or 0), 4)
    )
    _ps_open_count = pub_portfolio_state.get("open_positions_count")
    _ps_closed_count = pub_portfolio_state.get("closed_positions_count")
    _clamp = lambda v: round(v, 4) if v is not None and abs(v) >= 0.001 else (0.0 if v is not None else None)
    data = {
        "equity": base_equity,
        "paper_equity": base_equity,
        "paper_balance": base_equity,
        "realized_pnl": _clamp(base_realized),
        "unrealized_pnl": _clamp(base_unrealized),
        "paper_initial_capital": PAPER_INITIAL_CAPITAL,
        "open_position_count": _ps_open_count or redis_hb_public.get("open_position_count") or len(positions),
        "closed_trade_count": _ps_closed_count or redis_hb_public.get("closed_trade_count"),
        "total_open_notional": _float(pub_portfolio_state.get("open_position_notional")) or _float(redis_hb_public.get("total_open_notional")),
        "positions": positions,
        "mode": "paper",
        "trader_id": actor.get("trader_id") if actor else None,
        "paper_account_id": actor.get("paper_account_id") if actor else None,
        "account_scope": "authenticated_trader" if actor else "public_read_only",
        "account_specific": bool(scoped_paper or scoped_portfolio),
    }
    missing = [key for key in ("equity", "realized_pnl", "unrealized_pnl") if data.get(key) is None]
    if not positions:
        missing.append("positions")
    if not data["account_specific"]:
        missing.append("trader_specific_repository")
    warnings = ["Paper/static payload fallback; not a brokerage account API"]
    if position_scope_missing:
        warnings.append("Unscoped or mismatched fallback positions were withheld from authenticated trader account view")
    if actor:
        warnings.append(
            "Authenticated trader context attached"
            if data["account_specific"]
            else _account_scope_warning(actor)
        )
    else:
        warnings.append(_account_scope_warning(actor))
    return _base_response(
        endpoint=endpoint,
        data=data,
        source=f"{paper_source} + {portfolio_source}",
        source_type="static_payload",
        timestamp=_timestamp_from_payload(paper) or _timestamp_from_payload(portfolio),
        missing_fields=missing,
        warnings=warnings,
        mode="paper",
        trader_context=_trader_context(actor),
    )


@router.get("/account/readiness")
async def get_account_readiness(actor: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    endpoint = "/api/v2/account/readiness"
    if actor is None:
        data = _safe_trader_account_readiness_data(actor=None, repository_account=None, readiness=None)
        return _base_response(
            endpoint=endpoint,
            data=data,
            source="unavailable",
            source_type="unavailable",
            timestamp=None,
            missing_fields=["trader_session", "trader_account_repository"],
            warnings=[
                "Sign in to view trader-specific account readiness",
                "Live trading remains disabled",
                "No exchange state was read or mutated",
            ],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    repository = get_trader_account_repository()
    repository_account = _repository_account(actor)
    readiness = repository.readiness_report()
    data = _safe_trader_account_readiness_data(
        actor=actor,
        repository_account=repository_account,
        readiness=readiness,
    )
    readiness_missing = [
        str(field)
        for field in readiness.get("missing_fields", [])
        if isinstance(field, str)
    ]
    missing = [*readiness_missing]
    if repository_account is None:
        missing.append("trader_account_record")
    source_type: SourceType = "repository" if repository_account is not None else "unavailable"
    return _base_response(
        endpoint=endpoint,
        data=data,
        source="trader_account_repository" if source_type == "repository" else "unavailable",
        source_type=source_type,
        timestamp=repository_account.get("updated_at") if repository_account is not None else None,
        missing_fields=[*dict.fromkeys(missing)],
        warnings=[
            "Trader account readiness is scoped to the backend-authenticated session",
            "Production trader repository, writer validation, and current smoke validation remain pending"
            if missing else "Trader account readiness has no missing fields reported",
            "No raw credentials are returned",
            "Live trading remains disabled",
            "No exchange state was read or mutated",
        ],
        mode="paper",
        trader_context=_trader_context(actor),
    )


@router.get("/account/exchange-readonly")
async def get_exchange_readonly_account(actor: UserRecord = Depends(require_auth)) -> dict[str, Any]:
    endpoint = "/api/v2/account/exchange-readonly"
    accounts = safe_exchange_accounts(actor.get("exchange_accounts"), expose_credential_ref=True)
    account = next(
        (
            item
            for item in accounts
            if str(item.get("exchange", "")).lower() == "binance"
            and item.get("read_only") is True
            and item.get("trader_id") == actor.get("trader_id")
            and item.get("paper_account_id") == actor.get("paper_account_id")
        ),
        None,
    )
    base_data = {
        "trader_id": actor.get("trader_id"),
        "paper_account_id": actor.get("paper_account_id"),
        "exchange_account_id": account.get("id") if isinstance(account, dict) else None,
        "exchange": account.get("exchange") if isinstance(account, dict) else None,
        "account_type": account.get("account_type") if isinstance(account, dict) else None,
        "account_specific": isinstance(account, dict),
        "read_only": True,
        "live_trading_enabled": False,
        "account_snapshot": None,
        "positions": [],
        "positions_count": 0,
        "trade_permission_status": "Read-only account evidence unavailable",
        "margin_mode_evidence": None,
        "leverage_evidence": None,
    }
    if not isinstance(account, dict):
        return _base_response(
            endpoint=endpoint,
            data=base_data,
            source="unavailable",
            source_type="unavailable",
            timestamp=None,
            missing_fields=["exchange_account", "credential", "account_snapshot", "positions"],
            warnings=[
                "No trader-scoped exchange account is linked",
                "No exchange state was read or mutated",
                "Live trading remains disabled",
            ],
            mode="read_only",
            trader_context=_trader_context(actor),
        )

    credential_binding = backend_readonly_credential_binding(account)
    credential_status = credential_binding.safe_status
    credentials = ReadOnlyCredentials(
        api_key=credential_binding.api_key,
        api_secret=credential_binding.api_secret,
        status="PRESENT" if credential_binding.is_configured else "MISSING",
    )
    if not credentials.is_present:
        return _base_response(
            endpoint=endpoint,
            data=base_data,
            source="secure_credential_binding",
            source_type="unavailable",
            timestamp=None,
            missing_fields=["credential", "account_snapshot", "positions", "available_balance"],
            warnings=[
                "Trader-scoped read-only credential is not configured",
                "No exchange state was read or mutated",
                "Live trading remains disabled",
            ],
            mode="read_only",
            trader_context=_trader_context(actor),
        )

    client = BinanceFuturesReadOnlyClient(
        credentials=credentials,
        base_url=os.environ.get("ALPHAFORGE_BINANCE_SIGNED_READ_BASE", BINANCE_FAPI_BASE),
        timeout_seconds=float(os.environ.get("ALPHAFORGE_BINANCE_SIGNED_READ_TIMEOUT_SECONDS", "4")),
    )
    try:
        evidence = collect_account_position_evidence(client=client)
    except (ExchangeReadError, ReadOnlyContractError, RuntimeError) as exc:
        return _base_response(
            endpoint=endpoint,
            data={
                **base_data,
                "trade_permission_status": "Read-only account source unavailable",
                "credential_status": {
                    "configured": bool(credential_status.get("configured", True)),
                    "raw_credential_value_exposed": False,
                    "live_trading_enabled": False,
                },
            },
            source="binance_signed_readonly",
            source_type="unavailable",
            timestamp=None,
            missing_fields=["account_snapshot", "positions", "available_balance"],
            warnings=[
                f"Signed read-only account source unavailable: {type(exc).__name__}",
                "No raw credential values are returned",
                "No exchange state was mutated",
                "Live trading remains disabled",
            ],
            mode="read_only",
            trader_context=_trader_context(actor),
        )

    positions = evidence.get("positions") if isinstance(evidence.get("positions"), list) else []
    snapshot = evidence.get("account_snapshot") if isinstance(evidence.get("account_snapshot"), dict) else None
    data = {
        **base_data,
        "account_snapshot": snapshot,
        "positions": positions,
        "positions_count": len(positions),
        "trade_permission_status": "Read-only account verified",
        "margin_mode_evidence": evidence.get("margin_mode_evidence"),
        "leverage_evidence": evidence.get("leverage_evidence"),
        "credential_status": {
            "configured": True,
            "raw_credential_value_exposed": False,
            "live_trading_enabled": False,
        },
    }
    missing = []
    if not snapshot:
        missing.append("account_snapshot")
    elif snapshot.get("available_balance") is None:
        missing.append("available_balance")
    if not positions:
        missing.append("positions")
    return _base_response(
        endpoint=endpoint,
        data=data,
        source="binance_usdm_signed_readonly",
        source_type="api",
        timestamp=evidence.get("account_fetch_ts") if isinstance(evidence.get("account_fetch_ts"), str) else _utc_now(),
        missing_fields=missing,
        warnings=[
            "Trader-scoped signed read-only Binance USD-M account snapshot",
            "No raw credential values are returned",
            "No order submit/cancel/leverage/margin endpoint is exposed",
            "Live trading remains disabled",
        ],
        mode="read_only",
        trader_context=_trader_context(actor),
    )


@router.get("/account/positions")
async def get_account_positions(actor: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    endpoint = "/api/v2/account/positions"
    repository_account = _repository_account(actor)
    if actor and repository_account is not None:
        positions, missing, warnings = _repository_scoped_rows(repository_account, actor, "positions")
        metrics: dict[str, Any] | None
        enrich_source: str
        position_source_parts = [TRADER_ACCOUNT_REPOSITORY_SOURCE]
        position_source_type: SourceType = "repository"
        position_timestamp = repository_account.get("updated_at")
        # Fall back to v2:paper:positions Redis when repo has no positions
        if not positions:
            try:
                _pp_raw = get_redis().get("v2:paper:positions")
                if _pp_raw:
                    _pp_list = json.loads(_pp_raw)
                    if isinstance(_pp_list, list):
                        positions = [
                            _with_actor_scope({
                                **p,
                                "quantity": p.get("net_quantity"),
                                "entry_price": p.get("avg_entry_price") or p.get("entry_price"),
                                "mark_price": p.get("last_mark_price") or p.get("mark_price"),
                                "mark_price_source": p.get("latest_price_source") or "v2:paper:positions",
                                "unrealized_pnl": p.get("unrealized_pnl"),
                                "realized_pnl": p.get("realized_pnl"),
                            }, actor)
                            for p in _pp_list
                        ]
                        if missing == ["positions"]:
                            missing = []
                        position_source_parts.append("redis:v2:paper:positions")
                        position_source_type = "redis_live"
                        position_timestamp = _utc_now()
            except Exception:
                pass
        if not positions:
            portfolio_state, portfolio_state_source, portfolio_state_source_type, portfolio_state_warnings = _runtime_portfolio_state()
            if portfolio_state and not _runtime_payload_available_to_actor(portfolio_state, actor):
                portfolio_state = {}
                missing.append("portfolio_state_scope")
                warnings.append(
                    "Paper runtime portfolio state was withheld because payload scope did not match the authenticated trader"
                )
            warnings.extend(portfolio_state_warnings)
            if portfolio_state:
                runtime_positions, runtime_missing, runtime_warnings = _runtime_portfolio_positions(portfolio_state, actor)
                if runtime_positions:
                    positions = runtime_positions
                    if missing == ["positions"]:
                        missing = []
                    if portfolio_state_source:
                        position_source_parts.append(portfolio_state_source)
                    position_source_type = portfolio_state_source_type
                    position_timestamp = _timestamp_from_payload(portfolio_state) or position_timestamp
                missing.extend(runtime_missing)
                warnings.extend(runtime_warnings)
        positions, metrics, enrich_missing, enrich_warnings, enrich_source = _enrich_position_rows_for_read_response(positions)
        missing.extend(enrich_missing)
        warnings.extend(enrich_warnings)
        if enrich_source:
            position_source_parts.append(enrich_source.lstrip(" + "))
        return _base_response(
            endpoint=endpoint,
            data={
                "positions": positions,
                "position_pricing": metrics,
                "trader_id": repository_account.get("trader_id"),
                "paper_account_id": repository_account.get("paper_account_id"),
                "account_scope": "authenticated_trader",
                "account_specific": True,
            },
            source=" + ".join(position_source_parts),
            source_type=position_source_type,
            timestamp=position_timestamp,
            missing_fields=missing,
            warnings=["Trader-scoped paper positions: repository, Redis, and paper runtime read-only sources", *warnings],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    if actor is None:
        data, warnings = await run_in_threadpool(_load_paper_activity_payload)
        positions = data.get("positions") if isinstance(data.get("positions"), list) else []
        return _base_response(
            endpoint=endpoint,
            data={
                "positions": positions,
                "trader_id": None,
                "paper_account_id": None,
                "account_scope": "public_read_only",
                "account_specific": False,
            },
            source="v2:paper:* Redis",
            source_type=_paper_redis_source_type(warnings),
            timestamp=_utc_now(),
            missing_fields=[] if positions else ["positions"],
            warnings=[
                "Public paper activity position fallback; not a live account API",
                "Rows are paper-only runtime evidence and do not prove exchange execution",
                "Live trading remains disabled",
                *warnings,
            ],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    portfolio, source = _portfolio_payload()
    if not portfolio:
        return _unavailable(
            endpoint=endpoint,
            missing_fields=["positions"],
            warning="Position source is unavailable",
            mode="paper",
        ) | {"trader_context": _trader_context(actor), "account_scope": _actor_account_scope_context(actor, None)}
    scoped_portfolio = _payload_matches_actor(portfolio, actor)
    raw_positions = portfolio.get("positions") if scoped_portfolio and isinstance(portfolio.get("positions"), list) else []
    positions = _scoped_rows(raw_positions, actor)
    position_scope_missing = scoped_portfolio and isinstance(raw_positions, list) and len(positions) != len(raw_positions)
    return _base_response(
        endpoint=endpoint,
        data={
            "positions": positions,
            "trader_id": actor.get("trader_id") if actor else None,
            "paper_account_id": actor.get("paper_account_id") if actor else None,
            "account_scope": "authenticated_trader" if actor else "public_read_only",
            "account_specific": bool(scoped_portfolio),
        },
        source=source,
        source_type="static_payload",
        timestamp=_timestamp_from_payload(portfolio),
        missing_fields=(["positions", "trader_specific_repository"] if not scoped_portfolio else [])
        + (["positions_scope"] if position_scope_missing else []),
        warnings=[
            "Paper/static payload fallback; not a live account API",
            *(
                ["Unscoped or mismatched fallback positions were withheld from authenticated trader account view"]
                if position_scope_missing else []
            ),
            "Authenticated trader-scoped positions"
            if actor and scoped_portfolio
            else _account_scope_warning(actor),
        ],
        mode="paper",
        trader_context=_trader_context(actor),
    )


@router.get("/execution/orders")
async def get_execution_orders(actor: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    repository_account = _repository_account(actor)
    if actor and repository_account is not None:
        orders, missing, warnings = _repository_scoped_rows(repository_account, actor, "orders")
        return _base_response(
            endpoint="/api/v2/execution/orders",
            data={
                "orders": orders,
                "trader_id": repository_account.get("trader_id"),
                "paper_account_id": repository_account.get("paper_account_id"),
                "account_scope": "authenticated_trader",
                "account_specific": True,
            },
            source=TRADER_ACCOUNT_REPOSITORY_SOURCE,
            source_type="repository",
            timestamp=repository_account.get("updated_at"),
            missing_fields=missing,
            warnings=["Trader-scoped local paper order repository; no exchange transport is enabled", *warnings],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    if actor is None:
        data, warnings = await run_in_threadpool(_load_paper_activity_payload)
        orders = data.get("orders") if isinstance(data.get("orders"), list) else []
        open_orders = data.get("open_orders") if isinstance(data.get("open_orders"), list) else []
        return _base_response(
            endpoint="/api/v2/execution/orders",
            data={
                "orders": orders,
                "open_orders": open_orders,
                "order_history": orders,
                "trader_id": None,
                "paper_account_id": None,
                "account_scope": "public_read_only",
                "account_specific": False,
            },
            source="v2:paper:* Redis",
            source_type=_paper_redis_source_type(warnings),
            timestamp=_utc_now(),
            missing_fields=[] if orders or open_orders else ["orders"],
            warnings=[
                "Public paper activity order fallback; no exchange transport is enabled",
                "Rows are paper-only runtime evidence and do not prove exchange execution",
                "Live trading remains disabled",
                *warnings,
            ],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    return _unavailable(
        endpoint="/api/v2/execution/orders",
        missing_fields=["orders"],
        warning=(
            "Order endpoint is read-only and not wired to a trader-specific paper order service"
            if actor else "Order endpoint is read-only; sign in is required for account-specific orders"
        ),
        mode="paper",
    ) | {"trader_context": _trader_context(actor), "account_scope": _actor_account_scope_context(actor, None)}


@router.get("/execution/executions")
async def get_execution_executions(actor: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    repository_account = _repository_account(actor)
    if actor and repository_account is not None:
        executions, missing, warnings = _repository_scoped_rows(repository_account, actor, "executions")
        return _base_response(
            endpoint="/api/v2/execution/executions",
            data={
                "executions": executions,
                "trader_id": repository_account.get("trader_id"),
                "paper_account_id": repository_account.get("paper_account_id"),
                "account_scope": "authenticated_trader",
                "account_specific": True,
            },
            source=TRADER_ACCOUNT_REPOSITORY_SOURCE,
            source_type="repository",
            timestamp=repository_account.get("updated_at"),
            missing_fields=missing,
            warnings=["Trader-scoped paper execution repository", *warnings],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    if actor is None:
        data, warnings = await run_in_threadpool(_load_paper_activity_payload)
        executions = data.get("executions") if isinstance(data.get("executions"), list) else []
        return _base_response(
            endpoint="/api/v2/execution/executions",
            data={
                "executions": executions,
                "fills": executions,
                "trader_id": None,
                "paper_account_id": None,
                "account_scope": "public_read_only",
                "account_specific": False,
            },
            source="v2:paper:* Redis",
            source_type=_paper_redis_source_type(warnings),
            timestamp=_utc_now(),
            missing_fields=[] if executions else ["executions"],
            warnings=[
                "Public paper activity execution fallback; paper fills are simulation only",
                "Rows are paper-only runtime evidence and do not prove exchange execution",
                "Live trading remains disabled",
                *warnings,
            ],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    return _unavailable(
        endpoint="/api/v2/execution/executions",
        missing_fields=["executions"],
        warning=(
            "Execution endpoint is read-only and not wired to a trader-specific paper execution service"
            if actor else "Execution endpoint is read-only; sign in is required for account-specific executions"
        ),
        mode="paper",
    ) | {"trader_context": _trader_context(actor), "account_scope": _actor_account_scope_context(actor, None)}


@router.get("/execution/audit-events")
async def get_execution_audit_events(actor: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    endpoint = "/api/v2/execution/audit-events"
    repository_account = _repository_account(actor)
    if actor and repository_account is not None:
        audit_events, missing, scope_warnings = _repository_scoped_rows(repository_account, actor, "audit_events")
        ledger_events = read_local_paper_audit_events(
            trader_id=str(repository_account.get("trader_id") or ""),
            paper_account_id=str(repository_account.get("paper_account_id") or ""),
        )
        return _base_response(
            endpoint=endpoint,
            data={
                "audit_events": audit_events,
                "audit_policy": local_paper_audit_policy_metadata(event_count=len(audit_events), events=audit_events),
                "audit_ledger": local_paper_audit_ledger_metadata(event_count=len(ledger_events), events=ledger_events),
                "audit_ledger_events": ledger_events[:100],
                "trader_id": repository_account.get("trader_id"),
                "paper_account_id": repository_account.get("paper_account_id"),
                "account_scope": "authenticated_trader",
                "account_specific": True,
            },
            source=TRADER_ACCOUNT_REPOSITORY_SOURCE,
            source_type="repository",
            timestamp=repository_account.get("updated_at"),
            missing_fields=missing if audit_events else [*missing, "audit_events"],
            warnings=[
                "Trader-scoped local paper audit event repository",
                "Audit events are local paper evidence only and do not prove exchange execution",
                "No exchange state is read or mutated",
                "Live trading remains disabled",
                *scope_warnings,
            ],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    if actor is None:
        data, warnings = await run_in_threadpool(_load_paper_activity_payload)
        audit_events = data.get("audit_events") if isinstance(data.get("audit_events"), list) else []
        return _base_response(
            endpoint=endpoint,
            data={
                "audit_events": audit_events,
                "audit_policy": local_paper_audit_policy_metadata(event_count=len(audit_events), events=audit_events),
                "audit_ledger": local_paper_audit_ledger_metadata(event_count=len(audit_events), events=audit_events),
                "audit_ledger_events": audit_events[:100],
                "trader_id": None,
                "paper_account_id": None,
                "account_scope": "public_read_only",
                "account_specific": False,
            },
            source="v2:paper:* Redis",
            source_type=_paper_redis_source_type(warnings),
            timestamp=_utc_now(),
            missing_fields=[] if audit_events else ["audit_events"],
            warnings=[
                "Public paper activity audit fallback; local paper evidence only",
                "No exchange state is read or mutated",
                "Live trading remains disabled",
                *warnings,
            ],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    return _unavailable(
        endpoint=endpoint,
        missing_fields=["audit_events"],
        warning=(
            "Audit event endpoint is read-only and requires a trader-scoped local paper repository"
            if actor else "Audit event endpoint is read-only; sign in is required for account-specific audit events"
        ),
        mode="paper",
    ) | {"trader_context": _trader_context(actor), "account_scope": _actor_account_scope_context(actor, None)}


@router.get("/signals")
async def get_signals(
    symbol: str | None = Query(default=None),
    timeframe: str = Query(default="5m"),
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    requested_symbol = _strict_market_symbol(symbol) if symbol else None
    safe_timeframe = _strict_timeframe(timeframe) or "5m"
    if symbol and requested_symbol is None:
        return _unavailable(
            endpoint="/api/v2/signals?symbol={symbol}",
            symbol=None,
            missing_fields=["symbol", "active_signal"],
            warning="Enter a valid market symbol",
            mode="paper",
        ) | {"trader_context": _trader_context(actor), "account_scope": _actor_account_scope_context(actor, None)}
    endpoint_params: dict[str, str] = {}
    if requested_symbol:
        endpoint_params["symbol"] = requested_symbol
    if safe_timeframe != "5m":
        endpoint_params["timeframe"] = safe_timeframe
    endpoint = "/api/v2/signals" + (f"?{urllib.parse.urlencode(endpoint_params)}" if endpoint_params else "")
    repository_account = _repository_account(actor)
    if actor and repository_account is not None:
        signals, missing, scope_warnings = _repository_scoped_rows(repository_account, actor, "signals")
        active_signal = signals[0] if signals else None
        symbol_warnings: list[str] = []
        if active_signal is not None and not _signal_matches_requested_symbol(active_signal, requested_symbol):
            active_signal_symbol = _signal_symbol(active_signal)
            active_signal = None
            missing = [*missing, "active_signal_symbol_match"]
            symbol_warnings.append(
                f"Active signal was withheld because symbol evidence is {'unavailable' if active_signal_symbol is None else active_signal_symbol}"
            )
        if active_signal is None:
            redis_signal = _redis_paper_signal_response(
                symbol=requested_symbol or "BTCUSDT",
                timeframe=safe_timeframe,
                endpoint=endpoint,
                actor=actor,
            )
            if redis_signal is not None:
                redis_signal["missing_fields"] = sorted(set([*redis_signal.get("missing_fields", []), *missing]))
                redis_signal["warnings"] = [
                    *redis_signal.get("warnings", []),
                    "No trader-account-specific active signal is stored in the local repository",
                    *scope_warnings,
                    *symbol_warnings,
                ]
                return redis_signal
            runtime_signal = _runtime_signal_response(
                symbol=requested_symbol or "BTCUSDT",
                timeframe=safe_timeframe,
                endpoint=endpoint,
                actor=actor,
                strict_symbol=bool(requested_symbol),
            )
            if runtime_signal is not None:
                runtime_signal["missing_fields"] = sorted(
                    set(
                        [
                            *runtime_signal.get("missing_fields", []),
                            *[
                                field
                                for field in missing
                                if field not in {"active_signal", "active_signal_symbol_match", "signals", "signals_scope"}
                            ],
                        ]
                    )
                )
                runtime_signal["warnings"] = [
                    *runtime_signal.get("warnings", []),
                    "No trader-account-specific active signal is stored in the local repository",
                    *scope_warnings,
                    *symbol_warnings,
                ]
                return runtime_signal
        return _base_response(
            endpoint=endpoint,
            data={
                "active_signal": active_signal,
                "trader_id": repository_account.get("trader_id"),
                "paper_account_id": repository_account.get("paper_account_id"),
                "account_scope": "authenticated_trader",
                "account_specific": True,
            },
            source=TRADER_ACCOUNT_REPOSITORY_SOURCE,
            source_type="repository",
            timestamp=repository_account.get("updated_at"),
            missing_fields=missing if active_signal else [*missing, "active_signal"],
            warnings=[
                "Trader-scoped signal repository",
                "No active signal is available for this trader" if active_signal is None else "Signal is scoped to authenticated trader",
                *scope_warnings,
                *symbol_warnings,
            ],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    redis_signal = _redis_paper_signal_response(
        symbol=requested_symbol or "BTCUSDT",
        timeframe=safe_timeframe,
        endpoint=endpoint,
        actor=actor,
    )
    if redis_signal is not None:
        return redis_signal
    runtime_signal = _runtime_signal_response(
        symbol=requested_symbol or "BTCUSDT",
        timeframe=safe_timeframe,
        endpoint=endpoint,
        actor=actor,
        strict_symbol=bool(requested_symbol),
    )
    if runtime_signal is not None:
        return runtime_signal
    paper, source = _paper_payload()
    signal = _active_signal()
    if not paper or not signal:
        return _unavailable(
            endpoint=endpoint,
            missing_fields=["active_signal"],
            warning="Signal source is unavailable",
            mode="paper",
        ) | {"trader_context": _trader_context(actor), "account_scope": _actor_account_scope_context(actor, None)}
    signal_warnings: list[str] = []
    if not _signal_matches_requested_symbol(signal, requested_symbol):
        signal_symbol = _signal_symbol(signal)
        signal = None
        signal_warnings.append(
            f"Active signal was withheld because symbol evidence is {'unavailable' if signal_symbol is None else signal_symbol}"
        )
    signal_scoped = _row_matches_actor(signal, actor) or _payload_matches_actor(paper, actor)
    if actor and not signal_scoped:
        return _base_response(
            endpoint=endpoint,
            data={
                "active_signal": None,
                "trader_id": actor.get("trader_id"),
                "paper_account_id": actor.get("paper_account_id"),
                "account_scope": "authenticated_trader",
                "account_specific": False,
            },
            source=source,
            source_type="static_payload",
            timestamp=_timestamp_from_payload(paper),
            missing_fields=["active_signal", "trader_specific_signal_repository"],
            warnings=[
                "Unscoped fallback signal is withheld from authenticated trader account view",
                "Trader-specific signal routing repository is pending",
                *signal_warnings,
            ],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    return _base_response(
        endpoint=endpoint,
        data={
            "active_signal": signal if signal_scoped or actor is None else None,
            "trader_id": actor.get("trader_id") if actor else None,
            "paper_account_id": actor.get("paper_account_id") if actor else None,
            "account_scope": "authenticated_trader" if actor else "public_read_only",
            "account_specific": bool(signal_scoped),
        },
        source=source,
        source_type="static_payload",
        timestamp=_timestamp_from_payload(paper),
        # Only flag truly required fields as missing; optional levels (target_2/3, stop, invalidation)
        # are not required for a valid paper signal and should not trigger the "incomplete" banner.
        missing_fields=[
            field
            for field in ("target_1",)
            if signal is None or signal.get(field) is None
        ] + (["active_signal_symbol_match"] if signal is None and requested_symbol else []),
        warnings=[
            "Signal fallback may omit trade-plan levels",
            "Authenticated trader-scoped signal"
            if actor and signal_scoped
            else "Public signal preview; sign in for account-specific signal routing",
            *signal_warnings,
        ],
        mode="paper",
        trader_context=_trader_context(actor),
    )


def _scan_redis_prefix(prefix: str, match: str) -> list[str]:
    """Safely scan Redis keys matching a pattern using SCAN (not KEYS)."""
    client = get_redis()
    if client is None:
        return []
    try:
        keys: list[str] = []
        cursor = 0
        while True:
            cursor, batch = client.scan(cursor=cursor, match=match, count=1000)
            keys.extend(batch)
            if cursor == 0:
                break
            if len(keys) > 2000:
                break
        return keys
    except Exception:
        return []


def _compact_signal_row(symbol: str, timeframe: str, payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action") or "").strip().upper()
    confidence = _float(payload.get("confidence"))
    generated_at = _timestamp_from_redis_payload(payload)
    lag = _lag_ms(generated_at)
    expected_move_bps = _float(payload.get("expected_move_after_cost_bps"))
    expected_move_pct = round(expected_move_bps / 10000.0, 6) if expected_move_bps is not None else None
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "action": action or None,
        "side": action.title() if action else None,
        "confidence": confidence,
        "live_gate": payload.get("live_gate"),
        "actionable": payload.get("paper_fill_allowed") is True,
        "risk_state": payload.get("risk_state"),
        "orchestrator_state": payload.get("orchestrator_state"),
        "paper_fill_status": payload.get("paper_fill_status"),
        "data_coverage_percent": _float(payload.get("data_coverage_percent")),
        "market_state_integrity_score": _float(payload.get("market_state_integrity_score")),
        "generated_at": generated_at,
        "age_seconds": round(lag / 1000) if lag is not None else None,
        "signal_id": payload.get("signal_id"),
        "prediction_id": payload.get("prediction_id"),
        "price_target": _float(payload.get("price_target")),
        "price_target_after_cost": _float(payload.get("price_target_after_cost")),
        "expected_move_bps": expected_move_bps,
        "expected_move_pct": expected_move_pct,
    }


def _compact_prediction_row(symbol: str, timeframe: str, payload: dict[str, Any]) -> dict[str, Any]:
    # ── Action labels + probs ──────────────────────────────────────────────
    action_labels: list[str] = payload.get("action_labels") or []
    raw_probs_list: list[float] = [_float(p) or 0.0 for p in (payload.get("action_probabilities") or [])]
    # Build dict keyed by label for frontend — fallback to indices if no labels
    action_probs_dict: dict[str, float] = {}
    if action_labels and raw_probs_list:
        action_probs_dict = {lbl: round(raw_probs_list[i], 6) for i, lbl in enumerate(action_labels) if i < len(raw_probs_list)}
    # Top/second action by probability
    sorted_probs = sorted(action_probs_dict.items(), key=lambda kv: kv[1], reverse=True)
    top_action = sorted_probs[0][0] if sorted_probs else None
    top_prob = sorted_probs[0][1] if sorted_probs else None
    second_action = sorted_probs[1][0] if len(sorted_probs) > 1 else None
    second_prob = sorted_probs[1][1] if len(sorted_probs) > 1 else None
    best_action = top_action or payload.get("action") or payload.get("top_action")

    # ── Confidence calibration ─────────────────────────────────────────────
    calib: dict[str, Any] = payload.get("confidence_calibration") or {}
    # Top-level fields take precedence over nested (some payloads flatten them)
    confidence_calibrated = _float(
        payload.get("confidence_calibrated") or calib.get("confidence_calibrated")
        or (top_prob if top_prob is not None else None)
    )
    confidence_raw = _float(payload.get("confidence_raw") or calib.get("confidence_raw"))
    temperature = _float(calib.get("temperature"))
    coverage_factor = _float(calib.get("coverage_factor"))

    # ── Timestamps ────────────────────────────────────────────────────────
    generated_at_raw = payload.get("available_at") or payload.get("created_at") or payload.get("generated_utc")
    generated_at = generated_at_raw if isinstance(generated_at_raw, str) else None
    lag = _lag_ms(generated_at)

    # ── Missing features ──────────────────────────────────────────────────
    missing_names: list[str] = payload.get("missing_feature_names") or []
    missing_feature_count = int(payload.get("missing_feature_count") or len(missing_names))

    # ── Market state integrity score ──────────────────────────────────────
    score_components: dict[str, Any] = payload.get("market_state_score_components") or {}
    market_state_integrity_score: float | None = None
    if score_components:
        numeric_scores = [v for v in score_components.values() if isinstance(v, (int, float))]
        if numeric_scores:
            market_state_integrity_score = round(sum(numeric_scores) / len(numeric_scores), 2)

    # ── Price target ──────────────────────────────────────────────────────
    expected_move_bps = _float(payload.get("expected_move_bps"))
    price_target = _float(payload.get("price_target"))
    if price_target is None and expected_move_bps is not None:
        mark_price = _float(payload.get("mark_price") or payload.get("current_price"))
        if mark_price is not None:
            price_target = round(mark_price * (1.0 + expected_move_bps / 10000.0), 2)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        # lowercase action so frontend color/label logic works without .toLowerCase()
        "action": str(best_action).lower() if best_action else None,
        "side": str(best_action).title() if best_action else None,
        # Both calibrated and raw confidence — explicit field names
        "confidence_calibrated": confidence_calibrated,
        "confidence_raw": confidence_raw,
        "temperature": temperature,
        "coverage_factor": coverage_factor,
        # Top/second action for quick display
        "top_action": top_action,
        "top_prob": top_prob,
        "second_action": second_action,
        "second_prob": second_prob,
        # Checkpoint + compute
        "checkpoint_id": payload.get("checkpoint_id"),
        "cuda_available": bool(payload.get("cuda_active")) if payload.get("cuda_active") is not None else None,
        # Coverage + missing
        "data_coverage_percent": _float(payload.get("data_coverage_percent")),
        "missing_feature_count": missing_feature_count if missing_feature_count >= 0 else None,
        "market_state_integrity_score": market_state_integrity_score,
        # Timestamps
        "generated_at": generated_at,
        "age_seconds": round(lag / 1000) if lag is not None else None,
        # Probs as dict keyed by label (list fallback for old consumers)
        "action_probs": action_probs_dict,
        "action_labels": action_labels[:10],
        # Price
        "price_target": price_target,
        "expected_move_bps": expected_move_bps,
        # Signal quality
        "masa_signal": _float(payload.get("masa_signal")),
        "policy_value": _float(payload.get("policy_value")),
        "data_coverage_pct": _float(payload.get("data_coverage_percent")),
    }


def _prediction_action(payload: dict[str, Any]) -> str | None:
    for key in ("selected_action", "action", "top_action"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    probabilities = payload.get("action_probabilities")
    if isinstance(probabilities, dict) and probabilities:
        best = max(
            ((str(action), _float(probability)) for action, probability in probabilities.items()),
            key=lambda item: item[1] if item[1] is not None else -1.0,
        )
        return best[0].strip().lower() if best[0].strip() else None
    return None


def _signal_matrix_prediction_runtime_rows(
    sym_filter: set[str] | None,
    tf_filter: set[str] | None,
) -> tuple[list[dict[str, Any]], list[str], str | None]:
    payload, _source = _read_json("operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json")
    raw_rows = payload.get("prediction_rows") if isinstance(payload, dict) else None
    if not isinstance(raw_rows, list):
        return [], [], None
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        symbol = str(raw.get("symbol") or "").strip().upper()
        timeframe = str(raw.get("timeframe") or "").strip()
        if not symbol or not timeframe:
            continue
        if sym_filter and symbol not in sym_filter:
            continue
        if tf_filter and timeframe not in tf_filter:
            continue
        action = _prediction_action(raw)
        generated_at = (
            raw.get("available_at")
            or raw.get("decision_time")
            or raw.get("generated_utc")
            or raw.get("generated_est")
        )
        generated_at = generated_at if isinstance(generated_at, str) else None
        lag = _lag_ms(generated_at)
        paper_allowed = raw.get("paper_fill_allowed")
        paper_status = raw.get("paper_fill_gate_status") or raw.get("status")
        rows.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "action": action,
            "side": action.title() if action else None,
            "confidence": _float(raw.get("confidence_calibrated") or raw.get("confidence_raw")),
            "live_gate": raw.get("live_gate") if isinstance(raw.get("live_gate"), str) else None,
            "actionable": bool(paper_allowed) if isinstance(paper_allowed, bool) else False,
            "risk_state": paper_status if isinstance(paper_status, str) else None,
            "orchestrator_state": "routed" if raw.get("routes_to_orchestrator") is True else raw.get("status"),
            "paper_fill_status": "ready" if paper_allowed is True else "gated",
            "paper_fill_gate_status": paper_status if isinstance(paper_status, str) else None,
            "data_coverage_percent": _float(raw.get("data_coverage_percent") or raw.get("data_coverage_pct")),
            "market_state_integrity_score": _float(raw.get("market_state_integrity_score")),
            "generated_at": generated_at,
            "age_seconds": round(lag / 1000) if lag is not None else None,
            "signal_id": raw.get("signal_id") if isinstance(raw.get("signal_id"), str) else None,
            "prediction_id": raw.get("prediction_id") if isinstance(raw.get("prediction_id"), str) else None,
            "price_target": _float(raw.get("price_target")),
            "price_target_after_cost": _float(raw.get("price_target_after_cost")),
            "expected_move_bps": _float(raw.get("expected_move_after_cost_bps") or raw.get("expected_move_bps")),
        })
    if not rows:
        return [], [], _timestamp_from_payload(payload)
    present = {(row["symbol"], row["timeframe"]) for row in rows}
    missing: list[str] = []
    if sym_filter and tf_filter:
        for symbol in sorted(sym_filter):
            for timeframe in ["1m", "5m", "15m", "1h", "4h"]:
                if timeframe in tf_filter and (symbol, timeframe) not in present:
                    missing.append(f"{symbol}:{timeframe}")
    return rows, missing, _timestamp_from_payload(payload)


@router.get("/signals/matrix")
async def get_signals_matrix(
    symbols: str | None = Query(default=None, description="Comma-separated symbol filter (default: all)"),
    timeframes: str | None = Query(default=None, description="Comma-separated timeframe filter (default: all)"),
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Return a matrix of all available paper signals from Redis, grouped by symbol and timeframe."""
    endpoint = "/api/v2/signals/matrix"
    allowed_tfs = {"1m", "5m", "15m", "1h", "4h"}
    tf_filter: set[str] | None = None
    if timeframes:
        tf_filter = {tf.strip() for tf in timeframes.split(",") if tf.strip() in allowed_tfs} or None
    sym_filter: set[str] | None = None
    if symbols:
        sym_filter = {s.strip().upper() for s in symbols.split(",") if s.strip()} or None

    cache_key = json.dumps(
        {
            "symbols": sorted(sym_filter) if sym_filter else None,
            "timeframes": sorted(tf_filter) if tf_filter else None,
        },
        sort_keys=True,
    )
    cache_hit = False
    matrix_source = "Redis signal publisher (matrix direct lookup/cache)" if sym_filter and tf_filter else "Redis signal publisher (matrix scan/cache)"
    matrix_source_type: SourceType = "repository"
    matrix_timestamp: str | None = _utc_now()
    if SIGNALS_MATRIX_CACHE_TTL_SECONDS > 0:
        with SIGNALS_MATRIX_CACHE_LOCK:
            cached = SIGNALS_MATRIX_CACHE.get(cache_key)
            if cached is not None and time.monotonic() - cached[0] <= SIGNALS_MATRIX_CACHE_TTL_SECONDS:
                cached_entry = cached[1]
                cached_data = cached_entry.get("data") if isinstance(cached_entry.get("data"), dict) else cached_entry
                rows = list(cached_data.get("rows", []))
                missing_symbols = list(cached_data.get("missing", []))
                cached_source = cached_entry.get("source")
                cached_source_type = cached_entry.get("source_type")
                cached_timestamp = cached_entry.get("timestamp")
                if isinstance(cached_source, str):
                    matrix_source = cached_source
                if cached_source_type in {"api", "repository", "redis_live", "static_payload", "unavailable"}:
                    matrix_source_type = cached_source_type
                if isinstance(cached_timestamp, str):
                    matrix_timestamp = cached_timestamp
                cache_hit = True
            else:
                rows = []
                missing_symbols = []
    else:
        rows = []
        missing_symbols = []

    if not cache_hit and sym_filter and tf_filter:
        keys = [
            f"v2:signals:paper:{sym}:{tf}"
            for sym in sorted(sym_filter)
            for tf in ["1m", "5m", "15m", "1h", "4h"]
            if tf in tf_filter
        ]
    elif not cache_hit:
        keys = _scan_redis_prefix("v2:signals:paper:", "v2:signals:paper:*")
    else:
        keys = []
    client = get_redis()

    for key in keys:
        parts = key.split(":")
        if len(parts) != 5:
            continue
        sym = parts[3]
        tf = parts[4]
        if sym_filter and sym not in sym_filter:
            continue
        if tf_filter and tf not in tf_filter:
            continue
        if tf not in allowed_tfs:
            continue
        try:
            raw = client.get(key) if client else None
            if raw is None:
                missing_symbols.append(f"{sym}:{tf}")
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            payload = json.loads(str(raw))
            if not isinstance(payload, dict):
                continue
            rows.append(_compact_signal_row(sym, tf, payload))
        except Exception:
            continue

    if not cache_hit and not rows:
        fallback_rows, fallback_missing, fallback_timestamp = _signal_matrix_prediction_runtime_rows(sym_filter, tf_filter)
        if fallback_rows:
            rows = fallback_rows
            missing_symbols = fallback_missing
            matrix_source = "Runtime prediction signal matrix fallback"
            matrix_source_type = "static_payload"
            matrix_timestamp = fallback_timestamp

    all_syms = sorted({r["symbol"] for r in rows})
    all_tfs = [tf for tf in ["1m", "5m", "15m", "1h", "4h"] if any(r["timeframe"] == tf for r in rows)]
    data = {
        "rows": rows,
        "count": len(rows),
        "symbols": all_syms,
        "symbol_count": len(all_syms),
        "timeframes": all_tfs,
        "missing": missing_symbols,
    }
    if not cache_hit and SIGNALS_MATRIX_CACHE_TTL_SECONDS > 0:
        with SIGNALS_MATRIX_CACHE_LOCK:
            SIGNALS_MATRIX_CACHE[cache_key] = (
                time.monotonic(),
                {
                    "data": data,
                    "source": matrix_source,
                    "source_type": matrix_source_type,
                    "timestamp": matrix_timestamp,
                },
            )
    return _base_response(
        endpoint=endpoint,
        data=data,
        source=matrix_source,
        source_type=matrix_source_type,
        timestamp=matrix_timestamp,
        missing_fields=missing_symbols[:10],
        warnings=[
            "Matrix scan may have up to 2s lag vs individual signal queries",
            "Served from short-lived matrix cache"
            if cache_hit
            else "Matrix refreshed from runtime prediction fallback"
            if matrix_source_type == "static_payload"
            else "Matrix refreshed from Redis",
            "Exchange execution remains operator-gated",
        ],
        mode="paper",
        trader_context=_trader_context(actor),
    )


@router.get("/predictions/matrix")
async def get_predictions_matrix(
    symbols: str | None = Query(default=None),
    timeframes: str | None = Query(default=None),
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Return a matrix of all available trainer predictions from Redis."""
    endpoint = "/api/v2/predictions/matrix"
    allowed_tfs = {"1m", "5m", "15m", "1h", "4h"}
    tf_filter: set[str] | None = None
    if timeframes:
        tf_filter = {tf.strip() for tf in timeframes.split(",") if tf.strip() in allowed_tfs} or None
    sym_filter: set[str] | None = None
    if symbols:
        sym_filter = {s.strip().upper() for s in symbols.split(",") if s.strip()} or None

    cache_key = json.dumps(
        {
            "symbols": sorted(sym_filter) if sym_filter else None,
            "timeframes": sorted(tf_filter) if tf_filter else None,
        },
        sort_keys=True,
    )
    cache_hit = False
    matrix_source = (
        "Redis trainer prediction publisher (matrix direct lookup/cache)"
        if sym_filter and tf_filter
        else "Redis trainer prediction publisher (matrix scan/cache)"
    )
    matrix_source_type: SourceType = "repository"
    matrix_timestamp: str | None = _utc_now()
    rows: list[dict[str, Any]] = []
    missing_symbols: list[str] = []
    if PREDICTIONS_MATRIX_CACHE_TTL_SECONDS > 0:
        with PREDICTIONS_MATRIX_CACHE_LOCK:
            cached = PREDICTIONS_MATRIX_CACHE.get(cache_key)
            if cached is not None and time.monotonic() - cached[0] <= PREDICTIONS_MATRIX_CACHE_TTL_SECONDS:
                cached_entry = cached[1]
                cached_data = cached_entry.get("data") if isinstance(cached_entry.get("data"), dict) else cached_entry
                rows = list(cached_data.get("rows", []))
                missing_symbols = list(cached_data.get("missing", []))
                cached_source = cached_entry.get("source")
                cached_source_type = cached_entry.get("source_type")
                cached_timestamp = cached_entry.get("timestamp")
                if isinstance(cached_source, str):
                    matrix_source = cached_source
                if cached_source_type in {"api", "repository", "redis_live", "static_payload", "unavailable"}:
                    matrix_source_type = cached_source_type
                if isinstance(cached_timestamp, str):
                    matrix_timestamp = cached_timestamp
                cache_hit = True

    if not cache_hit and sym_filter and tf_filter:
        keys = [
            f"v2:prediction:{sym}:{tf}"
            for sym in sorted(sym_filter)
            for tf in ["1m", "5m", "15m", "1h", "4h"]
            if tf in tf_filter
        ]
    elif not cache_hit:
        keys = _scan_redis_prefix("v2:prediction:", "v2:prediction:*")
    else:
        keys = []
    client = get_redis()

    for key in sorted(keys):
        parts = key.split(":")
        if len(parts) != 4:
            continue
        sym = parts[2]
        tf = parts[3]
        if sym_filter and sym not in sym_filter:
            continue
        if tf_filter and tf not in tf_filter:
            continue
        if tf not in allowed_tfs:
            continue
        try:
            raw = client.get(key) if client else None
            if raw is None:
                if sym_filter and tf_filter:
                    missing_symbols.append(f"{sym}:{tf}")
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            payload = json.loads(str(raw))
            if not isinstance(payload, dict):
                continue
            rows.append(_compact_prediction_row(sym, tf, payload))
        except Exception:
            continue

    all_syms = sorted({r["symbol"] for r in rows})
    all_tfs = [tf for tf in ["1m", "5m", "15m", "1h", "4h"] if any(r["timeframe"] == tf for r in rows)]
    data = {
        "rows": rows,
        "count": len(rows),
        "symbols": all_syms,
        "symbol_count": len(all_syms),
        "timeframes": all_tfs,
        "missing": missing_symbols,
    }
    if not cache_hit and PREDICTIONS_MATRIX_CACHE_TTL_SECONDS > 0:
        with PREDICTIONS_MATRIX_CACHE_LOCK:
            PREDICTIONS_MATRIX_CACHE[cache_key] = (
                time.monotonic(),
                {
                    "data": data,
                    "source": matrix_source,
                    "source_type": matrix_source_type,
                    "timestamp": matrix_timestamp,
                },
            )
    return _base_response(
        endpoint=endpoint,
        data=data,
        source=matrix_source,
        source_type=matrix_source_type,
        timestamp=matrix_timestamp,
        missing_fields=missing_symbols[:10],
        warnings=[
            "Prediction matrix from trainer Redis stream",
            "Served from short-lived matrix cache" if cache_hit else "Prediction matrix refreshed from Redis",
            "Exchange execution remains operator-gated",
        ],
        mode="paper",
        trader_context=_trader_context(actor),
    )


_PREDICTION_STALE_THRESHOLD_S = 300  # 5 minutes
_SIGNAL_STALE_THRESHOLD_S = 300


@router.get("/predictions/status")
async def get_predictions_status() -> dict[str, Any]:
    """Lightweight prediction grid status: counts, staleness, direction breakdown."""
    keys = _scan_redis_prefix("v2:prediction:", "v2:prediction:*")
    client = get_redis()
    total = 0
    stale = 0
    current = 0
    direction_counts: dict[str, int] = {"short": 0, "long": 0, "hold": 0, "unknown": 0}
    symbols: set[str] = set()
    timeframes: set[str] = set()
    latest_generated: str | None = None
    allowed_tfs = {"1m", "5m", "15m", "1h", "4h"}

    for key in sorted(keys):
        parts = key.split(":")
        if len(parts) != 4:
            continue
        sym, tf = parts[2], parts[3]
        if tf not in allowed_tfs:
            continue
        try:
            raw = client.get(key) if client else None
            if raw is None:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            payload = json.loads(str(raw))
            if not isinstance(payload, dict):
                continue
        except Exception:
            continue

        total += 1
        symbols.add(sym)
        timeframes.add(tf)

        generated_at = _timestamp_from_redis_payload(payload)
        lag = _lag_ms(generated_at)
        if lag is None or lag > _PREDICTION_STALE_THRESHOLD_S * 1000:
            stale += 1
        else:
            current += 1

        if generated_at and (latest_generated is None or generated_at > latest_generated):
            latest_generated = generated_at

        action = str(payload.get("selected_action") or payload.get("action") or "").strip().lower()
        if action in ("short", "sell"):
            direction_counts["short"] += 1
        elif action in ("long", "buy"):
            direction_counts["long"] += 1
        elif action in ("hold", "flat"):
            direction_counts["hold"] += 1
        else:
            direction_counts["unknown"] += 1

    return {
        "endpoint": "/api/v2/predictions/status",
        "total_rows": total,
        "stale_rows": stale,
        "current_rows": current,
        "stale_threshold_s": _PREDICTION_STALE_THRESHOLD_S,
        "symbol_count": len(symbols),
        "timeframe_count": len(timeframes),
        "direction_breakdown": direction_counts,
        "latest_generated": latest_generated,
        "live_gate": "blocked_human_only",
        "source": "redis:v2:prediction:*",
        "mode": "paper",
        "timestamp": _utc_now(),
    }


@router.get("/signals/status")
async def get_signals_status() -> dict[str, Any]:
    """Lightweight signal grid status: counts, staleness, direction breakdown."""
    keys = _scan_redis_prefix("v2:signals:paper:", "v2:signals:paper:*")
    client = get_redis()
    total = 0
    stale = 0
    current = 0
    actionable = 0
    direction_counts: dict[str, int] = {"short": 0, "long": 0, "hold": 0, "unknown": 0}
    symbols: set[str] = set()
    timeframes: set[str] = set()
    latest_generated: str | None = None
    allowed_tfs = {"1m", "5m", "15m", "1h", "4h"}

    for key in sorted(keys):
        parts = key.split(":")
        if len(parts) != 5:
            continue
        sym, tf = parts[3], parts[4]
        if tf not in allowed_tfs:
            continue
        try:
            raw = client.get(key) if client else None
            if raw is None:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            payload = json.loads(str(raw))
            if not isinstance(payload, dict):
                continue
        except Exception:
            continue

        total += 1
        symbols.add(sym)
        timeframes.add(tf)

        generated_at = _timestamp_from_redis_payload(payload)
        lag = _lag_ms(generated_at)
        if lag is None or lag > _SIGNAL_STALE_THRESHOLD_S * 1000:
            stale += 1
        else:
            current += 1

        if generated_at and (latest_generated is None or generated_at > latest_generated):
            latest_generated = generated_at

        if payload.get("paper_fill_allowed") is True:
            actionable += 1

        action = str(payload.get("action") or "").strip().upper()
        if action in ("SHORT", "SELL"):
            direction_counts["short"] += 1
        elif action in ("LONG", "BUY"):
            direction_counts["long"] += 1
        elif action in ("HOLD", "FLAT"):
            direction_counts["hold"] += 1
        else:
            direction_counts["unknown"] += 1

    return {
        "endpoint": "/api/v2/signals/status",
        "total_rows": total,
        "stale_rows": stale,
        "current_rows": current,
        "actionable_rows": actionable,
        "stale_threshold_s": _SIGNAL_STALE_THRESHOLD_S,
        "symbol_count": len(symbols),
        "timeframe_count": len(timeframes),
        "direction_breakdown": direction_counts,
        "latest_generated": latest_generated,
        "live_gate": "blocked_human_only",
        "source": "redis:v2:signals:paper:*",
        "mode": "paper",
        "timestamp": _utc_now(),
    }


_LIQ_HEATMAP_ALLOWED_TFS = ("1m", "5m", "15m", "1h", "4h")
_LIQ_HEATMAP_DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _parse_liq_level_payload(raw: bytes | str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _liq_heatmap_row(sym: str, tf: str, p: dict[str, Any]) -> dict[str, Any]:
    def _f(k: str) -> float | None:
        v = p.get(k)
        return float(v) if v is not None else None

    long_s = _f("liquidation_long_strength") or 0.0
    short_s = _f("liquidation_short_strength") or 0.0
    total_s = long_s + short_s
    volume = _f("liquidation_volume") or 0.0
    cascade = _f("liquidation_cascade_risk")
    pressure = _f("liquidation_pressure_direction")
    stale_ms = _f("liquidation_staleness_ms")
    stale_flag = bool(p.get("liquidation_is_stale") or p.get("liquidation_no_events"))
    stale_age_s = round(stale_ms / 1000, 1) if stale_ms is not None else None
    long_pct = round(long_s / total_s * 100, 1) if total_s > 0 else 50.0
    short_pct = round(short_s / total_s * 100, 1) if total_s > 0 else 50.0

    return {
        "symbol": sym,
        "timeframe": tf,
        "long_strength": round(long_s, 2),
        "short_strength": round(short_s, 2),
        "total_strength": round(total_s, 2),
        "long_pct": long_pct,
        "short_pct": short_pct,
        "volume": round(volume, 2),
        "cascade_risk": cascade,
        "pressure_direction": pressure,
        "current_price": _f("liquidation_current_price"),
        "sweep_target_long": _f("liquidation_sweep_target_long"),
        "sweep_target_short": _f("liquidation_sweep_target_short"),
        "sweep_long_dist_bps": _f("liquidation_sweep_target_long_distance_bps"),
        "sweep_short_dist_bps": _f("liquidation_sweep_target_short_distance_bps"),
        "nearest_above": _f("nearest_liquidation_level_above"),
        "nearest_below": _f("nearest_liquidation_level_below"),
        "zones_long": int(p.get("liquidation_zones_count_long") or 0),
        "zones_short": int(p.get("liquidation_zones_count_short") or 0),
        "levels_long": int(p.get("liquidation_levels_count_long") or 0),
        "levels_short": int(p.get("liquidation_levels_count_short") or 0),
        "count_5m": int(p.get("liquidation_count_5m") or 0),
        "last_liq_bps": _f("last_liq_bps_proxy"),
        "long_distance_pct": _f("liquidation_long_distance_pct"),
        "short_distance_pct": _f("liquidation_short_distance_pct"),
        "stale": stale_flag,
        "stale_age_s": stale_age_s,
        "source": p.get("liquidation_source") or "redis",
        "updated_ts": _f("liquidation_updated_ts"),
    }


def _liq_runtime_current_price(
    long_level: float | None,
    long_distance_pct: float | None,
    short_level: float | None,
    short_distance_pct: float | None,
) -> float | None:
    candidates: list[float] = []
    if long_level is not None and long_level > 0 and long_distance_pct is not None:
        divisor = 1 - (abs(long_distance_pct) / 100)
        if divisor > 0:
            candidates.append(long_level / divisor)
    if short_level is not None and short_level > 0 and short_distance_pct is not None:
        divisor = 1 + (abs(short_distance_pct) / 100)
        if divisor > 0:
            candidates.append(short_level / divisor)
    if not candidates:
        return None
    return round(sum(candidates) / len(candidates), 8)


def _liq_heatmap_runtime_status_fallback_rows(
    sym_filter: set[str] | None,
    tf_filter: set[str] | None,
) -> tuple[list[dict[str, Any]], str | None, str | None, list[str]]:
    payload, source = _read_json("operator_runtime/v2_liquidation_runtime_status/latest/v2_liquidation_runtime_status.json")
    if not isinstance(payload, dict):
        return [], None, None, ["Liquidation runtime status fallback is unavailable"]
    if sym_filter and "BTCUSDT" not in sym_filter:
        return [], source, _timestamp_from_payload(payload), []
    tf = "5m"
    if tf_filter and tf not in tf_filter:
        return [], source, _timestamp_from_payload(payload), []

    long_level = _float(payload.get("btc_long_level"))
    short_level = _float(payload.get("btc_short_level"))
    long_distance_pct = _float(payload.get("btc_long_distance_pct"))
    short_distance_pct = _float(payload.get("btc_short_distance_pct"))
    if long_level is None and short_level is None:
        return [], source, _timestamp_from_payload(payload), ["BTC liquidation levels missing from runtime status fallback"]

    timestamp = _timestamp_from_payload(payload)
    lag = _lag_ms(timestamp)
    stale = lag is None or lag > 180_000
    updated_seconds = _epoch_seconds_from_iso(timestamp)
    current_price = _liq_runtime_current_price(
        long_level,
        long_distance_pct,
        short_level,
        short_distance_pct,
    )
    row = {
        "symbol": "BTCUSDT",
        "timeframe": tf,
        "long_strength": 0.0,
        "short_strength": 0.0,
        "total_strength": 0.0,
        "long_pct": 50.0,
        "short_pct": 50.0,
        "volume": 0.0,
        "cascade_risk": None,
        "pressure_direction": None,
        "current_price": current_price,
        "sweep_target_long": long_level,
        "sweep_target_short": short_level,
        "sweep_long_dist_bps": round((long_distance_pct or 0.0) * 100, 4) if long_distance_pct is not None else None,
        "sweep_short_dist_bps": round((short_distance_pct or 0.0) * 100, 4) if short_distance_pct is not None else None,
        "nearest_above": short_level,
        "nearest_below": long_level,
        "zones_long": 1 if long_level is not None else 0,
        "zones_short": 1 if short_level is not None else 0,
        "levels_long": 1 if long_level is not None else 0,
        "levels_short": 1 if short_level is not None else 0,
        "count_5m": int(_float(payload.get("liquidation_events_xlen")) or 0),
        "last_liq_bps": None,
        "long_distance_pct": long_distance_pct,
        "short_distance_pct": short_distance_pct,
        "stale": stale,
        "stale_age_s": round(lag / 1000, 1) if lag is not None else None,
        "source": source,
        "updated_ts": (updated_seconds * 1000) if updated_seconds is not None else None,
    }
    return [row], source, timestamp, ["Redis liquidation level keys unavailable; using current runtime-status fallback"]


@router.get("/liquidation/levels-heatmap")
async def get_liquidation_levels_heatmap(
    symbols: str | None = Query(default=None, description="Comma-separated symbol filter (default: all)"),
    timeframes: str | None = Query(default=None, description="Comma-separated timeframe filter (default: all)"),
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Return liquidation levels heatmap across all symbols and TFs from Redis.

    Primary data source: Redis v2:liquidations:levels:{symbol}:{tf}.
    Suitable for WebSocket streaming via /api/v2/ws/resource with HTTP fallback.
    """
    endpoint = "/api/v2/liquidation/levels-heatmap"
    tf_filter: set[str] | None = None
    if timeframes:
        tf_filter = {tf.strip() for tf in timeframes.split(",") if tf.strip() in _LIQ_HEATMAP_ALLOWED_TFS} or None
    sym_filter: set[str] | None = None
    if symbols:
        sym_filter = {s.strip().upper() for s in symbols.split(",") if s.strip()} or None

    keys = _scan_redis_prefix("v2:liquidations:levels:", "v2:liquidations:levels:*")
    client = get_redis()
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    source = "Redis v2:liquidations:levels:{symbol}:{tf} (heatmap scan)"
    source_type = "repository"
    response_timestamp = _utc_now()
    response_warnings = [
        "Heatmap scan may lag up to 2s vs individual queries",
        "Exchange execution remains operator-gated",
    ]

    filtered_keys: list[tuple[str, str, str]] = []
    for key in sorted(keys):
        parts = key.split(":")
        if len(parts) != 5:
            continue
        sym, tf = parts[3], parts[4]
        if sym_filter and sym not in sym_filter:
            continue
        if tf_filter and tf not in tf_filter:
            continue
        if tf not in _LIQ_HEATMAP_ALLOWED_TFS:
            continue
        filtered_keys.append((key, sym, tf))

    raw_values: list[Any]
    if client and filtered_keys:
        try:
            raw_values = list(client.mget([key for key, _, _ in filtered_keys]))
        except Exception:
            raw_values = [None] * len(filtered_keys)
    else:
        raw_values = []

    for (key, sym, tf), raw in zip(filtered_keys, raw_values):
        try:
            p = _parse_liq_level_payload(raw)
            if p is None:
                missing.append(f"{sym}:{tf}")
                continue
            rows.append(_liq_heatmap_row(sym, tf, p))
        except Exception:
            missing.append(f"{sym}:{tf}")

    if not rows:
        fallback_rows, fallback_source, fallback_timestamp, fallback_warnings = (
            _liq_heatmap_runtime_status_fallback_rows(sym_filter, tf_filter)
        )
        if fallback_rows:
            rows = fallback_rows
            source = fallback_source or FALLBACK_RUNTIME_SOURCE
            source_type = "static_payload"
            response_timestamp = fallback_timestamp or response_timestamp
            response_warnings = [
                *fallback_warnings,
                "Fallback exposes only fields present in the current runtime-status artifact",
                "Exchange execution remains operator-gated",
            ]
        elif fallback_warnings:
            response_warnings.extend(fallback_warnings)

    # Aggregate per symbol (sum volume across TFs for ranking)
    vol_by_sym: dict[str, float] = {}
    for r in rows:
        vol_by_sym[r["symbol"]] = vol_by_sym.get(r["symbol"], 0.0) + (r["volume"] or 0.0)

    top_by_volume = sorted(vol_by_sym, key=lambda s: vol_by_sym[s], reverse=True)
    top5 = top_by_volume[:5]
    # Default pinned symbols: BTC/ETH/SOL + top 2 not already in the list
    pinned_defaults = list(_LIQ_HEATMAP_DEFAULT_SYMBOLS)
    for s in top5:
        if s not in pinned_defaults:
            pinned_defaults.append(s)
        if len(pinned_defaults) >= 5:
            break

    all_syms = sorted(vol_by_sym.keys())
    all_tfs = [tf for tf in _LIQ_HEATMAP_ALLOWED_TFS if any(r["timeframe"] == tf for r in rows)]
    stale_count = sum(1 for r in rows if r.get("stale"))
    current_count = len(rows) - stale_count

    return _base_response(
        endpoint=endpoint,
        data={
            "rows": rows,
            "count": len(rows),
            "symbols": all_syms,
            "symbol_count": len(all_syms),
            "timeframes": all_tfs,
            "top_by_volume": top5,
            "pinned_defaults": pinned_defaults,
            "volume_by_symbol": {s: round(v, 2) for s, v in sorted(vol_by_sym.items(), key=lambda x: -x[1])},
            "stale_count": stale_count,
            "current_count": current_count,
            "missing": missing[:20],
        },
        source=source,
        source_type=source_type,
        timestamp=response_timestamp,
        missing_fields=missing[:5] if rows else ["liquidation_levels"],
        warnings=response_warnings,
        mode="read_only",
        trader_context=_trader_context(actor),
    )


class OrderPreviewRequest(BaseModel):
    symbol: str = Field(min_length=1)
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit", "stop"]
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    reduce_only: bool | None = None
    take_profit: float | None = None
    stop_loss: float | None = None
    trader_id: str | None = None
    paper_account_id: str | None = None
    mode: str = "paper"


class PaperFillRequest(BaseModel):
    price: float | None = None
    quantity: float | None = None
    reason: str = "Manual paper fill"


def _production_environment() -> bool:
    return os.environ.get("ALPHAFORGE_ENV", "").strip().lower() in {"prod", "production"}


def _production_paper_actions_disabled() -> bool:
    """Production paper submit/cancel/fill stays disabled until verified service approval.

    This is intentionally stricter than local/dev paper repository behavior. It
    does not affect preview math and does not create any live/exchange path.
    """
    return _production_environment()


def _production_paper_fill_writer_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_PRODUCTION_PAPER_FILL_WRITER_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def _production_paper_fill_writer_evidence() -> dict[str, Any]:
    path = _production_paper_fill_writer_artifact_path()
    if path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "warning": "Production paper fill-writer artifact is not configured",
            "payload": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": f"Production paper fill-writer artifact could not be read: {exc}",
            "payload": {},
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": "Production paper fill-writer artifact must be a JSON object",
            "payload": {},
        }
    status_value = str(
        payload.get("production_paper_fill_writer_status")
        or payload.get("paper_fill_writer_status")
        or payload.get("status")
        or ""
    ).strip().lower()
    required_true = (
        "paper_fill_writer_validated",
        "paper_only_fill_writer",
        "trader_scope_enforced",
        "paper_account_scope_enforced",
        "backend_owned_order_ids",
        "idempotency_enforced",
        "durable_repository_verified",
        "audit_event_linked",
    )
    required_false = (
        "contains_credentials",
        "live_transport_enabled",
        "exchange_mutation_enabled",
        "real_order_submitted",
        "real_order_cancelled",
        "leverage_mutation_enabled",
        "margin_mutation_enabled",
        "live_gate_mutation_enabled",
    )
    valid = (
        status_value in {"pass", "passed", "ok", "verified"}
        and all(payload.get(field) is True for field in required_true)
        and all(payload.get(field) is False for field in required_false)
        and not payload.get("missing_fields")
    )
    return {
        "configured": True,
        "valid": valid,
        "status": "verified" if valid else "invalid",
        "warning": None
        if valid
        else "Production paper fill-writer artifact must prove paper-only fill validation, scope enforcement, idempotency, durable repository, audit linkage, and no live/exchange mutation",
        "payload": payload,
    }


def _paper_execution_policy() -> dict[str, Any]:
    production_environment = _production_environment()
    fill_writer_evidence = _production_paper_fill_writer_evidence()
    fill_writer_payload = (
        fill_writer_evidence["payload"] if isinstance(fill_writer_evidence.get("payload"), dict) else {}
    )
    fill_writer_missing_fields = ["production_paper_fill_writer_current_validation"]
    if not fill_writer_evidence["valid"]:
        fill_writer_missing_fields.append("production_paper_fill_writer_artifact")
    artifact_missing_fields = (
        fill_writer_payload.get("missing_fields")
        if isinstance(fill_writer_payload.get("missing_fields"), list)
        else []
    )
    for field in artifact_missing_fields:
        if isinstance(field, str) and field not in fill_writer_missing_fields:
            fill_writer_missing_fields.append(field)
    fill_writer_warnings = [
        "Production paper fill-writer evidence is partial until current validation and review pass"
    ]
    if fill_writer_evidence.get("warning"):
        fill_writer_warnings.append(str(fill_writer_evidence["warning"]))
    for warning in (
        fill_writer_payload.get("warnings")
        if isinstance(fill_writer_payload.get("warnings"), list)
        else []
    ):
        fill_writer_warnings.append(str(warning))
    return {
        "status": "partial_local_policy",
        "mode": "paper",
        "account_scope": "authenticated_trader_required",
        "submit_policy": "authenticated_trader_local_paper_staging",
        "fill_policy": "no_automatic_fill",
        "manual_fill_policy": "authenticated_trader_local_paper_fill_only",
        "execution_policy": "explicit_local_paper_fill_writer_only",
        "cancel_policy": "local_repository_cancel_only",
        "local_paper_repository_enabled": True,
        "local_paper_staging_enabled": True,
        "local_paper_cancel_enabled": True,
        "local_manual_fill_enabled": True,
        "auto_fill_enabled": False,
        "verified_production_paper_submit_cancel": False,
        "verified_paper_execution_service": False,
        "production_environment": production_environment,
        "production_paper_actions_enabled": False,
        "production_paper_actions_status": "disabled_pending_verified_paper_execution_service"
        if production_environment
        else "local_repository_only_pending_production_validation",
        "local_paper_actions_allowed_in_production": False,
        "production_requires_verified_paper_execution_service": True,
        "product_decision": "keep_production_paper_submit_cancel_fill_disabled_until_verified_service",
        "production_validation_status": "pending",
        "production_paper_fill_writer_status": "artifact_present_pending_current_validation"
        if fill_writer_evidence["valid"]
        else "missing",
        "production_paper_fill_writer_artifact_configured": bool(fill_writer_evidence["configured"]),
        "production_paper_fill_writer_artifact_valid": bool(fill_writer_evidence["valid"]),
        "production_paper_fill_writer_artifact_status": str(fill_writer_evidence["status"]),
        "paper_fill_writer_validated": fill_writer_payload.get("paper_fill_writer_validated") is True,
        "paper_only_fill_writer": fill_writer_payload.get("paper_only_fill_writer") is True,
        "paper_fill_writer_trader_scope_enforced": fill_writer_payload.get("trader_scope_enforced") is True,
        "paper_fill_writer_paper_account_scope_enforced": fill_writer_payload.get("paper_account_scope_enforced") is True,
        "paper_fill_writer_backend_owned_order_ids": fill_writer_payload.get("backend_owned_order_ids") is True,
        "paper_fill_writer_idempotency_enforced": fill_writer_payload.get("idempotency_enforced") is True,
        "paper_fill_writer_durable_repository_verified": fill_writer_payload.get("durable_repository_verified") is True,
        "paper_fill_writer_audit_event_linked": fill_writer_payload.get("audit_event_linked") is True,
        "durable_audit_policy_status": "partial_local_hash_chain_and_jsonl_only",
        "durable_repository_enabled": False,
        "requires_authenticated_trader_scope": True,
        "requires_backend_owned_order_id": True,
        "live_transport_enabled": False,
        "exchange_mutation_enabled": False,
        "real_order_submission_enabled": False,
        "real_order_cancel_enabled": False,
        "position_risk_mutation_enabled": False,
        "collateral_mode_mutation_enabled": False,
        "live_gate_mutation_enabled": False,
        "contains_exchange_credentials": False,
        "missing_fields": [
            "production_paper_submit_cancel_validation",
            "production_paper_fill_writer",
            "verified_paper_execution_service",
            "durable_paper_audit_policy",
            "production_trader_account_repository",
            *fill_writer_missing_fields,
        ],
        "warnings": [
            "Local paper repository policy only",
            "Production paper submit/cancel/fill validation is pending",
            "Production paper actions remain disabled until a verified paper execution service is approved",
            *fill_writer_warnings,
            "No live exchange order path is enabled",
        ],
    }


def _production_paper_action_blocked_response(
    *,
    endpoint: str,
    actor: UserRecord,
    action: str,
    symbol: str | None = None,
    include_execution: bool = False,
) -> dict[str, Any]:
    label = {
        "submit": "Paper order submit",
        "fill": "Paper fill",
        "cancel": "Paper cancel",
    }.get(action, "Paper action")
    data: dict[str, Any] = {
        "accepted": False,
        "order": None,
        "reason": "production_paper_actions_disabled",
        "friendly_reason": f"{label} disabled until production paper execution is verified",
        "trader_id": actor.get("trader_id"),
        "paper_account_id": actor.get("paper_account_id"),
        "paper_execution_policy": _paper_execution_policy(),
    }
    if include_execution:
        data["execution"] = None
    return _base_response(
        endpoint=endpoint,
        data=data,
        source="unavailable",
        source_type="unavailable",
        timestamp=None,
        missing_fields=[
            "production_paper_submit_cancel_validation",
            "production_paper_fill_writer",
            "verified_paper_execution_service",
            "durable_paper_audit_policy",
        ],
        warnings=[
            f"{label} rejected because production paper actions are disabled until verified",
            "No exchange state was read or mutated",
            "No live order transport is enabled",
            "Live trading remains disabled",
        ],
        symbol=symbol,
        mode="paper",
        trader_context=_trader_context(actor),
    )


def _paper_repository_blocked_response(
    *,
    endpoint: str,
    actor: UserRecord,
    action: str,
    symbol: str | None = None,
    include_execution: bool = False,
    detail: str = "paper_repository_unavailable",
) -> dict[str, Any]:
    label = {
        "submit": "Paper order submit",
        "fill": "Paper fill",
        "cancel": "Paper cancel",
    }.get(action, "Paper action")
    data: dict[str, Any] = {
        "accepted": False,
        "order": None,
        "reason": "paper_repository_unavailable",
        "friendly_reason": f"{label} unavailable",
        "trader_id": actor.get("trader_id"),
        "paper_account_id": actor.get("paper_account_id"),
        "paper_execution_policy": _paper_execution_policy(),
    }
    if include_execution:
        data["execution"] = None
    return _base_response(
        endpoint=endpoint,
        data=data,
        source="unavailable",
        source_type="unavailable",
        timestamp=None,
        missing_fields=["production_trader_account_repository", "paper_repository"],
        warnings=[
            f"{label} rejected because the local paper repository is unavailable for this environment",
            detail,
            "No exchange state was read or mutated",
            "Live trading remains disabled",
        ],
        symbol=symbol,
        mode="paper",
        trader_context=_trader_context(actor),
    )


def _paper_action_scope_blocked_response(
    *,
    endpoint: str,
    actor: UserRecord,
    action: str,
    request_trader_id: str | None,
    request_paper_account_id: str | None,
    symbol: str | None = None,
) -> dict[str, Any]:
    label = {
        "submit": "Paper order submit",
        "fill": "Paper fill",
        "cancel": "Paper cancel",
    }.get(action, "Paper action")
    missing_fields: list[str] = []
    warnings = [
        f"{label} rejected because the request did not match the authenticated trader scope",
        "Backend session remains authoritative for trader and paper-account scope",
        "No exchange state was read or mutated",
        "Live trading remains disabled",
    ]
    actor_trader_id = actor.get("trader_id")
    actor_paper_account_id = actor.get("paper_account_id")
    reason = "paper_action_scope_required"
    friendly_reason = "Paper action requires a signed-in trader and matching paper account"
    if not actor_trader_id:
        missing_fields.append("trader_scope")
    if not actor_paper_account_id:
        missing_fields.append("paper_account_scope")
    if not request_trader_id:
        missing_fields.append("request_trader_id")
    elif request_trader_id != actor_trader_id:
        missing_fields.append("trader_scope")
        reason = "trader_scope_mismatch"
        friendly_reason = "Trader account does not match the signed-in session"
    if not request_paper_account_id:
        missing_fields.append("request_paper_account_id")
    elif request_paper_account_id != actor_paper_account_id:
        missing_fields.append("paper_account_scope")
        reason = "paper_account_scope_mismatch"
        friendly_reason = "Paper account does not match the signed-in session"
    return _base_response(
        endpoint=endpoint,
        data={
            "accepted": False,
            "order": None,
            "reason": reason,
            "friendly_reason": friendly_reason,
            "trader_id": actor_trader_id,
            "paper_account_id": actor_paper_account_id,
            "paper_execution_policy": _paper_execution_policy(),
        },
        source="unavailable",
        source_type="unavailable",
        timestamp=None,
        missing_fields=[*dict.fromkeys(missing_fields)],
        warnings=warnings,
        symbol=symbol,
        mode="paper",
        trader_context=_trader_context(actor),
    )


@router.post("/orders/preview")
async def preview_order(
    request: OrderPreviewRequest,
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    endpoint = "/api/v2/orders/preview"
    safe_symbol = _safe_order_symbol(request.symbol)
    warnings = [
        "Preview only; no order is placed, routed, submitted, canceled, or persisted",
        "Paper submit is local repository staging only when authenticated trader checks pass",
    ]
    missing: list[str] = []
    actor_has_scope = bool(actor and actor.get("trader_id") and actor.get("paper_account_id"))
    repository_account = _repository_account(actor)
    account = repository_account if repository_account is not None else _paper_account(actor)
    terminal, source = _terminal_payload()
    market_price = (
        request.price
        if request.price is not None
        else terminal.get("last_price") if isinstance(terminal, dict) else None
    )
    preview_source_parts: list[str] = []
    preview_source_type: SourceType = "unavailable"
    preview_timestamp: str | None = None
    if repository_account is not None:
        preview_source_parts.append(TRADER_ACCOUNT_REPOSITORY_SOURCE)
        preview_source_type = "repository"
        preview_timestamp = repository_account.get("updated_at")
    if request.price is not None:
        warnings.append("Reference price was supplied by the paper preview request")
    if terminal:
        preview_source_parts.append(source)
        if preview_source_type == "unavailable":
            preview_source_type = "static_payload"
        preview_timestamp = _timestamp_from_payload(terminal) or preview_timestamp
    estimated_notional = (
        request.quantity * float(market_price)
        if request.quantity > 0 and isinstance(market_price, (int, float)) and market_price > 0
        else None
    )
    available_balance = account.get("equity") if actor_has_scope and isinstance(account, dict) else None
    allowed = False
    reason = "paper_preview_pending"
    friendly_reason = "Paper order preview is pending"
    mode: Mode = "paper_preview_unverified"
    if request.mode not in ("paper", "read_only"):
        reason = "live_mode_rejected"
        friendly_reason = "Live order preview is blocked"
        warnings.append("Live mode requested and rejected")
        mode = "live_blocked"
    elif safe_symbol is None:
        reason = "symbol_invalid"
        friendly_reason = "Enter a valid market symbol"
        warnings.append("Malformed paper order symbol was rejected")
        missing.append("symbol")
    elif request.quantity <= 0:
        reason = "quantity_invalid"
        friendly_reason = "Enter a quantity greater than zero"
        missing.append("quantity")
    elif request.order_type in ("limit", "stop") and not request.price:
        reason = "price_required"
        friendly_reason = "Enter a valid paper order price"
        missing.append("price")
    elif _production_paper_actions_disabled():
        reason = "production_paper_actions_disabled"
        friendly_reason = "Paper submit/cancel is disabled until production paper execution is verified"
        missing.extend(["production_paper_submit_cancel_validation", "production_paper_fill_writer", "verified_paper_execution_service"])
        warnings.append("Production paper action staging is disabled pending verified paper execution service approval")
    elif actor and request.trader_id and request.trader_id != actor.get("trader_id"):
        reason = "trader_scope_mismatch"
        friendly_reason = "Trader account does not match the signed-in session"
        warnings.append("Requested trader_id was rejected; backend session is authoritative")
        missing.append("trader_scope")
    elif actor and request.paper_account_id and request.paper_account_id != actor.get("paper_account_id"):
        reason = "paper_account_scope_mismatch"
        friendly_reason = "Paper account does not match the signed-in session"
        warnings.append("Requested paper_account_id was rejected; backend session is authoritative")
        missing.append("paper_account_scope")
    elif not actor:
        reason = "trader_session_required"
        friendly_reason = "Sign in for trader-specific paper preview"
        warnings.append("Unauthenticated preview is public read-only; account-specific paper balance is unavailable")
        missing.append("trader_session")
    elif not actor_has_scope:
        reason = "trader_account_scope_required"
        friendly_reason = "Trader profile and paper workspace are required for paper preview"
        warnings.append("Authenticated session is missing trader or paper-account scope")
        missing.extend(["trader_scope", "paper_account_scope"])
    elif account is None:
        reason = "paper_account_unavailable"
        friendly_reason = "Paper account data is unavailable"
        missing.append("available_paper_balance")
    elif available_balance is None:
        reason = "paper_balance_unavailable"
        friendly_reason = "Paper balance is unavailable for this trader"
        missing.append("available_paper_balance")
    elif estimated_notional is None:
        reason = "price_unavailable"
        friendly_reason = "Reference price is unavailable"
        missing.append("price")
    elif available_balance is not None and estimated_notional > available_balance:
        reason = "paper_balance_insufficient"
        friendly_reason = "Insufficient paper balance for this order"
        missing.append("available_paper_balance")
    else:
        allowed = True
        reason = "paper_preview_ready"
        friendly_reason = "Paper order can be staged"
        mode = "paper"
    data = {
        "allowed": allowed,
        "mode": mode,
        "reason": reason,
        "friendly_reason": friendly_reason,
        "estimated_notional": estimated_notional,
        "estimated_fee": estimated_notional * 0.0004 if estimated_notional is not None else None,
        "estimated_margin": estimated_notional if estimated_notional is not None else None,
        "available_paper_balance": available_balance,
        "trader_id": actor.get("trader_id") if actor else None,
        "paper_account_id": actor.get("paper_account_id") if actor else None,
        "request_trader_id": request.trader_id,
        "request_paper_account_id": request.paper_account_id,
        "request_scope_matches_session": bool(
            actor
            and request.trader_id
            and request.paper_account_id
            and request.trader_id == actor.get("trader_id")
            and request.paper_account_id == actor.get("paper_account_id")
        ),
        "account_scope": "authenticated_trader" if actor else "public_read_only",
        "paper_execution_policy": _paper_execution_policy(),
        "risk_checks": [
            {"name": "mode", "passed": request.mode in ("paper", "read_only")},
            {"name": "quantity", "passed": request.quantity > 0},
            {"name": "paper_account", "passed": actor is not None and bool(actor.get("paper_account_id")) and account is not None},
            {"name": "paper_balance", "passed": available_balance is not None},
            {"name": "trader_scope", "passed": actor is not None and bool(actor.get("trader_id")) and (not request.trader_id or request.trader_id == actor.get("trader_id"))},
            {"name": "paper_account_scope", "passed": actor is not None and bool(actor.get("paper_account_id")) and (not request.paper_account_id or request.paper_account_id == actor.get("paper_account_id"))},
            {"name": "request_scope", "passed": bool(actor and request.trader_id and request.paper_account_id and request.trader_id == actor.get("trader_id") and request.paper_account_id == actor.get("paper_account_id"))},
            {"name": "submit_endpoint", "passed": actor is not None and account is not None},
        ],
    }
    return _base_response(
        endpoint=endpoint,
        data=data,
        source=" + ".join(preview_source_parts) if preview_source_parts else "unavailable",
        source_type=preview_source_type,
        timestamp=preview_timestamp,
        missing_fields=missing,
        warnings=warnings,
        symbol=safe_symbol,
        mode=mode,
        trader_context=_trader_context(actor),
    )


@router.post("/orders/paper")
async def submit_paper_order(
    request: OrderPreviewRequest,
    actor: UserRecord = Depends(require_auth),
) -> dict[str, Any]:
    endpoint = "/api/v2/orders/paper"
    safe_symbol = _safe_order_symbol(request.symbol)
    if _production_paper_actions_disabled():
        return _production_paper_action_blocked_response(
            endpoint=endpoint,
            actor=actor,
            action="submit",
            symbol=safe_symbol,
        )
    if (
        not actor.get("trader_id")
        or not actor.get("paper_account_id")
        or request.trader_id != actor.get("trader_id")
        or request.paper_account_id != actor.get("paper_account_id")
    ):
        return _paper_action_scope_blocked_response(
            endpoint=endpoint,
            actor=actor,
            action="submit",
            request_trader_id=request.trader_id,
            request_paper_account_id=request.paper_account_id,
            symbol=safe_symbol,
        )
    repository_account = _repository_account(actor)
    preview = await preview_order(request, actor)
    preview_data = preview.get("data") if isinstance(preview.get("data"), dict) else {}
    if request.mode != "paper" or preview_data.get("allowed") is not True or repository_account is None:
        return _base_response(
            endpoint=endpoint,
            data={
                "accepted": False,
                "order": None,
                "reason": preview_data.get("reason") or "paper_submit_blocked",
                "friendly_reason": preview_data.get("friendly_reason") or "Paper order submit is blocked",
                "trader_id": actor.get("trader_id"),
                "paper_account_id": actor.get("paper_account_id"),
                "paper_execution_policy": _paper_execution_policy(),
            },
            source=preview.get("source") if isinstance(preview.get("source"), str) else "unavailable",
            source_type=preview.get("source_type") if preview.get("source_type") in {"repository", "static_payload", "api"} else "unavailable",
            timestamp=preview.get("timestamp") if isinstance(preview.get("timestamp"), str) else None,
            missing_fields=list(preview.get("missing_fields", [])) or ["paper_submit"],
            warnings=[
                "Paper submit rejected by preview checks",
                "No exchange state was read or mutated",
                "Live trading remains disabled",
                "No automatic paper fill or execution was generated",
                *[str(warning) for warning in preview.get("warnings", [])],
            ],
            symbol=safe_symbol,
            mode="paper",
            trader_context=_trader_context(actor),
        )

    try:
        order = get_trader_account_repository().append_paper_order(
            trader_id=str(actor.get("trader_id")),
            paper_account_id=str(actor.get("paper_account_id")),
            order={
                "symbol": safe_symbol,
                "side": request.side,
                "type": request.order_type,
                "order_type": request.order_type,
                "price": request.price,
                "stop_price": request.stop_price,
                "size": request.quantity,
                "quantity": request.quantity,
                "filled": 0,
                "notional": preview_data.get("estimated_notional"),
                "estimated_fee": preview_data.get("estimated_fee"),
                "reduce_only": bool(request.reduce_only),
                "take_profit": request.take_profit,
                "stop_loss": request.stop_loss,
                "reason": "Paper order staged",
            },
        )
    except HTTPException as exc:
        return _paper_repository_blocked_response(
            endpoint=endpoint,
            actor=actor,
            action="submit",
            symbol=safe_symbol,
            detail=str(exc.detail),
        )
    return _base_response(
        endpoint=endpoint,
        data={
            "accepted": True,
            "order": order,
            "reason": "paper_order_staged",
            "friendly_reason": "Paper order staged",
            "trader_id": actor.get("trader_id"),
            "paper_account_id": actor.get("paper_account_id"),
            "paper_execution_policy": _paper_execution_policy(),
        },
        source=TRADER_ACCOUNT_REPOSITORY_SOURCE,
        source_type="repository",
        timestamp=order.get("updated_at") if isinstance(order.get("updated_at"), str) else _utc_now(),
        missing_fields=[],
        warnings=[
            "Paper repository write only",
            "No automatic paper fill or execution was generated",
            "No exchange order was placed, routed, submitted, or canceled",
            "Live trading remains disabled",
        ],
        symbol=safe_symbol,
        mode="paper",
        trader_context=_trader_context(actor),
    )


@router.post("/orders/paper/{order_id}/fill")
async def fill_paper_order(
    order_id: str,
    request: PaperFillRequest,
    actor: UserRecord = Depends(require_auth),
) -> dict[str, Any]:
    endpoint = f"/api/v2/orders/paper/{order_id}/fill"
    if _production_paper_actions_disabled():
        return _production_paper_action_blocked_response(
            endpoint=endpoint,
            actor=actor,
            action="fill",
            include_execution=True,
        )
    repository_account = _repository_account(actor)
    if repository_account is None:
        return _base_response(
            endpoint=endpoint,
            data={
                "accepted": False,
                "order": None,
                "execution": None,
                "reason": "paper_account_unavailable",
                "friendly_reason": "Paper account data is unavailable",
                "trader_id": actor.get("trader_id"),
                "paper_account_id": actor.get("paper_account_id"),
                "paper_execution_policy": _paper_execution_policy(),
            },
            source="unavailable",
            source_type="unavailable",
            timestamp=None,
            missing_fields=["paper_account", "order"],
            warnings=[
                "Paper fill rejected because the trader paper account is unavailable",
                "No exchange state was read or mutated",
                "No live order transport is enabled",
                "Live trading remains disabled",
            ],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    try:
        result = get_trader_account_repository().fill_paper_order(
            trader_id=str(actor.get("trader_id")),
            paper_account_id=str(actor.get("paper_account_id")),
            order_id=order_id,
            price=request.price,
            quantity=request.quantity,
            reason=request.reason,
        )
    except HTTPException as exc:
        return _paper_repository_blocked_response(
            endpoint=endpoint,
            actor=actor,
            action="fill",
            include_execution=True,
            detail=str(exc.detail),
        )
    except ValueError as exc:
        return _base_response(
            endpoint=endpoint,
            data={
                "accepted": False,
                "order": None,
                "execution": None,
                "reason": "paper_fill_rejected",
                "friendly_reason": str(exc).replace("_", " ").capitalize(),
                "trader_id": actor.get("trader_id"),
                "paper_account_id": actor.get("paper_account_id"),
                "paper_execution_policy": _paper_execution_policy(),
            },
            source=TRADER_ACCOUNT_REPOSITORY_SOURCE,
            source_type="repository",
            timestamp=repository_account.get("updated_at"),
            missing_fields=["order"],
            warnings=[
                "Paper fill did not find a fillable trader-scoped order",
                "No exchange state was read or mutated",
                "No live order transport is enabled",
                "Live trading remains disabled",
            ],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    order = result.get("order") if isinstance(result.get("order"), dict) else {}
    execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
    return _base_response(
        endpoint=endpoint,
        data={
            "accepted": True,
            "order": order,
            "execution": execution,
            "reason": "paper_order_filled",
            "friendly_reason": "Paper order filled locally",
            "trader_id": actor.get("trader_id"),
            "paper_account_id": actor.get("paper_account_id"),
            "paper_execution_policy": _paper_execution_policy(),
        },
        source=TRADER_ACCOUNT_REPOSITORY_SOURCE,
        source_type="repository",
        timestamp=execution.get("created_at") if isinstance(execution.get("created_at"), str) else _utc_now(),
        missing_fields=[],
        warnings=[
            "Local paper fill writer only",
            "No exchange order was placed, routed, submitted, canceled, or filled",
            "No exchange state was read or mutated",
            "No live order transport is enabled",
            "Live trading remains disabled",
        ],
        symbol=order.get("symbol") if isinstance(order.get("symbol"), str) else None,
        mode="paper",
        trader_context=_trader_context(actor),
    )


# ─── Market State Brain endpoints ─────────────────────────────────────────────

def _market_brain_response(
    *,
    endpoint: str,
    data: dict[str, Any],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return _base_response(
        endpoint=endpoint,
        data=data,
        source=endpoint,
        source_type="api",
        timestamp=_timestamp_from_payload(data) or _utc_now(),
        missing_fields=[],
        warnings=warnings or [],
        mode="read_only",
    )


@router.get("/market-brain/overview")
async def get_market_brain_overview(
    actor: UserRecord = Depends(require_auth),
    r: Any = Depends(get_redis),
) -> Any:
    """Aggregated market state brain overview across all active symbols/TFs."""
    data = await _redis_get_json_object(r, "v2:market_brain:overview")
    if data is None:
        data: dict[str, Any] = {
            "state_distribution": {},
            "classifications_computed": 0,
            "note": "Market brain stream connecting",
            "places_real_order": False,
        }
    return _market_brain_response(
        endpoint="/api/v2/market-brain/overview",
        data=data,
    )


@router.get("/market-brain/state")
async def get_market_brain_all_states(
    actor: UserRecord = Depends(require_auth),
    r: Any = Depends(get_redis),
) -> Any:
    """All cached market brain state classifications from Redis."""
    states: list[dict[str, Any]] = []
    for key in sorted(await _redis_keys(r, "v2:market_brain:state:*")):
        payload = await _redis_get_json_object(r, key)
        if payload is not None:
            states.append(payload)
    return _market_brain_response(
        endpoint="/api/v2/market-brain/state",
        data={"states": states, "count": len(states), "places_real_order": False},
    )


@router.get("/market-brain/entry-gate-status")
async def get_entry_gate_status(
    actor: UserRecord = Depends(require_auth),
) -> Any:
    """Current P0 entry gate config — symbol exclusions, TF filter, mode blocks."""
    warnings: list[str] = []
    try:
        from app.services.paper_trade_management.entry_gate import (
            PaperEntryGateConfig,
            _NOISY_TIMEFRAMES,
        )
        cfg = PaperEntryGateConfig()
        data: dict[str, Any] = {
            "symbol_exclusion_list": sorted(cfg.symbol_exclusion_list),
            "allowed_entry_timeframes": sorted(cfg.allowed_entry_timeframes),
            "blocked_strategy_modes": sorted(cfg.blocked_strategy_modes),
            "noisy_timeframes_require_override": sorted(_NOISY_TIMEFRAMES),
            "min_confidence_calibrated": cfg.min_confidence_calibrated,
            "require_positive_expected_move": cfg.require_positive_expected_move,
            "major_move_override_enabled": cfg.major_move_override_enabled,
            "evidence_source": "runtime_entry_gate_config",
            "places_real_order": False,
        }
    except Exception as exc:
        warnings.append(f"Entry gate config source connecting: {type(exc).__name__}")
        data = {
            "symbol_exclusion_list": [],
            "allowed_entry_timeframes": [],
            "blocked_strategy_modes": [],
            "noisy_timeframes_require_override": [],
            "min_confidence_calibrated": None,
            "require_positive_expected_move": True,
            "major_move_override_enabled": False,
            "evidence_source": "entry_gate_config_connecting",
            "places_real_order": False,
        }
    return _market_brain_response(
        endpoint="/api/v2/market-brain/entry-gate-status",
        data=data,
        warnings=warnings,
    )


@router.get("/market-brain/hedge-lock-status")
async def get_hedge_lock_status(
    actor: UserRecord = Depends(require_auth),
    r: Any = Depends(get_redis),
) -> Any:
    """All active paper-only hedge lock pairs."""
    pairs: list[dict[str, Any]] = []
    for key in sorted(await _redis_keys(r, "v2:paper:hedge_locks:*")):
        payload = await _redis_get_json_object(r, key)
        if payload is not None:
            pairs.append(payload)
    data: dict[str, Any] = {
        "active_hedge_locks": pairs,
        "count": len(pairs),
        "hedge_lock_enabled_by_default": False,
        "note": "HedgeLock requires explicit operator approval (CLAUDE.md dangerous setting).",
        "places_real_order": False,
    }
    return _market_brain_response(
        endpoint="/api/v2/market-brain/hedge-lock-status",
        data=data,
    )


@router.post("/orders/paper/{order_id}/cancel")
async def cancel_paper_order(
    order_id: str,
    actor: UserRecord = Depends(require_auth),
) -> dict[str, Any]:
    endpoint = f"/api/v2/orders/paper/{order_id}/cancel"
    if _production_paper_actions_disabled():
        return _production_paper_action_blocked_response(
            endpoint=endpoint,
            actor=actor,
            action="cancel",
        )
    repository_account = _repository_account(actor)
    if repository_account is None:
        return _base_response(
            endpoint=endpoint,
            data={
                "accepted": False,
                "order": None,
                "reason": "paper_account_unavailable",
                "friendly_reason": "Paper account data is unavailable",
                "trader_id": actor.get("trader_id"),
                "paper_account_id": actor.get("paper_account_id"),
                "paper_execution_policy": _paper_execution_policy(),
            },
            source="unavailable",
            source_type="unavailable",
            timestamp=None,
            missing_fields=["paper_account", "order"],
            warnings=[
                "Paper cancel rejected because the trader paper account is unavailable",
                "No exchange state was read or mutated",
                "Live trading remains disabled",
            ],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    try:
        order = get_trader_account_repository().cancel_paper_order(
            trader_id=str(actor.get("trader_id")),
            paper_account_id=str(actor.get("paper_account_id")),
            order_id=order_id,
        )
    except HTTPException as exc:
        return _paper_repository_blocked_response(
            endpoint=endpoint,
            actor=actor,
            action="cancel",
            detail=str(exc.detail),
        )
    except ValueError as exc:
        return _base_response(
            endpoint=endpoint,
            data={
                "accepted": False,
                "order": None,
                "reason": "paper_cancel_rejected",
                "friendly_reason": str(exc).replace("_", " ").capitalize(),
                "trader_id": actor.get("trader_id"),
                "paper_account_id": actor.get("paper_account_id"),
                "paper_execution_policy": _paper_execution_policy(),
            },
            source=TRADER_ACCOUNT_REPOSITORY_SOURCE,
            source_type="repository",
            timestamp=repository_account.get("updated_at"),
            missing_fields=["order"],
            warnings=[
                "Paper cancel did not find a cancelable trader-scoped order",
                "No exchange state was read or mutated",
                "Live trading remains disabled",
            ],
            mode="paper",
            trader_context=_trader_context(actor),
        )
    return _base_response(
        endpoint=endpoint,
        data={
            "accepted": True,
            "order": order,
            "reason": "paper_order_canceled",
            "friendly_reason": "Paper order canceled",
            "trader_id": actor.get("trader_id"),
            "paper_account_id": actor.get("paper_account_id"),
            "paper_execution_policy": _paper_execution_policy(),
        },
        source=TRADER_ACCOUNT_REPOSITORY_SOURCE,
        source_type="repository",
        timestamp=order.get("updated_at") if isinstance(order.get("updated_at"), str) else _utc_now(),
        missing_fields=[],
        warnings=[
            "Paper repository cancel only",
            "No exchange order was canceled",
            "Live trading remains disabled",
        ],
        symbol=order.get("symbol") if isinstance(order.get("symbol"), str) else None,
        mode="paper",
        trader_context=_trader_context(actor),
    )


# ---------------------------------------------------------------------------
# Natural-language explanation helpers
# ---------------------------------------------------------------------------

def _conviction_label(dominant_prob: float | None) -> str:
    if dominant_prob is None:
        return "uncertain"
    if dominant_prob > 0.9:
        return "extremely high-conviction"
    if dominant_prob > 0.7:
        return "high-conviction"
    if dominant_prob > 0.5:
        return "moderate-conviction"
    return "low-conviction / uncertain"


def _masa_label(masa: float | None) -> str:
    if masa is None:
        return "unavailable"
    if masa < -0.5:
        return "strongly bearish"
    if masa < -0.1:
        return "mildly bearish"
    if masa <= 0.1:
        return "neutral"
    if masa <= 0.5:
        return "mildly bullish"
    return "strongly bullish"


def _group_missing_features(names: list[str]) -> dict[str, list[str]]:
    """Group missing feature names into broad categories."""
    liquidation_kw = {"liquidation", "liquidity_zone", "distance_to_liquidity_zone"}
    nansen_kw = {"nansen"}
    lunar_kw = {"lunarcrush"}
    aicoin_kw = {"aicoin"}
    paper_kw = {"paper_position", "paper_unrealized"}
    htf_kw = {"htf_"}
    orchestrator_kw = {"orchestrator_recent", "risk_recent"}

    groups: dict[str, list[str]] = {
        "liquidation": [],
        "alternative_data": [],
        "paper_state": [],
        "htf": [],
        "orchestrator_feedback": [],
        "other": [],
    }
    for name in names:
        nl = name.lower()
        if any(kw in nl for kw in liquidation_kw):
            groups["liquidation"].append(name)
        elif any(kw in nl for kw in nansen_kw | lunar_kw | aicoin_kw):
            groups["alternative_data"].append(name)
        elif any(kw in nl for kw in paper_kw):
            groups["paper_state"].append(name)
        elif any(nl.find(kw) != -1 for kw in htf_kw):
            groups["htf"].append(name)
        elif any(kw in nl for kw in orchestrator_kw):
            groups["orchestrator_feedback"].append(name)
        else:
            groups["other"].append(name)
    return groups


def _build_explanation(
    pred_payload: dict[str, Any] | None,
    sig_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a structured natural-language explanation from raw Redis payloads.
    No LLM calls -- all text is derived from numeric thresholds and field values.
    """
    p = pred_payload or {}
    s = sig_payload or {}

    # --- Key numbers extraction ---
    action_labels: list[str] = p.get("action_labels") or []
    action_probs_raw = p.get("action_probabilities") or []
    action_probs: list[float] = [_float(v) or 0.0 for v in action_probs_raw]

    selected_action = str(p.get("selected_action") or s.get("action") or "").strip().upper() or "UNKNOWN"
    dominant_prob: float | None = None
    secondary_action: str | None = None
    secondary_prob: float | None = None
    if action_probs and action_labels:
        sorted_pairs = sorted(zip(action_probs, action_labels), reverse=True)
        if sorted_pairs:
            dominant_prob = sorted_pairs[0][0]
            secondary_prob = sorted_pairs[1][0] if len(sorted_pairs) > 1 else None
            secondary_action = sorted_pairs[1][1].upper() if len(sorted_pairs) > 1 else None

    confidence_calibrated = _float(p.get("confidence_calibrated"))
    confidence_raw = _float(p.get("confidence_raw"))
    calibration: dict[str, Any] = p.get("confidence_calibration") or {}
    temperature = _float(calibration.get("temperature"))
    coverage_factor = _float(calibration.get("coverage_factor"))

    data_coverage = _float(p.get("data_coverage_percent") or s.get("data_coverage_percent"))
    integrity_score = _float(p.get("market_state_integrity_score") or s.get("market_state_integrity_score"))
    score_components: dict[str, Any] = p.get("market_state_score_components") or {}

    masa_signal = _float(p.get("masa_signal"))
    policy_value = _float(p.get("policy_value"))
    expected_move_bps = _float(p.get("expected_move_bps"))
    expected_move_after_cost = _float(
        p.get("expected_move_after_cost_bps") or s.get("expected_move_after_cost_bps")
    )
    price_target = _float(s.get("price_target") or p.get("price_target"))
    price_target_after_cost = _float(s.get("price_target_after_cost") or p.get("price_target_after_cost"))

    missing_feature_names: list[str] = p.get("missing_feature_names") or []
    missing_feature_count = int(p.get("missing_feature_count") or len(missing_feature_names))
    stale_feature_count = int(p.get("stale_feature_count") or 0)

    live_gate = str(p.get("live_gate") or s.get("live_gate") or "blocked_human_only")
    orchestrator_state = str(s.get("orchestrator_state") or "UNKNOWN")
    risk_state = str(s.get("risk_state") or "UNKNOWN")
    paper_fill_status = str(s.get("paper_fill_status") or "UNKNOWN")
    paper_fill_allowed = s.get("paper_fill_allowed") is True

    # --- Conviction label ---
    conviction = _conviction_label(dominant_prob)
    dom_pct = f"{dominant_prob * 100:.1f}%" if dominant_prob is not None else "N/A"
    sec_pct = f"{secondary_prob * 100:.3f}%" if secondary_prob is not None else "N/A"

    secondary_clause = ""
    if secondary_action and secondary_prob is not None:
        secondary_clause = f" (vs {secondary_action} {sec_pct})"
    summary = (
        f"The model predicted {selected_action} with {dom_pct} confidence{secondary_clause}. "
        f"This is a {conviction} directional call."
    )

    signal_strength = conviction

    # --- Confidence calibration narrative ---
    conf_cal_pct = f"{confidence_calibrated * 100:.1f}%" if confidence_calibrated is not None else "N/A"
    conf_raw_pct = f"{confidence_raw * 100:.1f}%" if confidence_raw is not None else "N/A"
    temp_str = f"{temperature:.1f}x" if temperature is not None else "N/A"
    cov_pct = f"{coverage_factor * 100:.1f}%" if coverage_factor is not None else "N/A"
    cal_source = str(calibration.get("calibration_source") or "unknown")

    if (
        cal_source == "temperature_plus_data_quality_downrating"
        and temperature is not None
        and coverage_factor is not None
    ):
        confidence_narrative = (
            f"Raw model confidence was {conf_raw_pct}. "
            f"This was calibrated down to {conf_cal_pct} via two factors: "
            f"(1) Temperature scaling ({temp_str}) divides the raw logit score to account for model overconfidence -- "
            f"the higher the temperature, the softer (more uncertain) the output distribution. "
            f"(2) Data quality downrating ({cov_pct} coverage factor) further reduces confidence proportionally "
            f"to the fraction of expected feature inputs that were actually present at inference time."
        )
    else:
        confidence_narrative = (
            f"Raw model confidence was {conf_raw_pct}, calibrated to {conf_cal_pct} "
            f"(source: {cal_source})."
        )

    # --- Data quality narrative ---
    feature_groups = _group_missing_features(missing_feature_names)
    liq_count = len(feature_groups["liquidation"])
    alt_count = len(feature_groups["alternative_data"])
    paper_count = len(feature_groups["paper_state"])
    htf_count = len(feature_groups["htf"])
    orc_count = len(feature_groups["orchestrator_feedback"])
    other_count = len(feature_groups["other"])

    missing_parts: list[str] = []
    if liq_count:
        missing_parts.append(f"liquidation data ({liq_count} features)")
    if alt_count:
        alt_names = feature_groups["alternative_data"]
        providers: list[str] = []
        if any("nansen" in n.lower() for n in alt_names):
            providers.append("Nansen")
        if any("lunarcrush" in n.lower() for n in alt_names):
            providers.append("LunarCrush")
        if any("aicoin" in n.lower() for n in alt_names):
            providers.append("AICoin")
        provider_str = ", ".join(providers) if providers else "external alt-data"
        missing_parts.append(f"alternative data: {provider_str} ({alt_count} features)")
    if paper_count:
        missing_parts.append(f"paper trading state ({paper_count} features)")
    if htf_count:
        missing_parts.append(f"higher-timeframe context ({htf_count} features)")
    if orc_count:
        missing_parts.append(f"orchestrator/risk feedback ({orc_count} features)")
    if other_count:
        missing_parts.append(f"other inputs ({other_count} features)")

    cov_str = f"{data_coverage:.1f}%" if data_coverage is not None else "N/A"
    if missing_parts:
        dq_narrative = (
            f"Data coverage at inference: {cov_str} ({missing_feature_count} features missing). "
            f"Missing categories: {'; '.join(missing_parts)}. "
            f"Each missing category reduces model confidence and increases prediction uncertainty. "
            f"Stale features: {stale_feature_count}."
        )
    else:
        dq_narrative = (
            f"Data coverage at inference: {cov_str}. "
            f"No missing features detected. Stale features: {stale_feature_count}."
        )

    # --- Market integrity narrative ---
    int_str = f"{integrity_score:.1f}/100" if integrity_score is not None else "N/A"
    comp_parts: list[str] = []
    for comp_name, comp_val in sorted(score_components.items()):
        comp_val_f = _float(comp_val)
        label = comp_name.replace("_score", "").replace("_", " ")
        if comp_val_f is not None:
            comp_parts.append(f"{label} {comp_val_f:.0f}/100")

    if comp_parts:
        comp_str = "; ".join(comp_parts)
        integrity_narrative = (
            f"Market state scored {int_str}. "
            f"Component breakdown: {comp_str}. "
            f"Lower-scoring components indicate data gaps or market irregularities that increase noise."
        )
    else:
        integrity_narrative = f"Market state scored {int_str}."

    # --- Technical drivers ---
    masa_lbl = _masa_label(masa_signal)
    masa_str_val = f"{masa_signal:.3f}" if masa_signal is not None else "N/A"
    pv_str = f"{policy_value:.3f}" if policy_value is not None else "N/A"
    pv_bias = ""
    if policy_value is not None:
        if policy_value < -0.5:
            pv_bias = " (agent strongly prefers short)"
        elif policy_value < 0:
            pv_bias = " (agent mildly prefers short)"
        elif policy_value > 0.5:
            pv_bias = " (agent strongly prefers long)"
        elif policy_value > 0:
            pv_bias = " (agent mildly prefers long)"
        else:
            pv_bias = " (agent neutral)"
    technical_drivers = (
        f"MASA signal: {masa_str_val} ({masa_lbl} momentum indicator). "
        f"PPO policy value: {pv_str}{pv_bias}. "
        f"These are the primary model-internal indicators driving the directional call."
    )

    # --- Price target narrative ---
    if expected_move_after_cost is not None and price_target_after_cost is not None:
        move_str = f"{expected_move_after_cost:+.0f} bps"
        pt_str = f"${price_target_after_cost:,.2f}"
        raw_pt_str = f"${price_target:,.2f}" if price_target is not None else "N/A"
        current_price_approx: float | None = None
        if price_target is not None and expected_move_bps is not None and expected_move_bps != 0:
            current_price_approx = price_target / (1.0 + expected_move_bps / 10000.0)
        cur_str = f"~${current_price_approx:,.0f}" if current_price_approx is not None else "N/A"
        move_usd: float | None = None
        if current_price_approx is not None:
            move_usd = price_target_after_cost - current_price_approx
        usd_clause = f" = approx ~${move_usd:+,.0f} move." if move_usd is not None else "."
        price_target_narrative = (
            f"Expected move after cost: {move_str}. "
            f"Pre-cost target: {raw_pt_str}. "
            f"After-cost target: {pt_str} vs current {cur_str}"
            + usd_clause
        )
    elif expected_move_bps is not None:
        price_target_narrative = (
            f"Expected move: {expected_move_bps:+.0f} bps (after-cost target not available)."
        )
    else:
        price_target_narrative = "Price target unavailable."

    # --- Risk gate narrative ---
    if live_gate == "blocked_human_only":
        rg_base = "Live gate is BLOCKED -- human approval required before any live execution."
    elif live_gate == "blocked":
        rg_base = "Live gate is BLOCKED."
    elif live_gate == "open":
        rg_base = "Live gate is OPEN."
    else:
        rg_base = f"Live gate state: {live_gate}."

    paper_clause = (
        "Paper fill is ALLOWED (shadow fill pathway active)."
        if paper_fill_allowed
        else f"Paper fill is NOT allowed (status: {paper_fill_status})."
    )
    risk_gate_narrative = f"{rg_base} Risk gateway decision: {risk_state}. {paper_clause}"

    # --- Pipeline state narrative ---
    orch_clause = orchestrator_state.replace("_", " ").title()
    pipeline_state_narrative = (
        f"Signal is currently at orchestrator stage: {orch_clause}. "
        f"Paper fill status: {paper_fill_status.replace('_', ' ').title()}."
    )

    full_text = " | ".join([
        summary,
        confidence_narrative,
        dq_narrative,
        integrity_narrative,
        technical_drivers,
        price_target_narrative,
        risk_gate_narrative,
        pipeline_state_narrative,
    ])

    key_numbers: dict[str, Any] = {
        "action": selected_action,
        "confidence_calibrated": confidence_calibrated,
        "confidence_raw": confidence_raw,
        "dominant_prob": dominant_prob,
        "expected_move_bps": expected_move_bps,
        "expected_move_after_cost_bps": expected_move_after_cost,
        "price_target": price_target,
        "price_target_after_cost": price_target_after_cost,
        "data_coverage_pct": data_coverage,
        "integrity_score": integrity_score,
        "masa_signal": masa_signal,
        "policy_value": policy_value,
        "missing_feature_count": missing_feature_count,
        "stale_feature_count": stale_feature_count,
    }

    return {
        "explanation": {
            "summary": summary,
            "signal_strength": signal_strength,
            "confidence_narrative": confidence_narrative,
            "data_quality_narrative": dq_narrative,
            "market_integrity_narrative": integrity_narrative,
            "technical_drivers": technical_drivers,
            "price_target_narrative": price_target_narrative,
            "risk_gate_narrative": risk_gate_narrative,
            "pipeline_state_narrative": pipeline_state_narrative,
            "full_text": full_text,
        },
        "key_numbers": key_numbers,
    }


def _build_signal_explanation(sig_payload: dict[str, Any] | None) -> dict[str, Any]:
    """Shorter explanation focused on the trading signal outcome."""
    s = sig_payload or {}
    action = str(s.get("action") or "UNKNOWN").strip().upper()
    confidence = _float(s.get("confidence"))
    live_gate = str(s.get("live_gate") or "blocked_human_only")
    orchestrator_state = str(s.get("orchestrator_state") or "UNKNOWN")
    risk_state = str(s.get("risk_state") or "UNKNOWN")
    paper_fill_status = str(s.get("paper_fill_status") or "UNKNOWN")
    paper_fill_allowed = s.get("paper_fill_allowed") is True
    paper_state = str(s.get("paper_state") or "UNKNOWN")
    expected_move_bps = _float(s.get("expected_move_after_cost_bps"))
    price_target_after_cost = _float(s.get("price_target_after_cost"))
    integrity_score = _float(s.get("market_state_integrity_score"))
    data_coverage = _float(s.get("data_coverage_percent"))

    conf_str = f"{confidence * 100:.1f}%" if confidence is not None else "N/A"
    move_str = f"{expected_move_bps:+.0f} bps" if expected_move_bps is not None else "N/A"
    pt_str = f"${price_target_after_cost:,.2f}" if price_target_after_cost is not None else "N/A"
    int_str = f"{integrity_score:.1f}/100" if integrity_score is not None else "N/A"
    cov_str = f"{data_coverage:.1f}%" if data_coverage is not None else "N/A"

    gate_note = (
        "Live gate: BLOCKED -- human approval required."
        if live_gate == "blocked_human_only"
        else f"Live gate: {live_gate}."
    )
    paper_note = (
        "Paper fill allowed."
        if paper_fill_allowed
        else f"Paper fill NOT allowed ({paper_fill_status})."
    )
    risk_note = f"Risk gateway: {risk_state.replace('_', ' ').title()}."
    orch_note = f"Orchestrator: {orchestrator_state.replace('_', ' ').title()}."

    summary = (
        f"Signal: {action} at {conf_str} confidence. "
        f"Expected move after cost: {move_str}. After-cost price target: {pt_str}. "
        f"Market integrity: {int_str}. Data coverage: {cov_str}. "
        f"{gate_note} {paper_note} {risk_note} {orch_note} "
        f"Paper state: {paper_state.replace('_', ' ').title()}."
    )
    return {
        "summary": summary,
        "action": action,
        "confidence": confidence,
        "live_gate": live_gate,
        "paper_fill_allowed": paper_fill_allowed,
        "paper_fill_status": paper_fill_status,
        "paper_state": paper_state,
        "risk_state": risk_state,
        "orchestrator_state": orchestrator_state,
        "expected_move_after_cost_bps": expected_move_bps,
        "price_target_after_cost": price_target_after_cost,
        "integrity_score": integrity_score,
        "data_coverage_pct": data_coverage,
    }


# ---------------------------------------------------------------------------
# Prediction explain endpoint
# ---------------------------------------------------------------------------

@router.get("/predictions/explain")
async def get_prediction_explain(
    symbol: str = Query(description="Symbol, e.g. BTCUSDT"),
    timeframe: str = Query(description="Timeframe, e.g. 1h"),
) -> dict[str, Any]:
    """Return a natural-language explanation of the latest prediction for a symbol/timeframe."""
    endpoint = "/api/v2/predictions/explain"
    sym = symbol.strip().upper()
    tf = timeframe.strip().lower()

    pred_payload = _read_v2_redis_json(f"v2:prediction:{sym}:{tf}")
    sig_payload = _read_v2_redis_json(f"v2:signals:paper:{sym}:{tf}")

    if pred_payload is None and sig_payload is None:
        return _base_response(
            endpoint=endpoint,
            data=None,
            source="redis",
            source_type="unavailable",
            timestamp=None,
            missing_fields=["prediction", "signal"],
            warnings=[f"No prediction or signal found in Redis for {sym}:{tf}"],
            symbol=sym,
            mode="paper",
        )

    explain_data = _build_explanation(pred_payload, sig_payload)
    timestamp = _timestamp_from_redis_payload(pred_payload) or _timestamp_from_redis_payload(sig_payload)
    missing: list[str] = []
    if pred_payload is None:
        missing.append("prediction")
    if sig_payload is None:
        missing.append("signal")

    return _base_response(
        endpoint=endpoint,
        data={
            "symbol": sym,
            "timeframe": tf,
            "generated_at": _utc_now(),
            **explain_data,
        },
        source="redis:v2:prediction+v2:signals:paper",
        source_type="static_payload",
        timestamp=timestamp,
        missing_fields=missing,
        warnings=[] if not missing else [f"Partial data: missing {', '.join(missing)}"],
        symbol=sym,
        mode="paper",
    )


# ---------------------------------------------------------------------------
# Signal explain endpoint
# ---------------------------------------------------------------------------

@router.get("/signals/explain")
async def get_signal_explain(
    symbol: str = Query(description="Symbol, e.g. BTCUSDT"),
    timeframe: str = Query(description="Timeframe, e.g. 1h"),
) -> dict[str, Any]:
    """Return a short natural-language explanation of the latest paper signal for a symbol/timeframe."""
    endpoint = "/api/v2/signals/explain"
    sym = symbol.strip().upper()
    tf = timeframe.strip().lower()

    sig_payload = _read_v2_redis_json(f"v2:signals:paper:{sym}:{tf}")
    if sig_payload is None:
        return _base_response(
            endpoint=endpoint,
            data=None,
            source="redis",
            source_type="unavailable",
            timestamp=None,
            missing_fields=["signal"],
            warnings=[f"No signal found in Redis for {sym}:{tf}"],
            symbol=sym,
            mode="paper",
        )

    explanation = _build_signal_explanation(sig_payload)
    timestamp = _timestamp_from_redis_payload(sig_payload)
    return _base_response(
        endpoint=endpoint,
        data={
            "symbol": sym,
            "timeframe": tf,
            "generated_at": _utc_now(),
            "explanation": explanation,
        },
        source="redis:v2:signals:paper",
        source_type="static_payload",
        timestamp=timestamp,
        missing_fields=[],
        warnings=[],
        symbol=sym,
        mode="paper",
    )


# ---------------------------------------------------------------------------
# Redis JSON / list helpers for orchestrator and risk endpoints
# ---------------------------------------------------------------------------

def _read_v2_redis_json_or_list(key: str) -> Any:
    """Read a Redis key that may contain a JSON string, dict, or list."""
    client = get_redis()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return None


def _parse_redis_list_or_json(value: Any) -> list[dict[str, Any]]:
    """Normalise a value that may be a JSON list, a JSON dict, or None into a list of dicts."""
    if value is None:
        return []
    if isinstance(value, list):
        result: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, (str, bytes)):
                try:
                    parsed = json.loads(item)
                    if isinstance(parsed, dict):
                        result.append(parsed)
                except Exception:
                    pass
        return result
    if isinstance(value, dict):
        return [value]
    return []


def _risk_runtime_decision_symbol(decision: dict[str, Any]) -> str | None:
    canary = decision.get("canary_profile_tightening")
    canary_symbol = canary.get("symbol") if isinstance(canary, dict) else None
    value = decision.get("symbol") or canary_symbol
    return str(value).upper() if value else None


def _risk_runtime_decision_side(decision: dict[str, Any]) -> str | None:
    value = decision.get("side")
    if value:
        return str(value).lower()
    canary = decision.get("canary_profile_tightening")
    action = str(canary.get("action") if isinstance(canary, dict) else decision.get("risk_action") or "").lower()
    if "long" in action or "buy" in action:
        return "long"
    if "short" in action or "sell" in action:
        return "short"
    return None


def _risk_runtime_decision_row(decision: dict[str, Any]) -> dict[str, Any]:
    canary = decision.get("canary_profile_tightening")
    canary_dict = canary if isinstance(canary, dict) else {}
    edge_gate = decision.get("paper_edge_gate")
    edge_gate_dict = edge_gate if isinstance(edge_gate, dict) else {}
    return {
        "risk_decision_id": decision.get("risk_decision_id"),
        "prediction_id": decision.get("prediction_id"),
        "signal_id": decision.get("signal_id"),
        "feature_snapshot_id": decision.get("feature_snapshot_id"),
        "symbol": _risk_runtime_decision_symbol(decision),
        "side": _risk_runtime_decision_side(decision),
        "risk_action": decision.get("risk_action") or ("deny" if decision.get("live_blocked") is True else None),
        "risk_result": decision.get("risk_result"),
        "risk_reason_code": decision.get("risk_reason_code"),
        "live_blocked": decision.get("live_blocked"),
        "pre_trade_allowed": decision.get("pre_trade_allowed"),
        "fee_gate_allowed": edge_gate_dict.get("fill_allowed"),
        "fee_gate_reason": edge_gate_dict.get("classification"),
        "churn_blocked": None,
        "churn_reason": None,
        "strategy_selected_mode": decision.get("strategy_selected_mode"),
        "strategy_allowed_actions": decision.get("strategy_allowed_actions"),
        "strategy_size_multiplier": decision.get("strategy_size_multiplier"),
        "strategy_router_confidence": decision.get("strategy_router_confidence") or canary_dict.get("confidence"),
        "strategy_regime_labels": decision.get("strategy_regime_labels") or [],
        "required_blocks_checked": decision.get("required_blocks_checked") or [],
        "generated_at": decision.get("generated_at"),
    }


def _risk_status_from_runtime_artifacts(endpoint: str) -> dict[str, Any] | None:
    runtime, runtime_source = _read_json("operator_runtime/paper_online/latest/paper_runtime_status.json")
    risk_payload, risk_source = _read_json("operator_runtime/paper_online/latest/risk_runtime_payload.json")
    decisions_payload, decisions_source = _read_json("operator_runtime/paper_online/latest/current_risk_decisions.json")
    if not runtime and not risk_payload and not decisions_payload:
        return None

    decisions_raw = decisions_payload.get("decisions") if isinstance(decisions_payload, dict) else []
    decisions = [
        _risk_runtime_decision_row(row)
        for row in (decisions_raw if isinstance(decisions_raw, list) else [])
        if isinstance(row, dict)
    ]
    latest = decisions[0] if decisions else {}
    latest_runtime_decision = runtime.get("current_risk_decision") if isinstance(runtime, dict) else None
    if not latest and isinstance(latest_runtime_decision, dict):
        latest = _risk_runtime_decision_row(latest_runtime_decision)
        decisions = [latest]

    denials_breakdown: dict[str, int] = {}
    for row in decisions:
        action = str(row.get("risk_action") or "").lower()
        if action and action != "allow":
            reason = str(row.get("risk_reason_code") or row.get("fee_gate_reason") or "risk_denied")
            denials_breakdown[reason] = denials_breakdown.get(reason, 0) + 1

    timestamp = (
        _timestamp_from_payload(decisions_payload if isinstance(decisions_payload, dict) else None)
        or _timestamp_from_payload(risk_payload if isinstance(risk_payload, dict) else None)
        or _timestamp_from_payload(runtime if isinstance(runtime, dict) else None)
    )
    generated_at = timestamp or _utc_now()
    daily_limit = _float(risk_payload.get("daily_loss_limit_usdt")) if isinstance(risk_payload, dict) else None
    weekly_limit = _float(risk_payload.get("weekly_loss_limit_usdt")) if isinstance(risk_payload, dict) else None
    profile_id = str(risk_payload.get("risk_config_version") or "runtime_risk_profile") if isinstance(risk_payload, dict) else "runtime_risk_profile"
    live_gate = (
        risk_payload.get("live_gate_status")
        if isinstance(risk_payload, dict)
        else runtime.get("live_gate_status") if isinstance(runtime, dict) else None
    )
    heartbeat = {
        "worker_id": "paper_online_runtime",
        "started_at": runtime.get("generated_at") if isinstance(runtime, dict) else generated_at,
        "finished_at": generated_at,
        "decisions_processed_total": len(decisions),
        "live_gate": live_gate,
        "live_blocked": live_gate == "blocked_human_only",
        "classification": "RUNTIME_ARTIFACT_CURRENT" if timestamp else "RUNTIME_ARTIFACT_AVAILABLE",
        "fail_closed": True,
        "approves_live": False,
        "places_real_order": False,
    }
    data = {
        "active_profile": {
            "profile_id": profile_id,
            "profile_name": "Runtime risk controls",
            "fields": {
                "max_daily_loss": abs(daily_limit) if daily_limit is not None else None,
                "max_drawdown": abs(weekly_limit) if weekly_limit is not None else None,
                "kill_switch_conditions": [
                    "daily_loss_gate",
                    "weekly_loss_gate",
                    "stop_policy_required",
                    "operator_gate_required",
                ],
            },
        },
        "latest_gateway_result": latest,
        "heartbeat": heartbeat,
        "recent_decisions": decisions[:10],
        "denials_breakdown": denials_breakdown,
    }
    return _base_response(
        endpoint=endpoint,
        data=data,
        source=f"{runtime_source} + {risk_source} + {decisions_source}",
        source_type="static_payload",
        timestamp=timestamp,
        missing_fields=[] if decisions else ["risk_decisions"],
        warnings=[
            "Risk status loaded from current runtime artifacts because Redis risk keys are unavailable",
            "Risk endpoint remains read-only and does not approve exchange mutation",
        ],
        mode="paper",
    )


# ---------------------------------------------------------------------------
# Orchestrator status endpoint
# ---------------------------------------------------------------------------

@router.get("/orchestrator/status")
async def get_orchestrator_status() -> dict[str, Any]:
    """Return the current orchestrator heartbeat, proposals, and decisions from Redis."""
    endpoint = "/api/v2/orchestrator/status"

    heartbeat_raw = _read_v2_redis_json_or_list("v2:orchestrator:heartbeat")
    proposals_raw = _read_v2_redis_json_or_list("v2:orchestrator:proposals")
    decisions_raw = _read_v2_redis_json_or_list("v2:orchestrator:decisions")

    heartbeat: dict[str, Any] | None = heartbeat_raw if isinstance(heartbeat_raw, dict) else None
    last_proposals = _parse_redis_list_or_json(proposals_raw)
    decisions_list = _parse_redis_list_or_json(decisions_raw)
    latest_decision: dict[str, Any] | None = (
        decisions_list[0] if decisions_list else (
            decisions_raw if isinstance(decisions_raw, dict) else None
        )
    )

    classification = None
    live_gate = None
    deconflict_reason = None
    if heartbeat:
        classification = heartbeat.get("classification")
        live_gate = heartbeat.get("live_gate")
        deconflict_reason = heartbeat.get("deconflict_reason")
    if latest_decision and deconflict_reason is None:
        deconflict_reason = latest_decision.get("deconflict_reason")

    missing: list[str] = []
    if heartbeat is None:
        missing.append("orchestrator_heartbeat")
    if not decisions_list and latest_decision is None:
        missing.append("orchestrator_decisions")

    timestamp = None
    if heartbeat:
        timestamp = heartbeat.get("finished_at") or heartbeat.get("started_at")
    if timestamp is None and latest_decision:
        timestamp = latest_decision.get("generated_utc")

    return _base_response(
        endpoint=endpoint,
        data={
            "heartbeat": {
                "worker_id": heartbeat.get("worker_id") if heartbeat else None,
                "started_at": heartbeat.get("started_at") if heartbeat else None,
                "finished_at": heartbeat.get("finished_at") if heartbeat else None,
                "predictions_seen": heartbeat.get("predictions_seen") if heartbeat else None,
                "proposals_arbitrated": heartbeat.get("proposals_arbitrated") if heartbeat else None,
                "classification": classification,
                "live_gate": live_gate,
                "approves_live": heartbeat.get("approves_live") if heartbeat else None,
                "cannot_bypass_risk_gateway": heartbeat.get("cannot_bypass_risk_gateway") if heartbeat else None,
            } if heartbeat else None,
            "last_proposals": last_proposals,
            "last_decisions": (
                decisions_list[:10] if decisions_list else ([latest_decision] if latest_decision else [])
            ),
            "classification": classification,
            "live_gate": live_gate,
            "deconflict_reason": deconflict_reason,
        },
        source="redis:v2:orchestrator",
        source_type="static_payload" if not missing else "unavailable",
        timestamp=timestamp,
        missing_fields=missing,
        warnings=["Live trading is BLOCKED -- orchestrator status is read-only"],
        mode="paper",
    )


# ---------------------------------------------------------------------------
# Risk gateway status endpoint
# ---------------------------------------------------------------------------

@router.get("/risk/status")
async def get_risk_status() -> dict[str, Any]:
    """Return the current risk gateway state, active profile, and recent decisions from Redis."""
    endpoint = "/api/v2/risk/status"

    gateway_latest_raw = _read_v2_redis_json_or_list("v2:risk:gateway:latest")
    active_profile_raw = _read_v2_redis_json_or_list("v2:risk:active_profile")
    heartbeat_raw = _read_v2_redis_json_or_list("v2:risk:gateway:heartbeat")
    # Prefer paper_online_decisions (has risk_action, symbol, risk_reason_code, live_blocked)
    decisions_raw = (
        _read_v2_redis_json_or_list("v2:risk:paper_online_decisions")
        or _read_v2_redis_json_or_list("v2:risk:gateway:decisions")
        or _read_v2_redis_json_or_list("v2:risk:decisions")
    )

    gateway_latest: dict[str, Any] | None = (
        gateway_latest_raw if isinstance(gateway_latest_raw, dict) else None
    )
    active_profile: dict[str, Any] | None = (
        active_profile_raw if isinstance(active_profile_raw, dict) else None
    )
    heartbeat: dict[str, Any] | None = heartbeat_raw if isinstance(heartbeat_raw, dict) else None
    recent_decisions = _parse_redis_list_or_json(decisions_raw)

    missing: list[str] = []
    if not gateway_latest:
        missing.append("risk_gateway_latest")
    if active_profile is None:
        missing.append("risk_active_profile")
    if heartbeat is None:
        missing.append("risk_gateway_heartbeat")
    # Only fall back to artifact files when the heartbeat is ALSO missing —
    # if we have the heartbeat we have enough live data to serve the page.
    if heartbeat is None and missing:
        artifact_response = _risk_status_from_runtime_artifacts(endpoint)
        if artifact_response is not None:
            return artifact_response

    timestamp = None
    if heartbeat:
        timestamp = (
            heartbeat.get("finished_at")
            or heartbeat.get("started_at")
            or heartbeat.get("last_run_ts")
        )
    if timestamp is None and recent_decisions:
        timestamp = recent_decisions[0].get("generated_utc") or recent_decisions[0].get("created_at")

    profile_summary: dict[str, Any] | None = None
    if active_profile:
        profile_summary = {
            "profile_id": active_profile.get("profile_id"),
            "profile_name": active_profile.get("profile_name"),
            "fields": active_profile.get("fields") or {},
        }

    latest_gw: dict[str, Any] = {}
    if gateway_latest:
        latest_gw = gateway_latest
    elif heartbeat:
        latest_gw = {
            "classification": heartbeat.get("classification"),
            "live_gate": heartbeat.get("live_gate"),
            "approves_live": heartbeat.get("approves_live"),
            "live_blocked": heartbeat.get("live_blocked"),
        }

    denials_breakdown: dict[str, Any] = (heartbeat.get("denials_breakdown") or {}) if heartbeat else {}

    _live_gate = (heartbeat.get("current_gate_state") or heartbeat.get("live_gate") if heartbeat else None) or "blocked_human_only"
    _live_blocked = not bool(heartbeat.get("approves_live", False)) if heartbeat else True
    _fail_closed = bool(heartbeat.get("fail_closed", True)) if heartbeat else True

    # Normalize decisions for the admin-risk decisions table
    _normalized_decisions: list[dict[str, Any]] = []
    for _d in recent_decisions[:50]:
        _normalized_decisions.append({
            "risk_decision_id": _d.get("risk_decision_id") or _d.get("decision_id"),
            "symbol": _d.get("symbol"),
            "risk_action": _d.get("risk_action") or _d.get("action"),
            "risk_reason_code": _d.get("risk_reason_code") or _d.get("denial_reason") or _d.get("reason_code"),
            "live_blocked": not bool(_d.get("approves_live", False)),
            "generated_at": _d.get("generated_at") or _d.get("decision_time"),
        })

    _resp = _base_response(
        endpoint=endpoint,
        data={
            "active_profile": profile_summary,
            "latest_gateway_result": latest_gw,
            "heartbeat": {
                "worker_id": heartbeat.get("worker_id") if heartbeat else None,
                "started_at": heartbeat.get("started_at") if heartbeat else None,
                "finished_at": heartbeat.get("finished_at") if heartbeat else None,
                "decisions_processed_total": heartbeat.get("decisions_processed_total") if heartbeat else None,
                "live_gate": _live_gate,
                "live_blocked": _live_blocked,
                "classification": heartbeat.get("classification") if heartbeat else None,
                "fail_closed": _fail_closed,
                "approves_live": heartbeat.get("approves_live") if heartbeat else None,
                "places_real_order": heartbeat.get("places_real_order") if heartbeat else None,
            } if heartbeat else None,
            "recent_decisions": _normalized_decisions,
            "denials_breakdown": denials_breakdown,
        },
        source="redis:v2:risk",
        source_type="static_payload" if not missing else "unavailable",
        timestamp=timestamp,
        missing_fields=missing,
        warnings=["Live trading is BLOCKED -- risk gateway status is read-only"],
        mode="paper",
    )
    # Hoist convenience fields to outer envelope so admin-risk frontend can read them directly
    _resp["live_gate"] = _live_gate
    _resp["live_blocked"] = _live_blocked
    _resp["fail_closed"] = _fail_closed
    _resp["recent_decisions"] = _normalized_decisions
    _resp["active_profile"] = profile_summary
    # Risk gateway heartbeat updates once per cycle (~5-15 min), not per-second.
    # Override stale if classification confirms gateway is live and lag < 15 min.
    _hb_classification = (heartbeat.get("classification") or "") if heartbeat else ""
    _lag = _resp.get("lag_ms")
    if _hb_classification in ("V2_RISK_GATEWAY_LIVE_OK", "RUNTIME_ARTIFACT_CURRENT", "V2_RISK_GATEWAY_OK"):
        _resp["stale"] = _lag is None or _lag > 900_000
    return _resp


# ---------------------------------------------------------------------------
# Backtest API endpoints
# ---------------------------------------------------------------------------

_BACKTEST_RESULT_TTL = 7 * 24 * 3600  # 7 days (matches runner)
_BACKTEST_VENV_PY = os.environ.get(
    "V2_VENV_PYTHON",
    "/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python3",
)
_BACKTEST_BACKEND_DIR = os.environ.get(
    "V2_BACKEND_DIR",
    "/home/wali/Desktop/AI BOT REBUILD/v2/backend",
)
_VALID_BT_TIMEFRAMES = {"1m", "3m", "5m", "15m", "1h", "4h", "1d", "1w"}


def _safe_bt_symbol(symbol: str) -> str | None:
    cleaned = "".join(ch for ch in symbol.upper() if ch.isalnum())
    return cleaned if cleaned else None


def _bt_redis_scan_results(
    client: Any,
    symbol: str | None,
    timeframe: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Scan v2:backtest:results:* and return sorted summaries."""
    if client is None:
        return []
    try:
        pattern = "v2:backtest:results:*"
        keys: list[str] = []
        cursor = 0
        while True:
            cursor, batch = client.scan(cursor=cursor, match=pattern, count=200)
            keys.extend(batch)
            if cursor == 0:
                break
            if len(keys) > 2000:
                break
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for key in keys:
        # key format: v2:backtest:results:{sym}:{tf}:{run_id}
        parts = key.split(":")
        if len(parts) < 6:
            continue
        key_sym = parts[3]
        key_tf = parts[4]
        if symbol and key_sym.upper() != symbol.upper():
            continue
        if timeframe and key_tf != timeframe:
            continue
        try:
            raw = client.get(key)
            if not raw:
                continue
            data = json.loads(raw)
        except Exception:
            continue
        # Return compact summary (skip trades/equity_curve for list view)
        rows.append({
            "run_id": data.get("run_id"),
            "symbol": data.get("symbol"),
            "timeframe": data.get("timeframe"),
            "started_at": data.get("started_at"),
            "completed_at": data.get("completed_at"),
            "status": data.get("status"),
            "summary": data.get("summary"),
            "params": data.get("params"),
        })

    rows.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    return rows[:limit]


@router.post("/backtest/run")
async def trigger_backtest(
    symbol: str = Query(default="BTCUSDT"),
    timeframe: str = Query(default="1h"),
    lookback: int = Query(default=100, ge=10, le=500),
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Triggers a backtest run via subprocess. Returns run_id immediately.

    Safe invariants:
    - Never places exchange orders.
    - Never mutates trading state.
    - Only writes to v2:backtest:* Redis namespace.
    """
    endpoint = "/api/v2/backtest/run"

    sym = _safe_bt_symbol(symbol)
    if not sym:
        return _unavailable(
            endpoint=endpoint,
            missing_fields=["symbol"],
            warning="Invalid symbol",
        )
    tf = timeframe if timeframe in _VALID_BT_TIMEFRAMES else None
    if not tf:
        return _unavailable(
            endpoint=endpoint,
            missing_fields=["timeframe"],
            warning=f"Invalid timeframe. Valid: {sorted(_VALID_BT_TIMEFRAMES)}",
        )

    started_at_ms = int(time.time() * 1000)
    run_id = f"bt_{sym}_{tf}_{started_at_ms}"

    # Write pending status to Redis before launching subprocess
    def _write_pending() -> None:
        client = get_redis()
        if client is None:
            return
        try:
            client.set(
                f"v2:backtest:pending:{run_id}",
                json.dumps({
                    "run_id": run_id,
                    "status": "running",
                    "symbol": sym,
                    "timeframe": tf,
                }),
                ex=3600,
            )
        except Exception:
            pass

    await run_in_threadpool(_write_pending)

    # Launch subprocess — fire-and-forget
    def _launch_subprocess() -> None:
        env = {**os.environ, "PYTHONPATH": _BACKTEST_BACKEND_DIR}
        cmd = [
            _BACKTEST_VENV_PY,
            "-m",
            "app.cli.v2_backtest_runner",
            "--symbol", sym,
            "--timeframe", tf,
            "--lookback-candles", str(lookback),
            "--run-id", run_id,
        ]
        try:
            subprocess.Popen(
                cmd,
                cwd=_BACKTEST_BACKEND_DIR,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            # Best-effort: log to stderr but don't raise
            print(f"[backtest trigger] Popen failed: {exc}", file=sys.stderr)

    await run_in_threadpool(_launch_subprocess)

    return {
        "accepted": True,
        "run_id": run_id,
        "symbol": sym,
        "timeframe": tf,
        "lookback_candles": lookback,
        "status": "running",
        "endpoint": endpoint,
        "received_at": _utc_now(),
        "warnings": [
            "No exchange orders are placed",
            "Gate status: blocked_human_only",
        ],
    }


@router.get("/backtest/results")
async def list_backtest_results(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Returns list of all backtest results from Redis, newest first."""
    endpoint = "/api/v2/backtest/results"

    sym = _safe_bt_symbol(symbol) if symbol else None
    tf = timeframe if timeframe in _VALID_BT_TIMEFRAMES else None
    if timeframe and not tf:
        return _unavailable(
            endpoint=endpoint,
            missing_fields=["timeframe"],
            warning=f"Invalid timeframe filter. Valid: {sorted(_VALID_BT_TIMEFRAMES)}",
        )

    def _fetch() -> list[dict[str, Any]]:
        client = get_redis()
        return _bt_redis_scan_results(client, sym, tf, limit)

    rows = await run_in_threadpool(_fetch)

    return _base_response(
        endpoint=endpoint,
        data={
            "results": rows,
            "count": len(rows),
            "filters": {"symbol": sym, "timeframe": tf},
        },
        source="redis:v2:backtest:results:*",
        source_type="api",
        timestamp=_utc_now(),
        missing_fields=[] if rows else ["results"],
        warnings=[] if rows else ["No backtest results found in Redis"],
    )


@router.get("/backtest/results/{run_id}")
async def get_backtest_result(
    run_id: str,
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    """Returns full backtest result including equity curve and trades."""
    endpoint = f"/api/v2/backtest/results/{run_id}"

    # Sanitise run_id to prevent key injection
    safe_run_id = "".join(ch for ch in run_id if ch.isalnum() or ch in "_-")
    if not safe_run_id:
        return _unavailable(
            endpoint=endpoint,
            missing_fields=["run_id"],
            warning="Invalid run_id",
        )

    def _fetch() -> dict[str, Any] | None:
        client = get_redis()
        if client is None:
            return None
        # Scan for the key since we don't know symbol/timeframe from run_id alone
        try:
            cursor = 0
            while True:
                cursor, batch = client.scan(
                    cursor=cursor,
                    match=f"v2:backtest:results:*:{safe_run_id}",
                    count=200,
                )
                for key in batch:
                    raw = client.get(key)
                    if raw:
                        try:
                            return json.loads(raw)
                        except Exception:
                            pass
                if cursor == 0:
                    break
        except Exception:
            pass
        return None

    data = await run_in_threadpool(_fetch)
    if data is None:
        return _unavailable(
            endpoint=endpoint,
            missing_fields=["result"],
            warning=f"Backtest result not found or expired: {safe_run_id}",
        )

    return _base_response(
        endpoint=endpoint,
        data=data,
        source=f"redis:v2:backtest:results:*:{safe_run_id}",
        source_type="api",
        timestamp=data.get("completed_at"),
        missing_fields=[],
        warnings=[],
    )


@router.get("/backtest/status/{run_id}")
async def get_backtest_status(run_id: str) -> dict[str, Any]:
    """Check if a backtest run is still pending/running/complete/expired."""
    endpoint = f"/api/v2/backtest/status/{run_id}"

    safe_run_id = "".join(ch for ch in run_id if ch.isalnum() or ch in "_-")
    if not safe_run_id:
        return {
            "run_id": run_id,
            "status": "invalid",
            "endpoint": endpoint,
            "received_at": _utc_now(),
        }

    def _check_status() -> str:
        client = get_redis()
        if client is None:
            return "unknown"
        # Check pending key
        try:
            pending = client.get(f"v2:backtest:pending:{safe_run_id}")
            if pending:
                return "running"
        except Exception:
            pass
        # Check results key
        try:
            cursor = 0
            while True:
                cursor, batch = client.scan(
                    cursor=cursor,
                    match=f"v2:backtest:results:*:{safe_run_id}",
                    count=200,
                )
                if batch:
                    return "complete"
                if cursor == 0:
                    break
        except Exception:
            pass
        return "not_found"

    status = await run_in_threadpool(_check_status)

    return {
        "run_id": safe_run_id,
        "status": status,
        "endpoint": endpoint,
        "received_at": _utc_now(),
    }


# ── Paper Trading Status ──────────────────────────────────────────────────────

def _paper_positions_with_last_known_fallback(positions_raw: list[Any]) -> tuple[list[Any], str, list[str]]:
    warnings: list[str] = []
    now = time.monotonic()
    if positions_raw:
        with PAPER_ACTIVITY_CACHE_LOCK:
            PAPER_ACTIVITY_LAST_NON_EMPTY_POSITIONS["positions"] = positions_raw
            PAPER_ACTIVITY_LAST_NON_EMPTY_POSITIONS["updated_monotonic"] = now
            PAPER_ACTIVITY_LAST_NON_EMPTY_POSITIONS["updated_at"] = _utc_now()
        return positions_raw, "redis:v2:paper:positions", warnings

    with PAPER_ACTIVITY_CACHE_LOCK:
        cached_positions = list(PAPER_ACTIVITY_LAST_NON_EMPTY_POSITIONS.get("positions") or [])
        updated_monotonic = float(PAPER_ACTIVITY_LAST_NON_EMPTY_POSITIONS.get("updated_monotonic") or 0.0)
        updated_at = PAPER_ACTIVITY_LAST_NON_EMPTY_POSITIONS.get("updated_at")
    cache_age_seconds = now - updated_monotonic if updated_monotonic else None
    if cached_positions and cache_age_seconds is not None and cache_age_seconds <= 90:
        warnings.append(
            "Current v2:paper:positions snapshot was empty; showing last-known open positions for transient refresh stability"
        )
        for row in cached_positions:
            if isinstance(row, dict):
                row["last_known_position"] = True
                row["last_known_position_updated_at"] = updated_at
                row["last_known_position_age_seconds"] = round(cache_age_seconds, 1)
        return cached_positions, "memory:last_non_empty_v2_paper_positions", warnings
    return positions_raw, "redis:v2:paper:positions.empty", warnings


def _paper_intents_from_redis(client: Any) -> list[dict[str, Any]]:
    intents_raw = client.get("v2:paper:intents")
    intents: Any = json.loads(intents_raw) if intents_raw else []
    if isinstance(intents, dict):
        intents = list(intents.values())
    if not isinstance(intents, list):
        return []
    return [row for row in intents if isinstance(row, dict)]


def _paper_fills_from_intents(intents: list[dict[str, Any]], *, limit: int = 500) -> list[dict[str, Any]]:
    fills: list[dict[str, Any]] = []
    for intent in intents:
        fill_price = _float(intent.get("fill_price"))
        if fill_price is None:
            continue
        fills.append({
            "execution_id": intent.get("intent_id") or intent.get("execution_intent_id"),
            "symbol": str(intent.get("symbol") or ""),
            "side": str(intent.get("side") or "").upper(),
            "fill_price": fill_price,
            "entry_price": _float(intent.get("entry_price")),
            "quantity": _float(intent.get("quantity")),
            "notional_usd": _float(intent.get("notional_usdt")) or _float(intent.get("notional")),
            "fee": _float(intent.get("fee_usdt")),
            "slippage": _float(intent.get("slippage_bps")),
            "timeframe": intent.get("timeframe"),
            "strategy_id": intent.get("strategy_id"),
            "model_id": intent.get("model_id"),
            "confidence": _float(intent.get("confidence_calibrated")),
            "market_regime": intent.get("market_regime_at_entry"),
            "risk_result": "Paper fill accepted",
            "paper_only": True,
            "places_real_order": bool(intent.get("places_real_order")),
            "filled_at": intent.get("fill_price_utc") or intent.get("generated_utc") or intent.get("generated_at"),
            "created_at": intent.get("generated_utc") or intent.get("generated_at"),
        })
    fills.sort(key=lambda x: x.get("filled_at") or "", reverse=True)
    return fills[:limit]


def _paper_orders_from_intents(intents: list[dict[str, Any]], *, limit: int = 500) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    orders: list[dict[str, Any]] = []
    open_orders: list[dict[str, Any]] = []
    for intent in intents:
        fill_price = _float(intent.get("fill_price"))
        action = str(intent.get("intent_action") or intent.get("action") or "").lower()
        exchange_allowed = intent.get("exchange_order_allowed") is True
        blocked = (
            exchange_allowed is False
            or "blocked" in action
            or str(intent.get("risk_result") or "").lower().startswith("deny")
        )
        status = "filled" if fill_price is not None else "blocked" if blocked else "open"
        row = {
            "order_id": intent.get("intent_id") or intent.get("execution_intent_id"),
            "time": intent.get("generated_utc") or intent.get("generated_at"),
            "created_at": intent.get("generated_utc") or intent.get("generated_at"),
            "symbol": intent.get("symbol"),
            "side": str(intent.get("side") or "").upper(),
            "type": "paper_intent",
            "price": fill_price or _float(intent.get("entry_price")) or _float(intent.get("price_target")),
            "size": _float(intent.get("quantity")),
            "quantity": _float(intent.get("quantity")),
            "filled": _float(intent.get("quantity")) if fill_price is not None else 0,
            "status": status,
            "mode": "paper",
            "source": "v2:paper:intents",
            "paper_only": True,
            "exchange_order_allowed": False,
            "places_real_order": False,
            "risk_decision_id": intent.get("risk_decision_id"),
            "signal_id": intent.get("signal_id"),
            "reason": intent.get("risk_result") or intent.get("allocator_reason") or intent.get("paper_fill_gate_status"),
        }
        orders.append(row)
        if status == "open":
            open_orders.append(row)
    orders.sort(key=lambda x: x.get("time") or "", reverse=True)
    open_orders.sort(key=lambda x: x.get("time") or "", reverse=True)
    return open_orders[:limit], orders[:limit]


def _paper_audit_events_from_intents(intents: list[dict[str, Any]], *, limit: int = 200) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for intent in intents[:limit]:
        events.append({
            "event_id": intent.get("intent_id") or intent.get("execution_intent_id"),
            "time": intent.get("generated_utc") or intent.get("generated_at"),
            "symbol": intent.get("symbol"),
            "event_type": "PAPER_FILL_ACCEPTED" if _float(intent.get("fill_price")) is not None else "PAPER_INTENT_BLOCKED",
            "source": "v2:paper:intents",
            "paper_only": True,
            "places_real_order": False,
            "risk_decision_id": intent.get("risk_decision_id"),
            "signal_id": intent.get("signal_id"),
            "reason": intent.get("risk_result") or intent.get("allocator_reason") or intent.get("paper_fill_gate_status"),
        })
    return events


def _client_redis_json(client: Any, key: str) -> dict[str, Any]:
    try:
        raw = client.get(key)
    except Exception:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _paper_market_price_candidate(
    *,
    source_key: str,
    source_field: str,
    price: Any,
    generated_at: str | None,
    priority: int,
) -> dict[str, Any] | None:
    parsed_price = _float(price)
    if parsed_price is None or parsed_price <= 0:
        return None
    generated_epoch = _epoch_seconds_from_iso(generated_at)
    age_seconds = None
    if generated_epoch is not None:
        age_seconds = max(0.0, datetime.now(UTC).timestamp() - generated_epoch)
    return {
        "price": parsed_price,
        "source": f"{source_key}.{source_field}",
        "source_key": source_key,
        "generated_at": generated_at,
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "priority": priority,
    }


def _paper_live_market_price(client: Any, symbol: str) -> dict[str, Any]:
    sym = symbol.upper()
    candidates: list[dict[str, Any]] = []

    wsds_key = f"v2:market:coinapi:wsds:{sym}"
    wsds = _client_redis_json(client, wsds_key)
    wsds_generated = (
        _iso_from_ms(wsds.get("generated_at"))
        or _iso_from_ms(wsds.get("updated_ts_ms"))
        or _iso_from_ms(wsds.get("source_event_time"))
        or _iso_from_ms(wsds.get("available_at"))
    )
    for field in ("microprice", "mid_px"):
        candidate = _paper_market_price_candidate(
            source_key=wsds_key,
            source_field=field,
            price=wsds.get(field),
            generated_at=wsds_generated,
            priority=0,
        )
        if candidate:
            candidates.append(candidate)
            break

    funding_key = f"v2:market:funding:{sym}"
    funding_direct = _client_redis_json(client, funding_key)
    funding_candidate = _paper_market_price_candidate(
        source_key=funding_key,
        source_field="markPrice",
        price=funding_direct.get("markPrice") or funding_direct.get("mark_price"),
        generated_at=_iso_from_ms(funding_direct.get("time")) or _timestamp_from_redis_payload(funding_direct),
        priority=1,
    )
    if funding_candidate:
        candidates.append(funding_candidate)

    for key, priority in (
        (f"v2:market:orderbook:binance:{sym}", 2),
        (f"v2:market:orderbook:{sym}", 3),
    ):
        book = _client_redis_json(client, key)
        bids = book.get("bids") if isinstance(book.get("bids"), list) else []
        asks = book.get("asks") if isinstance(book.get("asks"), list) else []
        bid = _float(bids[0][0]) if bids and isinstance(bids[0], list) and bids[0] else None
        ask = _float(asks[0][0]) if asks and isinstance(asks[0], list) and asks[0] else None
        mid = (bid + ask) / 2 if bid is not None and ask is not None and ask >= bid else None
        candidate = _paper_market_price_candidate(
            source_key=key,
            source_field="mid_bid_ask",
            price=mid,
            generated_at=_iso_from_ms(book.get("T")) or _iso_from_ms(book.get("E")),
            priority=priority,
        )
        if candidate:
            candidates.append(candidate)

    source_key = f"v2:market:prices:{sym}"
    payload = _client_redis_json(client, source_key)

    funding = payload.get("funding") if isinstance(payload.get("funding"), dict) else {}
    ticker = payload.get("ticker_24hr") if isinstance(payload.get("ticker_24hr"), dict) else {}
    generated_at = (
        _iso_from_ms(funding.get("time"))
        or _iso_from_ms(ticker.get("closeTime"))
        or str(payload.get("fetched_utc") or "") or None
    )
    for source_field, price in (
        ("funding.markPrice", funding.get("markPrice")),
        ("ticker_24hr.lastPrice", ticker.get("lastPrice")),
        ("ticker_24hr.weightedAvgPrice", ticker.get("weightedAvgPrice")),
        ("ticker_24hr.bidPrice", ticker.get("bidPrice")),
    ):
        candidate = _paper_market_price_candidate(
            source_key=source_key,
            source_field=source_field,
            price=price,
            generated_at=generated_at,
            priority=4,
        )
        if candidate:
            candidates.append(candidate)
            break

    if not candidates:
        return {"price": None, "source": source_key, "source_key": source_key, "generated_at": None, "age_seconds": None}
    candidates.sort(key=lambda item: (
        item["age_seconds"] is None,
        item["age_seconds"] if item["age_seconds"] is not None else float("inf"),
        item["priority"],
    ))
    return candidates[0]


def _paper_position_side_multiplier(side: str) -> int:
    side_upper = side.upper()
    if "SHORT" in side_upper or side_upper in {"SELL", "S"}:
        return -1
    return 1


def _paper_position_stored_mark_candidate(row: dict[str, Any]) -> dict[str, Any] | None:
    mark_price = _float(row.get("last_mark_price") or row.get("mark_price") or row.get("current_price") or row.get("latest_price"))
    if mark_price is None or mark_price <= 0:
        return None
    generated_at = (
        row.get("last_mark_est")
        or row.get("last_mark_utc")
        or row.get("mark_price_generated_at")
        or row.get("latest_price_generated_at")
        or row.get("last_equity_update_utc")
        or row.get("generated_utc")
        or row.get("generated_at")
    )
    generated_at_str = str(generated_at) if generated_at else None
    generated_epoch = _epoch_seconds_from_iso(generated_at_str)
    age_seconds = None
    if generated_epoch is not None:
        age_seconds = max(0.0, datetime.now(UTC).timestamp() - generated_epoch)
    source = row.get("mark_price_source") or row.get("latest_price_source") or "v2:paper:positions.last_mark_price"
    return {
        "price": mark_price,
        "source": str(source),
        "source_key": str(row.get("mark_price_source_key") or row.get("source") or "v2:paper:positions"),
        "generated_at": generated_at_str,
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "priority": 4,
    }


def _first_positive_price_with_source(
    row: dict[str, Any],
    candidates: list[tuple[str, str]],
) -> tuple[float | None, str | None]:
    for field, source in candidates:
        value = _float(row.get(field))
        if value is not None and value > 0:
            return value, source
    return None, None


def _signal_basis_payload(payload: dict[str, Any]) -> dict[str, Any]:
    active = payload.get("active_signal")
    if isinstance(active, dict):
        basis = {**payload, **active}
        lineage = active.get("lineage_summary")
        if isinstance(lineage, dict):
            basis["lineage_summary"] = lineage
        return basis
    allocation = payload.get("adaptive_allocation")
    if isinstance(allocation, dict):
        basis = {**payload, **allocation}
        if "decision_reasoning" not in basis and isinstance(payload.get("decision_reasoning"), dict):
            basis["decision_reasoning"] = payload["decision_reasoning"]
        return basis
    return payload


def _nested_lineage_text(row: dict[str, Any], key: str) -> Any:
    lineage = row.get("lineage_summary")
    if isinstance(lineage, dict):
        return lineage.get(key)
    return None


def _position_reason_text(row: dict[str, Any], fallback: dict[str, Any] | None = None) -> Any:
    other = fallback or {}
    nested_reasoning = row.get("decision_reasoning") if isinstance(row.get("decision_reasoning"), dict) else {}
    return (
        row.get("reason")
        or row.get("explanation")
        or row.get("blocked_reason")
        or row.get("entry_reason")
        or row.get("close_reason")
        or row.get("exit_reason")
        or row.get("risk_reason")
        or row.get("risk_reason_code")
        or row.get("risk_result")
        or row.get("capital_allocation_reason")
        or row.get("allocator_decision")
        or row.get("decision")
        or row.get("paper_fill_gate_status")
        or row.get("actionable_reason_code")
        or row.get("paper_fill_status")
        or row.get("signal_reason")
        or _nested_lineage_text(row, "orchestrator_decision")
        or nested_reasoning.get("reason")
        or nested_reasoning.get("summary")
        or other.get("reason")
        or other.get("entry_reason")
        or other.get("close_reason")
        or other.get("exit_reason")
        or other.get("risk_result")
        or other.get("paper_fill_gate_status")
    )


def _row_position_reasoning(row: dict[str, Any], *, source: str) -> dict[str, Any] | None:
    basis = _signal_basis_payload(row)
    reason = _position_reason_text(basis)
    if not any((
        basis.get("signal_id"),
        basis.get("prediction_id"),
        _nested_lineage_text(basis, "signal_id"),
        _nested_lineage_text(basis, "prediction_id"),
        basis.get("action"),
        basis.get("proposed_action"),
        basis.get("selected_action"),
        basis.get("side"),
        reason,
    )):
        return None
    return {
        "source": source,
        "signal_id": basis.get("signal_id") or _nested_lineage_text(basis, "signal_id"),
        "prediction_id": basis.get("prediction_id") or _nested_lineage_text(basis, "prediction_id"),
        "timeframe": basis.get("timeframe"),
        "action": basis.get("action") or basis.get("proposed_action") or basis.get("selected_action") or basis.get("side") or basis.get("direction"),
        "confidence": _float(basis.get("confidence") or basis.get("confidence_calibrated") or basis.get("model_confidence")),
        "risk_state": basis.get("risk_state") or basis.get("risk_status") or basis.get("risk_decision") or _nested_lineage_text(basis, "risk_state"),
        "paper_fill_status": basis.get("paper_fill_status") or basis.get("actionable_reason_code") or _nested_lineage_text(basis, "paper_state") or basis.get("paper_fill_allowed"),
        "market_regime": basis.get("market_regime") or basis.get("market_regime_at_entry"),
        "expected_move_bps": _float(basis.get("expected_move_bps") or basis.get("expected_move_after_cost_bps")),
        "data_coverage": _float(basis.get("data_coverage_percent") or basis.get("data_coverage")),
        "reason": reason,
        "available_at": basis.get("available_at"),
        "decision_time": basis.get("decision_time"),
        "generated_at": basis.get("generated_at") or basis.get("generated_utc") or basis.get("published_at"),
        "model_version": basis.get("model_version") or basis.get("model_id"),
    }


def _position_reasoning_has_decision_basis(reasoning: dict[str, Any] | None) -> bool:
    if not isinstance(reasoning, dict):
        return False
    return any((
        reasoning.get("signal_id"),
        reasoning.get("prediction_id"),
        reasoning.get("reason"),
        reasoning.get("confidence") is not None,
        reasoning.get("risk_state"),
        reasoning.get("paper_fill_status"),
        reasoning.get("market_regime"),
        reasoning.get("expected_move_bps") is not None,
        reasoning.get("data_coverage") is not None,
        reasoning.get("model_version"),
    ))


def _latest_position_signal_reasoning(
    client: Any,
    symbol: str,
    row: dict[str, Any],
    *,
    row_source: str = "v2:paper:positions",
) -> dict[str, Any] | None:
    sym = symbol.upper()
    row_basis = _signal_basis_payload(row)
    row_reasoning = _row_position_reasoning(row, source=row_source)
    row_signal_id = str(row_basis.get("signal_id") or _nested_lineage_text(row_basis, "signal_id") or "")
    row_prediction_id = str(row_basis.get("prediction_id") or _nested_lineage_text(row_basis, "prediction_id") or "")
    if row_source == "v2:paper:closed_trades" and not row_signal_id and not row_prediction_id:
        return row_reasoning

    candidates: list[dict[str, Any]] = []
    key_candidates = [f"v2:signals:latest:{sym}", f"v2:signals:paper:{sym}"]
    row_timeframe = str(row_basis.get("timeframe") or "").lower()
    if row_timeframe:
        key_candidates.extend((
            f"v2:signals:latest:{sym}:{row_timeframe}",
            f"v2:signals:paper:{sym}:{row_timeframe}",
        ))
    seen_keys: set[str] = set()
    for key in key_candidates:
        if key in seen_keys:
            continue
        seen_keys.add(key)
        payload = _client_redis_json(client, key)
        if payload:
            payload["_source_key"] = key
            candidates.append(payload)
    if not candidates:
        return row_reasoning
    if row_signal_id or row_prediction_id:
        matching = [
            candidate for candidate in candidates
            for basis in [_signal_basis_payload(candidate)]
            if (
                row_signal_id
                and str(basis.get("signal_id") or _nested_lineage_text(basis, "signal_id") or "") == row_signal_id
            ) or (
                row_prediction_id
                and str(basis.get("prediction_id") or _nested_lineage_text(basis, "prediction_id") or "") == row_prediction_id
            )
        ]
        if matching:
            candidates = matching
        else:
            return row_reasoning
    else:
        if row_timeframe:
            matching_timeframe = [
                candidate for candidate in candidates
                if str(_signal_basis_payload(candidate).get("timeframe") or "").lower() == row_timeframe
            ]
            if matching_timeframe:
                candidates = matching_timeframe
            elif _position_reasoning_has_decision_basis(row_reasoning):
                return row_reasoning
        elif (
            row_source in {"v2:paper:positions", "v2:paper:closed_trades"}
            and _position_reasoning_has_decision_basis(row_reasoning)
        ):
            return row_reasoning

    def _candidate_time(candidate: dict[str, Any]) -> float:
        basis = _signal_basis_payload(candidate)
        for key in ("available_at", "decision_time", "generated_at", "published_at", "generated_utc"):
            parsed = _epoch_seconds_from_iso(str(basis.get(key))) if basis.get(key) else None
            if parsed is not None:
                return parsed
        return 0.0

    candidates.sort(key=_candidate_time, reverse=True)
    signal = candidates[0]
    basis = _signal_basis_payload(signal)
    reason = _position_reason_text(basis, row)
    return {
        "source": signal.get("_source_key"),
        "signal_id": basis.get("signal_id") or _nested_lineage_text(basis, "signal_id") or row.get("signal_id"),
        "prediction_id": basis.get("prediction_id") or _nested_lineage_text(basis, "prediction_id") or row.get("prediction_id"),
        "timeframe": basis.get("timeframe") or row.get("timeframe"),
        "action": basis.get("action") or basis.get("proposed_action") or basis.get("selected_action") or basis.get("side") or basis.get("direction") or row.get("side"),
        "confidence": _float(basis.get("confidence") or basis.get("confidence_calibrated") or basis.get("model_confidence")),
        "risk_state": basis.get("risk_state") or basis.get("risk_status") or basis.get("risk_decision") or _nested_lineage_text(basis, "risk_state"),
        "paper_fill_status": basis.get("paper_fill_status") or basis.get("actionable_reason_code") or _nested_lineage_text(basis, "paper_state") or row.get("paper_fill_allowed"),
        "market_regime": basis.get("market_regime") or basis.get("market_regime_at_entry") or row.get("market_regime_at_entry"),
        "expected_move_bps": _float(basis.get("expected_move_bps") or basis.get("expected_move_after_cost_bps")),
        "data_coverage": _float(basis.get("data_coverage_percent") or basis.get("data_coverage")),
        "reason": reason,
        "available_at": basis.get("available_at"),
        "decision_time": basis.get("decision_time"),
        "generated_at": basis.get("generated_at") or basis.get("generated_utc") or basis.get("published_at"),
        "model_version": basis.get("model_version") or basis.get("model_id") or row.get("model_id"),
    }


def _select_freshest_paper_mark(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [
        candidate
        for candidate in candidates
        if _float(candidate.get("price")) is not None and (_float(candidate.get("price")) or 0) > 0
    ]
    if not valid:
        return {
            "price": None,
            "source": "MISSING_PAPER_MARK_PRICE",
            "source_key": None,
            "generated_at": None,
            "age_seconds": None,
            "priority": 999,
        }
    valid.sort(
        key=lambda item: (
            item.get("age_seconds") is None,
            item.get("age_seconds") if item.get("age_seconds") is not None else float("inf"),
            item.get("priority", 999),
        )
    )
    return valid[0]


def _recent_closed_trade_rows(rows: list[Any], limit: int = 200) -> list[dict[str, Any]]:
    projected = [row for row in rows if isinstance(row, dict)]
    projected.sort(
        key=lambda row: str(
            row.get("closed_at")
            or row.get("exit_price_utc")
            or row.get("closed_utc")
            or row.get("generated_at")
            or row.get("generated_utc")
            or ""
        ),
        reverse=True,
    )
    return projected[:limit]


def _enrich_paper_positions(
    client: Any,
    positions_raw: list[Any],
    *,
    max_leverage: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    total_unrealized_pnl = 0.0
    total_open_notional = 0.0
    live_mark_count = 0
    stale_mark_count = 0
    missing_mark_count = 0

    for row in positions_raw:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper()
        side_raw = str(row.get("side") or "")
        side = side_raw.upper()
        side_display = side_raw or side
        entry_price, entry_price_source = _first_positive_price_with_source(
            row,
            [
                ("avg_entry_price", "avg_entry_price"),
                ("entry_price", "entry_price"),
                ("paper_entry_price", "paper_entry_price"),
                ("entry_fill_price", "entry_fill_price"),
                ("filled_entry_price", "filled_entry_price"),
                ("entry_avg_price", "entry_avg_price"),
                ("avg_fill_price", "avg_fill_price"),
                ("price_at_entry", "price_at_entry"),
                ("open_price", "open_price"),
                ("fill_price", "fill_price"),
            ],
        )
        qty = _float(row.get("net_quantity") or row.get("quantity"))
        qty_abs = abs(qty) if qty is not None else None
        live_mark = _paper_live_market_price(client, sym) if sym else {}
        mark_candidates = []
        if _float(live_mark.get("price")) is not None:
            mark_candidates.append(live_mark)
        stored_mark = _paper_position_stored_mark_candidate(row)
        if stored_mark is not None:
            mark_candidates.append(stored_mark)
        selected_mark = _select_freshest_paper_mark(mark_candidates)
        mark_price = _float(selected_mark.get("price"))
        mark_source = str(selected_mark.get("source") or "MISSING_PAPER_MARK_PRICE")
        mark_age_seconds = _float(selected_mark.get("age_seconds"))

        if selected_mark.get("source_key") != "v2:paper:positions" and _float(selected_mark.get("price")) is not None:
            live_mark_count += 1
        # 90s threshold: REST price ingestors run every 60s; WSDS sources are <2s.
        # A mark older than 90s is genuinely stale regardless of source.
        if mark_age_seconds is not None and mark_age_seconds > 90:
            stale_mark_count += 1
        if _float(selected_mark.get("price")) is None:
            missing_mark_count += 1

        fallback_pnl = _float(row.get("unrealized_pnl"))
        fallback_bps = _float(row.get("unrealized_pnl_bps"))
        pnl = fallback_pnl
        pnl_bps = fallback_bps
        side_multiplier = _paper_position_side_multiplier(side_raw)
        if entry_price is not None and entry_price > 0 and qty_abs is not None and mark_price is not None:
            move = mark_price - entry_price
            pnl = move * qty_abs * side_multiplier
            pnl_bps = (move / entry_price) * 10000.0 * side_multiplier

        notional_from_mark = qty_abs * mark_price if qty_abs is not None and mark_price is not None else None
        stored_notional = _float(row.get("notional") or row.get("gross_notional") or row.get("notional_usd"))
        notional = notional_from_mark if notional_from_mark is not None else stored_notional
        if pnl is not None:
            total_unrealized_pnl += pnl
        if notional is not None:
            total_open_notional += notional
        reasoning = _latest_position_signal_reasoning(client, sym, row) if sym else None

        positions.append({
            "id": row.get("id") or row.get("position_id"),
            "position_id": row.get("position_id") or row.get("id"),
            "trader_id": row.get("trader_id"),
            "paper_account_id": row.get("paper_account_id"),
            "symbol": sym,
            "side": side_display,
            "net_quantity": qty,
            "quantity": qty,
            "avg_entry_price": entry_price,
            "entry_price": entry_price,
            "entry_price_source": entry_price_source,
            "mark_price": mark_price,
            "last_mark_price": mark_price,
            "current_price": mark_price,
            "mark_price_source": mark_source,
            "mark_price_source_key": selected_mark.get("source_key"),
            "mark_price_generated_at": selected_mark.get("generated_at"),
            "mark_price_age_seconds": mark_age_seconds,
            "mark_price_stale": mark_age_seconds is not None and mark_age_seconds > 90,
            "entry_notional_usd": stored_notional,
            "notional_usd": notional,
            "leverage": max_leverage,
            "unrealized_pnl": round(pnl, 4) if pnl is not None else None,
            "unrealized_pnl_bps": round(pnl_bps, 2) if pnl_bps is not None else None,
            "unrealized_pnl_pct": round(pnl_bps / 10000.0, 6) if pnl_bps is not None else None,
            "timeframe": row.get("timeframe"),
            "strategy_id": row.get("strategy_id"),
            "market_regime_at_entry": row.get("market_regime_at_entry"),
            "position_age_seconds": row.get("position_age_seconds"),
            "opened_est": row.get("opened_est"),
            "opened_utc": row.get("opened_utc") or row.get("opened_est"),
            "paper_fill_allowed": row.get("paper_fill_allowed"),
            "places_real_order": row.get("places_real_order"),
            "hedge_state": row.get("hedge_state"),
            "signal_id": row.get("signal_id") or (reasoning or {}).get("signal_id"),
            "prediction_id": row.get("prediction_id") or (reasoning or {}).get("prediction_id"),
            "decision_reasoning": reasoning,
            "last_known_position": row.get("last_known_position") is True,
            "last_known_position_updated_at": row.get("last_known_position_updated_at"),
            "last_known_position_age_seconds": row.get("last_known_position_age_seconds"),
        })

    return positions, {
        "unrealized_pnl_usd": round(total_unrealized_pnl, 4),
        "total_open_notional": round(total_open_notional, 4),
        "mark_to_market_live": live_mark_count > 0,
        "live_mark_price_count": live_mark_count,
        "stale_mark_price_count": stale_mark_count,
        "missing_mark_price_count": missing_mark_count,
    }


def _load_paper_activity_payload() -> tuple[dict[str, Any], list[str]]:
    client = get_redis()
    warnings: list[str] = []
    if client is None:
        return {
            "positions": [],
            "fills": [],
            "executions": [],
            "open_orders": [],
            "orders": [],
            "order_history": [],
            "audit_events": [],
            "risk_profile": {},
            "summary": {
                "open_position_count": 0,
                "closed_trade_count": 0,
                "realized_pnl_usd": 0.0,
                "unrealized_pnl_usd": 0.0,
                "total_open_notional": 0.0,
                "mark_to_market_live": False,
                "live_mark_price_count": 0,
                "stale_mark_price_count": 0,
                "missing_mark_price_count": 0,
                "position_source_status": "redis_unavailable",
                "position_rows_returned": 0,
                "fills_count": 0,
                "order_history_count": 0,
                "open_order_count": 0,
                "audit_event_count": 0,
            },
            "stream": {
                "source": "v2:paper:* Redis",
                "transport": "websocket_or_http_polling_fallback",
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
            },
        }, ["Redis unavailable for paper activity; returned structured empty paper state"]
    hb_raw = client.get("v2:paper:heartbeat")
    heartbeat: dict[str, Any] = json.loads(hb_raw) if hb_raw else {}

    rp_raw = client.get("v2:risk:active_profile")
    risk_profile: dict[str, Any] = json.loads(rp_raw) if rp_raw else {}
    risk_fields: dict[str, Any] = risk_profile.get("fields", {})
    max_leverage = float(risk_fields.get("max_leverage") or 1.0)

    pos_raw = client.get("v2:paper:positions")
    positions_raw: Any = json.loads(pos_raw) if pos_raw else []
    if isinstance(positions_raw, dict):
        positions_raw = list(positions_raw.values())
    positions_raw, position_source_status, position_warnings = _paper_positions_with_last_known_fallback(
        positions_raw if isinstance(positions_raw, list) else []
    )
    warnings.extend(position_warnings)

    positions, position_metrics = _enrich_paper_positions(
        client,
        positions_raw,
        max_leverage=max_leverage,
    )

    intents = _paper_intents_from_redis(client)
    fills = _paper_fills_from_intents(intents, limit=120)
    open_orders, order_history = _paper_orders_from_intents(intents, limit=150)
    audit_events = _paper_audit_events_from_intents(intents, limit=80)
    data = {
        "positions": positions,
        "fills": fills,
        "executions": fills,
        "open_orders": open_orders,
        "orders": order_history,
        "order_history": order_history,
        "audit_events": audit_events,
        "risk_profile": {
            "profile_id": risk_profile.get("profile_id"),
            "max_leverage": max_leverage,
            "max_notional_per_trade": risk_fields.get("max_notional_per_trade"),
            "max_open_positions": risk_fields.get("max_open_positions"),
            "min_confidence_calibrated": risk_fields.get("min_confidence_calibrated"),
            "max_daily_loss": risk_fields.get("max_daily_loss"),
            "max_drawdown": risk_fields.get("max_drawdown"),
            "max_spread_bps": risk_fields.get("max_spread_bps"),
            "min_expected_move_after_cost_bps": risk_fields.get("min_expected_move_after_cost_bps"),
            "cooldown_seconds": risk_fields.get("cooldown_seconds"),
        },
        "summary": {
            "open_position_count": len(positions),
            "closed_trade_count": int(heartbeat.get("closed_trade_count") or 0),
            "realized_pnl_usd": heartbeat.get("realized_pnl_usd") or 0.0,
            "unrealized_pnl_usd": position_metrics["unrealized_pnl_usd"],
            "total_open_notional": position_metrics["total_open_notional"] or heartbeat.get("total_open_notional"),
            "paper_signals_seen": heartbeat.get("paper_signals_seen"),
            "intents_accepted": heartbeat.get("intents_accepted"),
            "intents_blocked": heartbeat.get("intents_blocked"),
            "persistent_accepted_fill_count": heartbeat.get("persistent_accepted_fill_count"),
            "worker_id": heartbeat.get("worker_id"),
            "started_at": heartbeat.get("started_at"),
            "finished_at": heartbeat.get("finished_at"),
            "mark_to_market_live": position_metrics["mark_to_market_live"],
            "live_mark_price_count": position_metrics["live_mark_price_count"],
            "stale_mark_price_count": position_metrics["stale_mark_price_count"],
            "missing_mark_price_count": position_metrics["missing_mark_price_count"],
            "position_source_status": position_source_status,
            "position_rows_returned": len(positions),
            "fills_count": len(fills),
            "order_history_count": len(order_history),
            "open_order_count": len(open_orders),
            "audit_event_count": len(audit_events),
        },
        "stream": {
            "source": "v2:paper:* Redis",
            "transport": "websocket_or_http_polling_fallback",
            "interval_ms": 1000,
            "live_trading_enabled": False,
            "exchange_mutation_enabled": False,
        },
    }
    return data, warnings


@router.get("/paper/status")
async def get_paper_status(actor: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    endpoint = "/api/v2/paper/status"

    def _load() -> dict[str, Any]:
        try:
            client = get_redis()
            hb_raw = client.get("v2:paper:heartbeat")
            heartbeat: dict[str, Any] = json.loads(hb_raw) if hb_raw else {}

            pos_raw = client.get("v2:paper:positions")
            positions_raw: list[Any] = json.loads(pos_raw) if pos_raw else []
            if isinstance(positions_raw, dict):
                positions_raw = list(positions_raw.values())
            positions_raw, position_source_status, position_warnings = _paper_positions_with_last_known_fallback(
                positions_raw if isinstance(positions_raw, list) else []
            )

            ct_raw = client.get("v2:paper:closed_trades")
            closed_raw: list[Any] = json.loads(ct_raw) if ct_raw else []
            if isinstance(closed_raw, dict):
                closed_raw = list(closed_raw.values())

            rp_raw = client.get("v2:risk:active_profile")
            risk_profile: dict[str, Any] = json.loads(rp_raw) if rp_raw else {}
            risk_fields: dict[str, Any] = risk_profile.get("fields", {})
            max_leverage = float(risk_fields.get("max_leverage") or 1.0)

            positions, position_metrics = _enrich_paper_positions(
                client,
                positions_raw,
                max_leverage=max_leverage,
            )

            trades = []
            for t in _recent_closed_trade_rows(closed_raw, 200):
                entry_price, entry_price_source = _first_positive_price_with_source(
                    t,
                    [
                        ("entry_price", "entry_price"),
                        ("avg_entry_price", "avg_entry_price"),
                        ("paper_entry_price", "paper_entry_price"),
                        ("entry_fill_price", "entry_fill_price"),
                        ("filled_entry_price", "filled_entry_price"),
                        ("entry_avg_price", "entry_avg_price"),
                        ("avg_fill_price", "avg_fill_price"),
                        ("price_at_entry", "price_at_entry"),
                        ("open_price", "open_price"),
                        ("fill_price", "fill_price"),
                    ],
                )
                exit_price, exit_price_source = _first_positive_price_with_source(
                    t,
                    [
                        ("exit_price", "exit_price"),
                        ("paper_exit_price", "paper_exit_price"),
                        ("close_price", "close_price"),
                        ("closing_price", "closing_price"),
                        ("closed_price", "closed_price"),
                        ("close_fill_price", "close_fill_price"),
                        ("closing_fill_price", "closing_fill_price"),
                        ("filled_exit_price", "filled_exit_price"),
                        ("exit_fill_price", "exit_fill_price"),
                        ("avg_exit_price", "avg_exit_price"),
                        ("exit_mark_price", "exit_mark_price"),
                    ],
                )
                sym = str(t.get("symbol") or "").upper()
                reasoning = _latest_position_signal_reasoning(
                    client,
                    sym,
                    t,
                    row_source="v2:paper:closed_trades",
                ) if sym else _row_position_reasoning(t, source="v2:paper:closed_trades")
                trades.append({
                    "close_id": t.get("close_id"),
                    "position_id": t.get("position_id"),
                    "symbol": sym or t.get("symbol"),
                    "side": str(t.get("side", "")).upper(),
                    "entry_price": entry_price,
                    "entry_price_source": entry_price_source,
                    "exit_price": exit_price,
                    "exit_price_source": exit_price_source,
                    "signal_id": t.get("signal_id") or (reasoning or {}).get("signal_id"),
                    "prediction_id": t.get("prediction_id") or (reasoning or {}).get("prediction_id"),
                    "decision_reasoning": reasoning,
                    "realized_pnl_usd": t.get("realized_pnl_usd"),
                    "realized_pnl_bps": t.get("realized_pnl_bps"),
                    "close_reason": t.get("close_reason") or t.get("exit_reason"),
                    "hold_time_seconds": t.get("hold_time_seconds"),
                    "fees": t.get("fees"),
                    "slippage": t.get("slippage"),
                    "winner": t.get("winner"),
                    "strategy_id": t.get("strategy_id"),
                    "market_regime_at_entry": t.get("market_regime_at_entry"),
                    "timeframe": t.get("timeframe"),
                    "exit_price_utc": t.get("exit_price_utc"),
                })
            trades.sort(key=lambda x: x.get("exit_price_utc") or "", reverse=True)

            # Equity curve: cumulative realized PnL from oldest to newest
            trades_asc = list(reversed(trades))
            cumulative = 0.0
            equity_curve: list[dict[str, Any]] = []
            for t in trades_asc:
                cumulative += float(t.get("realized_pnl_usd") or 0)
                equity_curve.append({
                    "t": t.get("exit_price_utc"),
                    "pnl": round(cumulative, 4),
                    "winner": t.get("winner"),
                })

            # Close reason breakdown
            reason_counts: dict[str, int] = {}
            for t in trades:
                r = str(t.get("close_reason") or "UNKNOWN")
                reason_counts[r] = reason_counts.get(r, 0) + 1

            return {
                "positions": positions,
                "closed_trades": trades[:200],
                "equity_curve": equity_curve,
                "reason_breakdown": reason_counts,
                "risk_profile": {
                    "profile_id": risk_profile.get("profile_id"),
                    "max_leverage": max_leverage,
                    "max_notional_per_trade": risk_fields.get("max_notional_per_trade"),
                    "max_open_positions": risk_fields.get("max_open_positions"),
                    "min_confidence_calibrated": risk_fields.get("min_confidence_calibrated"),
                    "max_daily_loss": risk_fields.get("max_daily_loss"),
                    "max_drawdown": risk_fields.get("max_drawdown"),
                    "max_spread_bps": risk_fields.get("max_spread_bps"),
                    "min_expected_move_after_cost_bps": risk_fields.get("min_expected_move_after_cost_bps"),
                    "cooldown_seconds": risk_fields.get("cooldown_seconds"),
                },
                "summary": {
                    "open_position_count": int(heartbeat.get("open_position_count") or len(positions)),
                    "closed_trade_count": int(heartbeat.get("closed_trade_count") or len(closed_raw)),
                    "realized_pnl_usd": heartbeat.get("realized_pnl_usd") or 0.0,
                    "unrealized_pnl_usd": position_metrics["unrealized_pnl_usd"] if positions else (heartbeat.get("unrealized_pnl_usd") or 0.0),
                    "total_open_notional": position_metrics["total_open_notional"] or heartbeat.get("total_open_notional"),
                    "paper_signals_seen": heartbeat.get("paper_signals_seen"),
                    "intents_accepted": heartbeat.get("intents_accepted"),
                    "intents_blocked": heartbeat.get("intents_blocked"),
                    "persistent_accepted_fill_count": heartbeat.get("persistent_accepted_fill_count"),
                    "worker_id": heartbeat.get("worker_id"),
                    "started_at": heartbeat.get("started_at"),
                    "finished_at": heartbeat.get("finished_at"),
                    "mark_to_market_live": position_metrics["mark_to_market_live"],
                    "live_mark_price_count": position_metrics["live_mark_price_count"],
                    "stale_mark_price_count": position_metrics["stale_mark_price_count"],
                    "missing_mark_price_count": position_metrics["missing_mark_price_count"],
                    "position_source_status": position_source_status,
                    "position_rows_returned": len(positions),
                },
                "_warnings": position_warnings,
            }
        except Exception as exc:
            return {
                "error": str(exc),
                "positions": [],
                "closed_trades": [],
                "equity_curve": [],
                "reason_breakdown": {},
                "risk_profile": {},
                "summary": {},
                "_warnings": [str(exc)],
            }

    data = await run_in_threadpool(_load)
    warnings = data.pop("_warnings", []) if isinstance(data, dict) else []
    return _base_response(
        endpoint=endpoint,
        data=data,
        source="v2:paper:* Redis",
        source_type="redis_live",
        timestamp=_utc_now(),
        missing_fields=[],
        warnings=warnings,
        mode="paper",
        trader_context=_trader_context(actor),
    )


@router.get("/paper/runtime-status")
async def get_paper_runtime_status(actor: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    """Real-time paper runtime status synthesized from Redis — replaces stale static file."""

    def _build() -> dict[str, Any]:
        try:
            client = get_redis()
            now = _utc_now()

            hb_raw = client.get("v2:paper:heartbeat")
            hb: dict[str, Any] = json.loads(hb_raw) if hb_raw else {}
            hb_ts = hb.get("heartbeat_generated_at") or hb.get("started_at") or ""
            hb_age = _lag_ms(hb_ts or None)
            heartbeat_fresh = hb_age is not None and hb_age < 900_000

            market_hb_raw = client.get("v2:market:coinapi:ohlcv:heartbeat")
            market_hb: dict[str, Any] = json.loads(market_hb_raw) if market_hb_raw else {}
            market_ts = market_hb.get("finished_utc") or market_hb.get("ts") or ""
            market_age_ms = _lag_ms(market_ts or None)
            market_age_s = int(market_age_ms / 1000) if market_age_ms is not None else None

            ledger_raw = client.get("v2:paper:ledger")
            ledger_stats: dict[str, Any] = {}
            if ledger_raw:
                parsed_ledger = json.loads(ledger_raw)
                ledger_stats = parsed_ledger if isinstance(parsed_ledger, dict) else {}
            paper_event_count = int(ledger_stats.get("accepted_count") or 0)

            intents_raw = client.get("v2:paper:intents")
            paper_intents: list[dict[str, Any]] = []
            if intents_raw:
                parsed_intents = json.loads(intents_raw)
                if isinstance(parsed_intents, list):
                    paper_intents = [row for row in parsed_intents if isinstance(row, dict)]
            production_grade_cost_rows = sum(
                1
                for row in paper_intents
                if row.get("production_grade_cost_flag") is True
                or row.get("production_grade_cost_evidence") is True
            )
            no_order_explained_rows = sum(
                1
                for row in paper_intents
                if row.get("runtime_cost_capture_order_cost_applicable") is False
            )
            unexplained_missing_cost_rows = sum(
                1
                for row in paper_intents
                if len(row.get("runtime_cost_capture_unexplained_missing_fields") or []) > 0
            )
            paper_fill_allowed_rows = sum(1 for row in paper_intents if row.get("paper_fill_allowed") is True)
            routes_to_live_rows = sum(1 for row in paper_intents if row.get("routes_to_live") is True)
            places_real_order_rows = sum(1 for row in paper_intents if row.get("places_real_order") is True)
            cost_coverage = (
                production_grade_cost_rows / len(paper_intents)
                if paper_intents
                else 0.0
            )

            sig_keys = client.keys("v2:signals:latest:*")
            latest_signal: dict[str, Any] = {}
            latest_sig_ts = ""
            for raw_key in (sig_keys or []):
                k = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
                try:
                    s_raw = client.get(k)
                    if not s_raw:
                        continue
                    s = json.loads(s_raw)
                    if not isinstance(s, dict):
                        continue
                    s_ts = s.get("available_at") or s.get("ts") or ""
                    if not latest_sig_ts or s_ts > latest_sig_ts:
                        latest_sig_ts = s_ts
                        latest_signal = s
                except Exception:
                    pass

            last_event: dict[str, Any] = {}
            if latest_signal:
                last_event = {
                    "paper_action": latest_signal.get("action") or latest_signal.get("paper_fill_status"),
                    "risk_gateway_result": latest_signal.get("risk_state") or latest_signal.get("paper_fill_gate_status"),
                    "paper_ledger_entry_id": latest_signal.get("paper_ledger_id") or latest_signal.get("paper_intent_id"),
                    "symbol": latest_signal.get("symbol"),
                    "timeframe": latest_signal.get("timeframe"),
                    "available_at": latest_sig_ts,
                }

            risk_hb_raw = client.get("v2:risk:gateway:heartbeat")
            risk_hb: dict[str, Any] = json.loads(risk_hb_raw) if risk_hb_raw else {}

            runtime_state = "PAPER_RUNTIME_ONLINE_ACTIVE" if heartbeat_fresh else "PAPER_RUNTIME_HEARTBEAT_STALE"

            lineage_ids: dict[str, Any] = {}
            if latest_signal:
                raw_lineage = latest_signal.get("lineage_ids")
                base_lineage = raw_lineage if isinstance(raw_lineage, dict) else {}
                lineage_ids = {
                    "prediction_id": (
                        latest_signal.get("prediction_id")
                        or base_lineage.get("prediction_id")
                        or base_lineage.get("trainer_prediction_id")
                    ),
                    "feature_snapshot_id": (
                        latest_signal.get("feature_snapshot_id")
                        or base_lineage.get("feature_snapshot_id")
                    ),
                    "signal_id": (
                        latest_signal.get("signal_id")
                        or latest_signal.get("decision_id")
                        or base_lineage.get("signal_id")
                    ),
                    "risk_decision_id": (
                        latest_signal.get("risk_decision_id")
                        or base_lineage.get("risk_decision_id")
                        or risk_hb.get("risk_decision_id")
                    ),
                    "execution_intent_id": (
                        base_lineage.get("paper_intent_id")
                        or latest_signal.get("paper_intent_id")
                    ),
                    "orchestrator_decision_id": (
                        latest_signal.get("orchestrator_decision_id")
                        or base_lineage.get("orchestrator_decision_id")
                    ),
                }

            return {
                "generated_at": now,
                "runtime": hb.get("worker_id", "v2_trade_management_paper_loop"),
                "runtime_state": runtime_state,
                "live_gate_status": "blocked_human_only",
                "mode": "paper",
                "continuous_loop_available": heartbeat_fresh,
                "loop_interval_seconds": 10,
                "writes_only_local_v2_artifacts": True,
                "legacy_redis_writes": bool(hb.get("writes_legacy_redis", False)),
                "exchange_orders": bool(hb.get("places_real_order", False)),
                "leverage_changes": False,
                "margin_mode_changes": False,
                "redis_trim_approval_created": False,
                "market_feed": {
                    "symbol": market_hb.get("live_symbols", [None])[0] if market_hb.get("live_symbols") else "BTCUSDT",
                    "price": None,
                    "source_type": "redis_live",
                    "source": market_hb.get("source", "coinapi_rest"),
                    "source_pointer": "v2:market:coinapi:ohlcv:heartbeat",
                    "generated_at": market_ts or now,
                    "last_event_at": market_ts or None,
                    "age_seconds": market_age_s,
                    "freshness_state": "MARKET_FEED_CURRENT" if market_age_s is not None and market_age_s < 600 else "MARKET_FEED_STALE",
                    "errors": [],
                },
                "paper_loop": {
                    "state": hb.get("cycle_state", "RUNNING_CYCLE"),
                    "tick_id": hb.get("candidate_id", ""),
                    "candidate_id": hb.get("candidate_id"),
                    "policy_id": hb.get("policy_id"),
                    "paper_policy_owner": hb.get("paper_policy_owner"),
                    "current_allowed_paper_owner": hb.get("current_allowed_paper_owner"),
                    "policy_fingerprint": hb.get("policy_fingerprint") or hb.get("selector_policy_fingerprint"),
                    "model_source": hb.get("model_source"),
                    "last_tick_at": hb_ts or now,
                    "paper_event_count": paper_event_count,
                    "last_paper_event_count": paper_event_count,
                    "last_shadow_decision_count": int(ledger_stats.get("shadow_observation_count") or 0),
                    "last_risk_block_count": int(ledger_stats.get("blocked_count") or 0),
                    "intents_built": hb.get("intents_built"),
                    "intents_accepted": hb.get("intents_accepted"),
                    "intents_blocked": hb.get("intents_blocked"),
                    "production_grade_cost_rows": production_grade_cost_rows,
                    "production_grade_cost_coverage": cost_coverage,
                    "no_order_explained_rows": no_order_explained_rows,
                    "unexplained_missing_cost_rows": unexplained_missing_cost_rows,
                    "paper_fill_allowed_rows": paper_fill_allowed_rows,
                    "routes_to_live_rows": routes_to_live_rows,
                    "places_real_order_rows": places_real_order_rows,
                },
                "paper_account": {
                    "currency": "USDT",
                    "starting_equity": 10000.0,
                    "equity": 10000.0,
                    "realized_pnl": 0.0,
                    "unrealized_pnl": 0.0,
                    "open_position_count": 0,
                    "position_source": "v2:paper:positions",
                },
                "trainer_prediction": {
                    "prediction_id": latest_signal.get("prediction_id"),
                    "feature_snapshot_id": latest_signal.get("feature_snapshot_id"),
                    "status": "ACTIVE_PAPER_RUNTIME" if latest_signal else "MISSING_EVIDENCE",
                    "source": "redis:v2:signals:latest:*",
                } if latest_signal else None,
                "current_signal_lineage": {
                    "status": "REALTIME_RUNTIME_EVIDENCE" if latest_signal else "MISSING_EVIDENCE",
                    "source": "redis:v2:signals:latest:*",
                    "classification": "V2_PAPER_SIGNAL_ACTIVE" if latest_signal else "NO_SIGNAL",
                    "lineage_ids": lineage_ids,
                    "live_trading_enabled": False,
                    "signal": {
                        "signal_id": latest_signal.get("signal_id") or latest_signal.get("decision_id"),
                        "proposed_action": latest_signal.get("action"),
                        "symbol": latest_signal.get("symbol"),
                        "timeframe": latest_signal.get("timeframe"),
                        "confidence": latest_signal.get("confidence"),
                        "available_at": latest_sig_ts,
                    } if latest_signal else None,
                } if latest_signal else {"status": "MISSING_EVIDENCE", "source": "redis:v2:signals:latest:*", "lineage_ids": {}},
                "current_risk_decision": {
                    "status": "LIVE_OK",
                    "classification": risk_hb.get("classification", "V2_RISK_GATEWAY_LIVE_OK"),
                    "generated_at": risk_hb.get("available_at") or risk_hb.get("ts") or now,
                    "live_gate": "blocked_human_only",
                    "live_blocked": True,
                    "profile_id": risk_hb.get("profile_id"),
                },
                "last_paper_event": last_event or {
                    "paper_action": "NO_RECENT_EVENT",
                    "risk_gateway_result": "NO_RECENT_EVENT",
                    "paper_ledger_entry_id": None,
                },
                "safety": {
                    "live_trading_enabled": False,
                    "exchange_orders_enabled": False,
                    "leverage_changes_enabled": False,
                    "margin_mode_changes_enabled": False,
                    "legacy_redis_writes_enabled": False,
                    "live_gate_status": "blocked_human_only",
                },
                "blockers": [
                    {
                        "id": "LIVE_GATE_BLOCKED_HUMAN_ONLY",
                        "severity": "expected_safety_gate",
                        "detail": "Live order routing remains blocked_human_only.",
                    },
                ],
                "freshness": {
                    "status": "REALTIME_RUNTIME_EVIDENCE" if heartbeat_fresh else "STALE_HEARTBEAT",
                    "generated_at": now,
                    "runtime_age_seconds": int(hb_age / 1000) if hb_age is not None else None,
                    "market_age_seconds": market_age_s,
                    "source_type": "redis_live",
                },
                "signal_lineage_status": {
                    "status": "REALTIME_RUNTIME_EVIDENCE" if latest_signal else "MISSING_EVIDENCE",
                    "source": "redis:v2:signals:latest:*",
                    "classification": "ACTIVE_PAPER_RUNTIME",
                    "live_trading_enabled": False,
                },
                "source": "redis_live",
                "heartbeat_classification": hb.get("classification"),
            }
        except Exception as exc:
            return {
                "generated_at": _utc_now(),
                "runtime": "v2_trade_management_paper_loop",
                "runtime_state": "PAPER_RUNTIME_EVIDENCE_ERROR",
                "live_gate_status": "blocked_human_only",
                "mode": "paper",
                "error": str(exc),
                "exchange_orders": False,
                "legacy_redis_writes": False,
                "leverage_changes": False,
                "margin_mode_changes": False,
                "continuous_loop_available": False,
            }

    data = await run_in_threadpool(_build)
    return data


@router.get("/paper/fills")
async def get_paper_fills(actor: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    """Public endpoint: paper engine fill history from v2:paper:intents (filled entries only)."""
    endpoint = "/api/v2/paper/fills"

    def _load() -> dict[str, Any]:
        try:
            client = get_redis()
            intents = _paper_intents_from_redis(client)
            fills = _paper_fills_from_intents(intents)
            return {"fills": fills[:500], "total": len(fills)}
        except Exception as exc:
            return {"fills": [], "total": 0, "error": str(exc)}

    data = await run_in_threadpool(_load)
    return _base_response(
        endpoint=endpoint,
        data=data,
        source="v2:paper:intents Redis",
        source_type="redis_live",
        timestamp=_utc_now(),
        missing_fields=[],
        warnings=["Paper fills are simulation only; no real orders were placed"],
        mode="paper",
        trader_context=_trader_context(actor),
    )


@router.get("/paper/activity")
async def get_paper_activity(actor: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    endpoint = "/api/v2/paper/activity"

    def _load() -> tuple[dict[str, Any], list[str]]:
        try:
            return _load_paper_activity_payload()
        except Exception as exc:
            return {
                "positions": [],
                "fills": [],
                "executions": [],
                "open_orders": [],
                "orders": [],
                "order_history": [],
                "audit_events": [],
                "summary": {},
                "stream": {
                    "source": "v2:paper:* Redis",
                    "transport": "websocket_or_http_polling_fallback",
                    "live_trading_enabled": False,
                    "exchange_mutation_enabled": False,
                },
                "error": str(exc),
            }, [str(exc)]

    data, warnings = await run_in_threadpool(_load)
    return _base_response(
        endpoint=endpoint,
        data=data,
        source="v2:paper:* Redis",
        source_type="redis_live",
        timestamp=_utc_now(),
        missing_fields=[],
        warnings=warnings,
        mode="paper",
        trader_context=_trader_context(actor),
    )


async def _paper_activity_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        requested_interval = int(websocket.query_params.get("interval_ms", "1000"))
    except ValueError:
        requested_interval = 1000
    interval_seconds = max(0.5, min(10.0, requested_interval / 1000))
    try:
        while True:
            try:
                data, warnings = await run_in_threadpool(_load_paper_activity_payload)
                payload = _base_response(
                    endpoint="/api/v2/ws/paper-activity",
                    data=data,
                    source="v2:paper:* Redis",
                    source_type="redis_live",
                    timestamp=_utc_now(),
                    missing_fields=[],
                    warnings=warnings,
                    mode="paper",
                )
            except Exception as exc:
                payload = {
                    "data": None,
                    "source": "v2:paper:* Redis",
                    "source_type": "unavailable",
                    "endpoint": "/api/v2/ws/paper-activity",
                    "timestamp": _utc_now(),
                    "received_at": _utc_now(),
                    "lag_ms": None,
                    "stale": True,
                    "missing_fields": ["paper_activity"],
                    "warnings": [str(exc)],
                    "mode": "paper",
                }
            try:
                await websocket.send_json(payload)
            except Exception:
                return
            await asyncio.sleep(interval_seconds)
    except WebSocketDisconnect:
        return


@router.websocket("/ws/paper-activity")
async def api_v2_paper_activity_stream(websocket: WebSocket) -> None:
    await _paper_activity_websocket(websocket)


@stream_router.websocket("/ws/paper-activity")
async def root_paper_activity_stream(websocket: WebSocket) -> None:
    await _paper_activity_websocket(websocket)


async def _readonly_resource_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    target = _safe_readonly_resource_target(websocket.query_params.get("path"))
    try:
        requested_interval = int(websocket.query_params.get("interval_ms", "15000"))
    except ValueError:
        requested_interval = 15000
    interval_seconds = max(0.5, min(120.0, requested_interval / 1000))
    if target is None:
        await websocket.send_json({
            "data": None,
            "source": "readonly_resource_websocket",
            "source_type": "unavailable",
            "endpoint": "/api/v2/ws/resource",
            "timestamp": _utc_now(),
            "received_at": _utc_now(),
            "lag_ms": None,
            "stale": True,
            "missing_fields": ["path"],
            "warnings": ["Invalid or non-read-only resource path"],
            "mode": "read_only",
        })
        await websocket.close(code=1008)
        return

    headers = {key.lower(): value for key, value in websocket.headers.items()}
    try:
        while True:
            started = time.monotonic()
            try:
                handled, payload = await run_in_threadpool(
                    _readonly_resource_direct_payload_sync,
                    target,
                    headers,
                )
                if not handled:
                    payload = await run_in_threadpool(_fetch_same_origin_readonly_json, target, headers)
                payload = _readonly_resource_ws_payload(target, payload, started)
            except Exception as exc:
                payload = {
                    "data": None,
                    "source": target,
                    "source_type": "unavailable",
                    "endpoint": target,
                    "timestamp": _utc_now(),
                    "received_at": _utc_now(),
                    "lag_ms": round((time.monotonic() - started) * 1000),
                    "stale": True,
                    "missing_fields": ["resource"],
                    "warnings": [str(exc)],
                    "mode": "read_only",
                    "transport": "websocket",
                    "resource_path": target,
                }
            try:
                await websocket.send_json(payload)
            except Exception:
                return
            await asyncio.sleep(interval_seconds)
    except WebSocketDisconnect:
        return


@router.websocket("/ws/resource")
async def api_v2_readonly_resource_stream(websocket: WebSocket) -> None:
    await _readonly_resource_websocket(websocket)


@stream_router.websocket("/ws/resource")
async def root_readonly_resource_stream(websocket: WebSocket) -> None:
    await _readonly_resource_websocket(websocket)
