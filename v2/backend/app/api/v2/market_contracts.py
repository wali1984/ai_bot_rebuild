"""Read-only V2 market/trading contracts for public trader surfaces.

These routes normalize existing public payload files into typed, honest API
states. They never place orders, cancel orders, change leverage/margin, mutate
live gates, or write execution state. Missing data returns a structured
``unavailable`` response instead of raising a server error.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketState

from app.api.v2._common import get_redis
from app.api.v2.probation_display import probation_gate_display_status
from app.services.realtime.operator_snapshot import _hedge_payload, _ingestors_payload
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
from app.services.portfolio import build_canonical_pnl
from app.services.trader_account_repository import TraderPaperAccount, get_trader_account_repository
from app.services.backend_shutdown import (
    SERVICE_RESTART_CLOSE_CODE,
    create_registered_task,
    shutdown_started,
    track_current_task,
    wait_for_shutdown,
)
from app.services.coinglass_provider import build_coinglass_health
from app.services.hedge_engine import compute_portfolio_exposure, simulate_cross_margin_stress
from app.services.provider_features import build_provider_actual_data_panel
from app.services.smart_money_wallets import build_moralis_health
from app.services.binance_unified_websocket_transport import (
    REST_FALLBACK_ENV,
    binance_rest_fallback_decision,
)

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
BINANCE_PUBLIC_CACHE_STALE_MAX_SECONDS = float(
    os.environ.get("ALPHAFORGE_BINANCE_PUBLIC_CACHE_STALE_MAX_SECONDS", "60")
)
MARKET_OVERVIEW_REDIS_LIMIT = int(os.environ.get("ALPHAFORGE_MARKET_OVERVIEW_REDIS_LIMIT", "250"))
MARKET_OVERVIEW_REDIS_SYMBOLS = tuple(
    symbol.strip().upper()
    for symbol in os.environ.get(
        "ALPHAFORGE_MARKET_OVERVIEW_REDIS_SYMBOLS",
        "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,DOGEUSDT,ADAUSDT,LINKUSDT,AVAXUSDT,LTCUSDT,BCHUSDT,DOTUSDT,UNIUSDT,AAVEUSDT,OPUSDT,ARBUSDT,PEPEUSDT",
    ).split(",")
    if symbol.strip()
)
BINANCE_PUBLIC_JSON_CACHE_LOCK = threading.Lock()
BINANCE_PUBLIC_JSON_CACHE: dict[str, tuple[float, Any, str]] = {}
_BINANCE_REFRESH_IN_FLIGHT: set[str] = set()
READONLY_RESOURCE_RESOLVE_TIMEOUT_SECONDS = float(os.environ.get("ALPHAFORGE_READONLY_RESOURCE_RESOLVE_TIMEOUT_SECONDS", "2.5"))
WEBSOCKET_DISCONNECT_POLL_SECONDS = float(os.environ.get("ALPHAFORGE_WEBSOCKET_DISCONNECT_POLL_SECONDS", "0.25"))
WEBSOCKET_SEND_TIMEOUT_SECONDS = float(os.environ.get("ALPHAFORGE_WEBSOCKET_SEND_TIMEOUT_SECONDS", "0.75"))
PAPER_ACTIVITY_WS_MAX_ACTIVE = int(os.environ.get("ALPHAFORGE_PAPER_ACTIVITY_WS_MAX_ACTIVE", "16"))
PAPER_ACTIVITY_WS_MAX_ACTIVE_PER_CLIENT = int(
    os.environ.get("ALPHAFORGE_PAPER_ACTIVITY_WS_MAX_ACTIVE_PER_CLIENT", "3")
)
SIGNALS_MATRIX_CACHE_TTL_SECONDS = float(os.environ.get("ALPHAFORGE_SIGNALS_MATRIX_CACHE_TTL_SECONDS", "2"))
SIGNALS_MATRIX_CACHE_LOCK = threading.Lock()
SIGNALS_MATRIX_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
PREDICTIONS_MATRIX_CACHE_TTL_SECONDS = float(os.environ.get("ALPHAFORGE_PREDICTIONS_MATRIX_CACHE_TTL_SECONDS", "2"))
PREDICTIONS_MATRIX_CACHE_LOCK = threading.Lock()
PREDICTIONS_MATRIX_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
PAPER_ACTIVITY_CACHE_LOCK = threading.Lock()
PAPER_ACTIVITY_WS_LOCK = threading.Lock()
PAPER_ACTIVITY_WS_BY_CLIENT: dict[str, int] = {}
PAPER_ACTIVITY_LAST_NON_EMPTY_POSITIONS: dict[str, Any] = {
    "positions": [],
    "updated_monotonic": 0.0,
    "updated_at": None,
}
PAPER_RUNTIME_STATUS_SAMPLE_KEYS = {
    "sample_a_grade_rows",
    "sample_canary_candidates",
    "sample_canary_pending_rows",
    "sample_compacted_economic_trades",
    "sample_lifecycle_closed_canary_outcomes",
    "sample_near_a_grade_rows",
    "sample_near_miss_strategy_blocked_rows",
    "sample_quality_rows",
    "sample_rejected_forward_canary_outcomes",
    "sample_valid_forward_canary_outcomes",
}
PAPER_RUNTIME_STATUS_SIGNAL_FALLBACK_SYMBOLS = tuple(
    symbol.strip().upper()
    for symbol in os.environ.get(
        "ALPHAFORGE_RUNTIME_STATUS_SIGNAL_FALLBACK_SYMBOLS",
        "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT",
    ).split(",")
    if symbol.strip()
)
PAPER_RUNTIME_STATUS_SIGNAL_FALLBACK_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
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
OPERATOR_ET = ZoneInfo("America/New_York")


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


def _et_now() -> str:
    return datetime.now(OPERATOR_ET).isoformat(timespec="seconds")


def _to_et(timestamp: str | None) -> str | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(OPERATOR_ET).isoformat(timespec="seconds")


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


def _provider_readiness_summary() -> dict[str, Any]:
    coinglass = _read_v2_redis_json("v2:provider:coinglass:health")
    moralis = _read_v2_redis_json("v2:provider:moralis:health")
    coinglass_usage = _read_v2_redis_json("v2:provider:coinglass:usage") or {}
    moralis_usage = _read_v2_redis_json("v2:provider:moralis:usage") or {}
    coinglass_endpoint_status = _read_v2_redis_json("v2:provider:coinglass:endpoint_status") or {}
    moralis_endpoint_status = _read_v2_redis_json("v2:provider:moralis:endpoint_status") or {}
    provider_consumption = _read_v2_redis_json("v2:altdata:provider_consumption_status") or {}
    confluence_sample = _read_v2_redis_json(
        "v2:altdata:confluence:"
        + str(os.environ.get("ALPHAFORGE_PROVIDER_PANEL_SYMBOL", "BTCUSDT")).upper()
        + ":"
        + str(os.environ.get("ALPHAFORGE_PROVIDER_PANEL_TIMEFRAME", "1m"))
    ) or {}
    confluence_features = (
        confluence_sample.get("features")
        if isinstance(confluence_sample.get("features"), dict)
        else {}
    )
    if not coinglass:
        coinglass = build_coinglass_health(os.environ)
    if not moralis:
        moralis = build_moralis_health(os.environ)
    provider_actual_data = build_provider_actual_data_panel(
        get_redis(),
        symbol=str(os.environ.get("ALPHAFORGE_PROVIDER_PANEL_SYMBOL", "BTCUSDT")).upper(),
        timeframe=str(os.environ.get("ALPHAFORGE_PROVIDER_PANEL_TIMEFRAME", "1m")),
    )
    return {
        "schema_version": "v2_provider_readiness_summary_v1",
        "status": "PROVIDER_READINESS_ACTIVE",
        "coinglass": coinglass,
        "moralis": moralis,
        "coinglass_status": coinglass.get("status"),
        "moralis_status": moralis.get("status"),
        "coinglass_dashboard_color": provider_actual_data.get("coinglass", {}).get("dashboard_color"),
        "moralis_dashboard_color": provider_actual_data.get("moralis", {}).get("dashboard_color"),
        "coinglass_actual_payload_present": provider_actual_data.get("coinglass", {}).get("actual_payload_present"),
        "moralis_actual_payload_present": provider_actual_data.get("moralis", {}).get("actual_payload_present"),
        "coinglass_heartbeat_only": provider_actual_data.get("coinglass", {}).get("heartbeat_only"),
        "moralis_heartbeat_only": provider_actual_data.get("moralis", {}).get("heartbeat_only"),
        "moralis_feature_bridge_ready": moralis.get("feature_bridge_ready"),
        "moralis_feature_count": moralis.get("feature_count"),
        "moralis_required_feature_count": moralis.get("required_feature_count"),
        "moralis_missing_feature_flags": moralis.get("missing_feature_flags"),
        "moralis_stale_feature_flags": moralis.get("stale_feature_flags"),
        "moralis_missing_mask_true": moralis.get("missing_mask_true"),
        "moralis_stale_mask_true": moralis.get("stale_mask_true"),
        "moralis_token_map_count": moralis.get("token_map_count"),
        "moralis_wallet_watchlist_count": moralis.get("wallet_watchlist_count"),
        "provider_tensor_consumption": provider_consumption.get("provider_tensor_consumption"),
        "provider_risk_consumption": provider_consumption.get("provider_risk_consumption"),
        "provider_orchestrator_consumption": provider_consumption.get("provider_orchestrator_consumption"),
        "provider_allocator_consumption": provider_consumption.get("provider_allocator_consumption"),
        "provider_paper_consumption": provider_consumption.get("provider_paper_consumption"),
        "provider_live_dryrun_consumption": provider_consumption.get("provider_live_dryrun_consumption"),
        "provider_feedback_attribution": provider_consumption.get("provider_feedback_attribution"),
        "ppo_provider_feature_count": provider_consumption.get("ppo_provider_feature_count"),
        "masa_provider_feature_count": provider_consumption.get("masa_provider_feature_count"),
        "confluence_trade_block_score": provider_consumption.get("confluence_trade_block_score", confluence_features.get("altdata_trade_block_score")),
        "confluence_reduce_size_score": provider_consumption.get("confluence_reduce_size_score", confluence_features.get("altdata_reduce_size_score")),
        "confluence_hedge_required_score": provider_consumption.get("confluence_hedge_required_score", confluence_features.get("altdata_hedge_required_score")),
        "altdata_provider_consumption_status": provider_consumption,
        "altdata_single_provider_can_approve": False,
        "coinglass_usage": coinglass_usage,
        "moralis_usage": moralis_usage,
        "coinglass_endpoint_status": coinglass_endpoint_status,
        "moralis_endpoint_status": moralis_endpoint_status,
        "actual_data_panel": provider_actual_data,
        "raw_keys_exposed": False,
        "invalid_subscription_blocks_core_system": False,
        "optional_provider_failures_core_blocking": False,
        "heartbeat_only_green_allowed": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _adaptive_hedge_cross_margin_summary() -> dict[str, Any]:
    portfolio = _read_v2_redis_json("v2:portfolio:state") or {}
    rows = portfolio.get("positions_by_symbol") or portfolio.get("positions") or []
    positions = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("open_position") is not False
        and str(row.get("position_state") or "").lower() != "shadow_observation_only"
    ]
    equity = _float(
        portfolio.get("equity")
        or portfolio.get("current_session_equity")
        or portfolio.get("paper_equity")
    ) or 0.0
    available = _float(portfolio.get("cash_balance") or portfolio.get("available_balance") or equity) or 0.0
    open_notional = _float(portfolio.get("open_position_notional")) or sum(
        _float(row.get("gross_notional") or row.get("notional") or row.get("notional_usd")) or 0.0
        for row in positions
    )
    portfolio_summary_leverage = _float(portfolio.get("effective_leverage")) or (
        open_notional / equity if equity > 0.0 and open_notional > 0.0 else 0.0
    )
    exposure = compute_portfolio_exposure(positions, equity_usd=equity)
    stress = simulate_cross_margin_stress(
        equity_usd=equity,
        available_margin_usd=available,
        target_notional_usd=open_notional,
        allocated_margin_usd=open_notional,
        recommended_leverage=portfolio_summary_leverage,
        max_loss_usd=portfolio.get("current_drawdown_usd"),
        requested_margin_mode="isolated_paper_simulated",
        expectancy_usd=portfolio.get("session_realized_pnl") or portfolio.get("realized_pnl_usd"),
    )
    leverage_values = []
    margin_modes = []
    hedge_rows = 0
    for row in positions:
        leverage = _float(row.get("recommended_leverage") or row.get("effective_leverage"))
        if leverage is not None:
            leverage_values.append(round(leverage, 8))
        mode = row.get("recommended_margin_mode") or row.get("margin_mode_simulated")
        if mode:
            margin_modes.append(str(mode))
        if row.get("hedge_state") not in (None, "", "NO_HEDGE"):
            hedge_rows += 1
    if not leverage_values and open_notional > 0.0:
        leverage_values = [round(portfolio_summary_leverage, 8)]
    if not margin_modes and open_notional > 0.0:
        margin_modes = [stress.get("recommended_margin_mode") or "isolated_paper_simulated"]
    return {
        "schema_version": "v2_adaptive_hedge_cross_margin_runtime_summary_v1",
        "status": "ADAPTIVE_HEDGE_CROSS_MARGIN_SIMULATION_ACTIVE",
        "source": "redis:v2:portfolio:state",
        "generated_utc": portfolio.get("generated_utc") or _utc_now(),
        "generated_et": _to_et(portfolio.get("generated_utc")) or portfolio.get("generated_est") or _et_now(),
        "paper_session_id": portfolio.get("paper_session_id") or portfolio.get("reset_session_id"),
        "recommended_leverage_distribution": sorted(set(leverage_values)),
        "recommended_margin_mode_distribution": sorted(set(margin_modes)),
        "current_notional_distribution_usd": [round(open_notional, 8)] if open_notional else [],
        "hedge_rows": hedge_rows,
        "hedge_state": "NO_HEDGE" if hedge_rows <= 0 else "HEDGE_ROWS_PRESENT",
        "cross_margin_state": stress.get("why_cross_margin_or_isolated"),
        "cross_margin_safe": stress.get("cross_margin_safe"),
        "recommended_margin_mode": stress.get("recommended_margin_mode"),
        "operator_display_currency": "USD",
        "operator_display_timezone": "America/New_York",
        "bps_operator_display_allowed": False,
        **exposure,
        **stress,
    }


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


def _compact_paper_runtime_contract(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in payload.items():
        if key in PAPER_RUNTIME_STATUS_SAMPLE_KEYS:
            if isinstance(value, list):
                compact[f"{key}_count"] = len(value)
            continue
        compact[key] = value
    compact["sample_rows_omitted_from_api"] = True
    return compact


PAPER_RUNTIME_RESPONSE_LIST_LIMIT = 20
PAPER_RUNTIME_RESPONSE_DICT_LIMIT = 80
PAPER_RUNTIME_RESPONSE_HEAVY_KEYS = PAPER_RUNTIME_STATUS_SAMPLE_KEYS | {
    "rows",
    "source_rows",
    "sample_decisions",
    "sample_rows",
    "sample_reasons",
    "failed_forward_canary_blocker_details",
}
PAPER_RUNTIME_RESPONSE_PRIORITY_KEYS = (
    "preemptive_edge_control",
    "preemptive_edge_control_status",
    "paper_preemptive_admission_status",
    "paper_no_bad_entry_runtime_status",
    "positive_edge_probation",
    "positive_edge_probation_runtime_status",
    "probation_5_trade_gate",
    "probation_20_trade_gate",
    "probation_50_trade_gate",
    "order_cost_applicable_rows",
    "production_grade_cost_rows",
    "production_grade_cost_order_applicable_rows",
    "production_grade_cost_coverage",
    "production_grade_cost_coverage_basis",
    "production_grade_cost_total_row_coverage",
    "paper_fill_allowed_rows",
    "routes_to_live_rows",
    "places_real_order_rows",
    "a_grade_rows",
    "near_a_grade_rows",
    "source_tier_a_grade_execution_rows",
    "guardian_status",
    "guardian_new_entries_allowed",
    "guardian_block_all_new_a_grade_entries",
    "a_grade_predicate_counts",
    "paper_a_grade_gate_burndown_status",
)


def _compact_paper_runtime_response(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, list):
        if not value:
            return []
        trimmed = [
            _compact_paper_runtime_response(item, depth=depth + 1)
            for item in value[:PAPER_RUNTIME_RESPONSE_LIST_LIMIT]
        ]
        if len(value) > PAPER_RUNTIME_RESPONSE_LIST_LIMIT:
            trimmed.append({
                "omitted_count": len(value) - PAPER_RUNTIME_RESPONSE_LIST_LIMIT,
                "omitted_reason": "primary_api_payload_compaction",
            })
        return trimmed
    if not isinstance(value, dict):
        return value

    compact: dict[str, Any] = {}
    items = list(value.items())
    priority = [
        (key, value[key])
        for key in PAPER_RUNTIME_RESPONSE_PRIORITY_KEYS
        if key in value
    ]
    priority_names = {key for key, _ in priority}
    items = priority + [
        (key, item) for key, item in items if key not in priority_names
    ]
    for index, (key, item) in enumerate(items):
        if index >= PAPER_RUNTIME_RESPONSE_DICT_LIMIT:
            compact["omitted_key_count"] = len(items) - PAPER_RUNTIME_RESPONSE_DICT_LIMIT
            compact["omitted_reason"] = "primary_api_payload_compaction"
            break
        if key in PAPER_RUNTIME_RESPONSE_HEAVY_KEYS:
            if isinstance(item, (list, dict)):
                compact[f"{key}_count"] = len(item)
                compact[f"{key}_omitted_from_primary_api"] = True
                continue
        if depth >= 6 and isinstance(item, (list, dict)):
            compact[f"{key}_omitted_from_primary_api"] = True
            compact[f"{key}_count"] = len(item)
            continue
        compact[key] = _compact_paper_runtime_response(item, depth=depth + 1)
    if depth == 0:
        compact["primary_api_payload_compacted"] = True
        compact["debug_detail_route"] = "/api/v2/paper/runtime-status?debug=true"
    return compact


def _paper_runtime_signal_timestamp(row: dict[str, Any]) -> str:
    for key in ("available_at", "decision_time", "generated_at", "generated_utc", "timestamp", "ts"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _latest_signal_from_paper_intents(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    latest_signal: dict[str, Any] = {}
    latest_ts = ""
    for row in rows:
        if not any(row.get(key) for key in ("signal_id", "prediction_id", "decision_id")):
            continue
        row_ts = _paper_runtime_signal_timestamp(row)
        if not latest_ts or row_ts > latest_ts:
            latest_ts = row_ts
            latest_signal = row
    return latest_signal, latest_ts


def _latest_signal_from_bounded_keys(client: Any) -> tuple[dict[str, Any], str]:
    latest_signal: dict[str, Any] = {}
    latest_ts = ""
    for symbol in PAPER_RUNTIME_STATUS_SIGNAL_FALLBACK_SYMBOLS:
        keys = [f"v2:signals:latest:{symbol}"]
        keys.extend(f"v2:signals:latest:{symbol}:{timeframe}" for timeframe in PAPER_RUNTIME_STATUS_SIGNAL_FALLBACK_TIMEFRAMES)
        for key in keys:
            try:
                raw = client.get(key)
            except Exception:
                continue
            parsed = _json_object_from_redis_raw(raw)
            if not parsed:
                continue
            row_ts = _paper_runtime_signal_timestamp(parsed)
            if not latest_ts or row_ts > latest_ts:
                latest_ts = row_ts
                latest_signal = parsed
    return latest_signal, latest_ts


async def _bounded_run_in_threadpool(func: Any, *args: Any, timeout: float, **kwargs: Any) -> Any:
    return await asyncio.wait_for(
        run_in_threadpool(func, *args, **kwargs),
        timeout=max(0.1, timeout),
    )


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


async def _readonly_resource_resolve_payload(target: str, headers: dict[str, str]) -> Any:
    """Async-native resolver that avoids creating nested event loops via asyncio.run()."""
    handled, payload = await asyncio.wait_for(
        _readonly_resource_direct_payload(target, headers),
        timeout=max(0.1, READONLY_RESOURCE_RESOLVE_TIMEOUT_SECONDS),
    )
    if handled:
        return payload
    return await _bounded_run_in_threadpool(
        _fetch_same_origin_readonly_json,
        target,
        headers,
        timeout=READONLY_RESOURCE_HTTP_TIMEOUT_SECONDS + 0.5,
    )


def _websocket_is_connected(websocket: WebSocket) -> bool:
    return (
        websocket.client_state == WebSocketState.CONNECTED
        and websocket.application_state == WebSocketState.CONNECTED
    )


async def _close_websocket_for_service_restart(websocket: WebSocket) -> None:
    if websocket.application_state == WebSocketState.DISCONNECTED:
        return
    with contextlib.suppress(Exception):
        await websocket.close(code=SERVICE_RESTART_CLOSE_CODE)


async def _send_websocket_json_bounded(websocket: WebSocket, payload: Any) -> bool:
    try:
        await asyncio.wait_for(
            websocket.send_json(payload),
            timeout=max(0.1, WEBSOCKET_SEND_TIMEOUT_SECONDS),
        )
        return True
    except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
        return False


def _websocket_client_id(websocket: WebSocket) -> str:
    if websocket.client and websocket.client.host:
        return str(websocket.client.host)
    return "unknown"


def _try_register_paper_activity_websocket(client_id: str) -> tuple[bool, int, int]:
    max_total = max(1, PAPER_ACTIVITY_WS_MAX_ACTIVE)
    max_client = max(1, PAPER_ACTIVITY_WS_MAX_ACTIVE_PER_CLIENT)
    with PAPER_ACTIVITY_WS_LOCK:
        total = sum(PAPER_ACTIVITY_WS_BY_CLIENT.values())
        client_count = PAPER_ACTIVITY_WS_BY_CLIENT.get(client_id, 0)
        if total >= max_total or client_count >= max_client:
            return False, total, client_count
        PAPER_ACTIVITY_WS_BY_CLIENT[client_id] = client_count + 1
        return True, total + 1, client_count + 1


def _unregister_paper_activity_websocket(client_id: str) -> None:
    with PAPER_ACTIVITY_WS_LOCK:
        current = PAPER_ACTIVITY_WS_BY_CLIENT.get(client_id, 0)
        if current <= 1:
            PAPER_ACTIVITY_WS_BY_CLIENT.pop(client_id, None)
        else:
            PAPER_ACTIVITY_WS_BY_CLIENT[client_id] = current - 1


async def _watch_websocket_disconnect(websocket: WebSocket) -> str:
    try:
        while not shutdown_started():
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return "client_disconnect"
    except WebSocketDisconnect:
        return "client_disconnect"
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return f"receive_error:{type(exc).__name__}"
    return "shutdown"


async def _wait_for_next_websocket_iteration(
    seconds: float,
    disconnect_task: "asyncio.Task[Any]",
) -> str:
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        if shutdown_started():
            return "shutdown"
        if disconnect_task.done():
            return "disconnect"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "interval"
        shutdown_task = asyncio.create_task(wait_for_shutdown())
        sleep_task = asyncio.create_task(
            asyncio.sleep(min(remaining, WEBSOCKET_DISCONNECT_POLL_SECONDS))
        )
        try:
            done, _pending = await asyncio.wait(
                {shutdown_task, sleep_task, disconnect_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if shutdown_task in done:
                return "shutdown"
            if disconnect_task in done:
                return "disconnect"
        finally:
            for task in (shutdown_task, sleep_task):
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task


async def _cancel_websocket_disconnect_task(task: "asyncio.Task[Any]") -> None:
    if not task.done():
        task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


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


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


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


def _json_from_redis_raw(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return raw


def _redis_sync_get_json(key: str) -> Any:
    try:
        client = get_redis()
    except Exception:
        return None
    if client is None:
        return None
    try:
        return _json_from_redis_raw(client.get(key))
    except Exception:
        return None


def _redis_sync_scan(pattern: str, *, limit: int = 256) -> list[str]:
    try:
        client = get_redis()
    except Exception:
        return []
    if client is None or not hasattr(client, "scan_iter"):
        return []
    keys: list[str] = []
    try:
        for key in client.scan_iter(match=pattern, count=500):
            keys.append(key.decode("utf-8", errors="replace") if isinstance(key, bytes) else str(key))
            if len(keys) >= limit:
                break
    except Exception:
        return []
    return keys


def _ms_from_any(value: Any) -> int | None:
    number = _float(value)
    if number is not None:
        return int(number * 1000) if number < 10_000_000_000 else int(number)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            return None
    return None


def _redis_kline_to_binance_row(row: Any) -> list[Any] | None:
    if isinstance(row, list) and len(row) >= 11:
        return row
    if not isinstance(row, dict):
        return None
    ohlcv = row.get("ohlcv") if isinstance(row.get("ohlcv"), dict) else {}
    open_ms = _ms_from_any(row.get("open_time_ms") or row.get("candle_open_time") or row.get("open_time") or row.get("time"))
    close_ms = _ms_from_any(row.get("close_time_ms") or row.get("candle_close_time") or row.get("close_time"))
    open_price = row.get("open", ohlcv.get("open"))
    high = row.get("high", ohlcv.get("high"))
    low = row.get("low", ohlcv.get("low"))
    close = row.get("close", ohlcv.get("close"))
    volume = row.get("volume", ohlcv.get("volume"))
    if open_ms is None or close_ms is None:
        return None
    if any(_float(value) is None for value in (open_price, high, low, close, volume)):
        return None
    return [
        open_ms,
        str(open_price),
        str(high),
        str(low),
        str(close),
        str(volume),
        close_ms,
        str(row.get("quote_volume") or row.get("quoteVolume") or ohlcv.get("quote_volume") or 0),
        int(_float(row.get("trade_count") or row.get("number_of_trades") or 0) or 0),
        str(row.get("taker_buy_base_volume") or 0),
        str(row.get("taker_buy_quote_volume") or 0),
        "0",
    ]


def _redis_trade_to_binance_recent_trade(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    price = row.get("price") or row.get("p")
    qty = row.get("qty") or row.get("q") or row.get("size")
    ts = _ms_from_any(row.get("time") or row.get("T") or row.get("event_time") or row.get("E"))
    if _float(price) is None or _float(qty) is None or ts is None:
        return None
    return {
        "id": row.get("id") or row.get("a"),
        "price": str(price),
        "qty": str(qty),
        "time": ts,
        "isBuyerMaker": bool(row.get("isBuyerMaker", row.get("m", False))),
    }


def _binance_public_json_from_redis(path: str, params: dict[str, Any]) -> tuple[Any | None, str, str | None]:
    symbol = str(params.get("symbol") or "").upper()
    if path == "/fapi/v1/ticker/24hr" and symbol:
        payload = _redis_sync_get_json(f"v2:market:prices:{symbol}")
        ticker = payload.get("ticker_24hr") if isinstance(payload, dict) and isinstance(payload.get("ticker_24hr"), dict) else payload
        if isinstance(ticker, dict):
            return (
                {**ticker, "symbol": ticker.get("symbol") or symbol},
                f"redis:v2:market:prices:{symbol}",
                "Binance public WebSocket/cache primary; REST not used",
            )
    if path == "/fapi/v1/ticker/24hr" and not symbol:
        rows: list[dict[str, Any]] = []
        for key in _redis_sync_scan("v2:market:prices:*", limit=512):
            payload = _redis_sync_get_json(key)
            if not isinstance(payload, dict):
                continue
            row_symbol = key.rsplit(":", 1)[-1].upper()
            ticker = payload.get("ticker_24hr") if isinstance(payload.get("ticker_24hr"), dict) else payload
            if isinstance(ticker, dict):
                rows.append({**ticker, "symbol": ticker.get("symbol") or row_symbol})
        if rows:
            return rows, "redis:v2:market:prices:*", "Binance public WebSocket/cache primary; REST not used"
    if path == "/fapi/v1/premiumIndex" and symbol:
        funding = _redis_sync_get_json(f"v2:market:funding:{symbol}")
        prices = _redis_sync_get_json(f"v2:market:prices:{symbol}")
        nested = prices.get("funding") if isinstance(prices, dict) and isinstance(prices.get("funding"), dict) else {}
        source = funding if isinstance(funding, dict) and funding else nested if isinstance(nested, dict) else {}
        if source:
            return (
                {
                    "symbol": source.get("symbol") or symbol,
                    "markPrice": source.get("markPrice") or source.get("mark_price"),
                    "indexPrice": source.get("indexPrice") or source.get("index_price"),
                    "estimatedSettlePrice": source.get("estimatedSettlePrice"),
                    "lastFundingRate": source.get("lastFundingRate") or source.get("funding_rate") or source.get("last_funding_rate"),
                    "nextFundingTime": source.get("nextFundingTime") or source.get("next_funding_time_ms"),
                    "interestRate": source.get("interestRate"),
                    "time": source.get("time") or source.get("event_time"),
                },
                f"redis:v2:market:funding:{symbol}",
                "Binance mark-price WebSocket/cache primary; REST not used",
            )
    if path == "/fapi/v1/openInterest" and symbol:
        payload = _redis_sync_get_json(f"v2:market:open_interest:{symbol}")
        if isinstance(payload, dict):
            return (
                {
                    "symbol": payload.get("symbol") or symbol,
                    "openInterest": payload.get("openInterest") or payload.get("open_interest") or payload.get("open_interest_contracts"),
                    "time": payload.get("time") or payload.get("timestamp") or payload.get("event_time"),
                },
                f"redis:v2:market:open_interest:{symbol}",
                "Binance open-interest WebSocket/cache primary; REST not used",
            )
    if path == "/futures/data/openInterestHist" and symbol:
        payload = _redis_sync_get_json(f"v2:market:open_interest_hist:{symbol}:{params.get('period') or '5m'}")
        if isinstance(payload, list) and payload:
            return payload, f"redis:v2:market:open_interest_hist:{symbol}:{params.get('period') or '5m'}", "Binance open-interest history cache primary; REST not used"
    if path == "/futures/data/globalLongShortAccountRatio" and symbol:
        payload = _redis_sync_get_json(f"v2:market:long_short:{symbol}")
        if isinstance(payload, dict):
            return [payload], f"redis:v2:market:long_short:{symbol}", "Binance long/short cache primary; REST not used"
    if path == "/fapi/v1/depth" and symbol:
        for key in (f"v2:market:orderbook:binance:{symbol}", f"v2:market:orderbook:{symbol}", f"v2:orderbook:top:binance:{symbol}"):
            payload = _redis_sync_get_json(key)
            if not isinstance(payload, dict):
                continue
            bids = payload.get("bids") if isinstance(payload.get("bids"), list) else []
            asks = payload.get("asks") if isinstance(payload.get("asks"), list) else []
            if bids or asks:
                return {"lastUpdateId": payload.get("lastUpdateId") or payload.get("update_id"), "bids": bids, "asks": asks}, f"redis:{key}", "Binance depth WebSocket/cache primary; REST not used"
    if path == "/fapi/v1/klines" and symbol:
        timeframe = str(params.get("interval") or "1m")
        payload = _redis_sync_get_json(f"v2:market:ohlcv:binance:{symbol}:{timeframe}")
        if isinstance(payload, list):
            rows = [converted for row in payload if (converted := _redis_kline_to_binance_row(row)) is not None]
            if rows:
                return rows, f"redis:v2:market:ohlcv:binance:{symbol}:{timeframe}", "Binance kline WebSocket/cache primary; REST not used"
    if path == "/fapi/v1/trades" and symbol:
        payload = _redis_sync_get_json(f"v2:market:agg_trades:{symbol}")
        rows_source = payload.get("trades") if isinstance(payload, dict) and isinstance(payload.get("trades"), list) else payload
        if isinstance(rows_source, list):
            rows = [converted for row in rows_source if (converted := _redis_trade_to_binance_recent_trade(row)) is not None]
            if rows:
                return rows[-int(_float(params.get("limit")) or 80):], f"redis:v2:market:agg_trades:{symbol}", "Binance aggTrade WebSocket/cache primary; REST not used"
    return None, "redis:v2:market:*", None


def _binance_fetch_and_cache(url: str, cache_key: str) -> tuple[Any | None, str, str | None]:
    fallback = binance_rest_fallback_decision(
        endpoint=urllib.parse.urlparse(url).path or url,
        fallback_reason=f"market_contracts_websocket_cache_miss:{cache_key}",
        role="market_contracts_public_json_recovery",
    )
    if not fallback["request_allowed"]:
        return (
            None,
            "binance_rest_fallback_blocked_websocket_primary",
            f"Binance REST fallback blocked: {REST_FALLBACK_ENV}=true is required after WebSocket/cache miss",
        )
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
    finally:
        with BINANCE_PUBLIC_JSON_CACHE_LOCK:
            _BINANCE_REFRESH_IN_FLIGHT.discard(cache_key)


def _binance_public_json(path: str, params: dict[str, Any]) -> tuple[Any | None, str, str | None]:
    query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
    url = f"{BINANCE_FAPI_BASE}{path}" + (f"?{query}" if query else "")
    cache_key = f"{path}?{query}"
    if "binance.com" in BINANCE_FAPI_BASE:
        redis_payload, redis_source, redis_warning = _binance_public_json_from_redis(path, params)
        if redis_payload is not None:
            return redis_payload, redis_source, redis_warning
    now = time.monotonic()
    if BINANCE_PUBLIC_CACHE_TTL_SECONDS > 0:
        with BINANCE_PUBLIC_JSON_CACHE_LOCK:
            cached = BINANCE_PUBLIC_JSON_CACHE.get(cache_key)
            if cached is not None:
                age = now - cached[0]
                if age <= BINANCE_PUBLIC_CACHE_TTL_SECONDS:
                    return cached[1], cached[2], None
                # Stale-while-revalidate: serve the stale snapshot immediately
                # and refresh in the background, so request latency never
                # blocks on the upstream exchange once the cache is warm.
                if age <= BINANCE_PUBLIC_CACHE_STALE_MAX_SECONDS:
                    if cache_key not in _BINANCE_REFRESH_IN_FLIGHT:
                        _BINANCE_REFRESH_IN_FLIGHT.add(cache_key)
                        threading.Thread(
                            target=_binance_fetch_and_cache,
                            args=(url, cache_key),
                            name=f"binance-swr:{path}",
                            daemon=True,
                        ).start()
                    return cached[1], cached[2], None
    with BINANCE_PUBLIC_JSON_CACHE_LOCK:
        _BINANCE_REFRESH_IN_FLIGHT.add(cache_key)
    return _binance_fetch_and_cache(url, cache_key)


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
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="binance-snapshot") as pool:
        ticker_future = pool.submit(_binance_public_json, "/fapi/v1/ticker/24hr", {"symbol": safe_symbol})
        premium_future = pool.submit(_binance_public_json, "/fapi/v1/premiumIndex", {"symbol": safe_symbol})
        oi_future = pool.submit(_binance_public_json, "/fapi/v1/openInterest", {"symbol": safe_symbol})
        ticker, ticker_source, ticker_warning = ticker_future.result()
        premium, premium_source, premium_warning = premium_future.result()
        oi, oi_source, oi_warning = oi_future.result()
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
    fresh_max_seconds: float = 30,
    stale_min_seconds: float = 120,
) -> dict[str, Any]:
    # fresh_max_seconds / stale_min_seconds let slow-cadence analytical surfaces
    # (e.g. the adaptive-capital dashboard, recomputed every few minutes) declare a
    # freshness window matching their natural update rate instead of the tick-stream
    # default of 30s/120s.
    lag = _lag_ms(timestamp)
    unavailable = source_type == "unavailable"
    staleness_seconds = round(lag / 1000, 3) if lag is not None else None
    freshness_status = (
        "unavailable" if unavailable
        else "unknown" if staleness_seconds is None
        else "fresh" if staleness_seconds <= fresh_max_seconds
        else "stale" if staleness_seconds > stale_min_seconds
        else "degraded"
    )
    data_quality_status = (
        "unavailable" if unavailable
        else "partial" if missing_fields
        else "fresh" if freshness_status == "fresh"
        else freshness_status
    )
    response = {
        "schema_version": "api_v2_readonly_envelope_v1",
        "data": data,
        "source": source,
        "source_type": source_type,
        "endpoint": endpoint,
        "timestamp": timestamp,
        "timestamp_et": _to_et(timestamp),
        "generated_at_utc": timestamp,
        "generated_at_et": _to_et(timestamp),
        "generated_et": _to_et(timestamp),
        "received_at": _utc_now(),
        "received_et": _et_now(),
        "lag_ms": lag,
        "staleness_seconds": staleness_seconds,
        "freshness_status": freshness_status,
        "canonical_owner": endpoint,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
        "data_quality_status": data_quality_status,
        "stale": unavailable or lag is None or lag > stale_min_seconds * 1000,
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


def _high_confidence_cluster_derived_dimensions(
    cluster_payload: dict[str, Any],
) -> dict[str, Any]:
    rows = (
        cluster_payload.get("sample_high_confidence_losses")
        if isinstance(cluster_payload.get("sample_high_confidence_losses"), list)
        else []
    )
    sample_rows = [row for row in rows if isinstance(row, dict)]

    def _counts(*fields: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in sample_rows:
            value = None
            for field in fields:
                if row.get(field) not in (None, ""):
                    value = row.get(field)
                    break
            if value in (None, ""):
                continue
            key = str(value).strip().lower()
            if key:
                counts[key] = counts.get(key, 0) + 1
        return counts

    dimension_counts = cluster_payload.get("affected_dimension_counts")
    if not isinstance(dimension_counts, dict) or not dimension_counts:
        dimension_counts = {
            "side": _counts("side"),
            "timeframe": _counts("timeframe"),
            "strategy_mode": _counts("strategy_selected_mode", "strategy_mode", "strategy_id"),
        }
    affected_symbols = cluster_payload.get("affected_symbols")
    if not isinstance(affected_symbols, list) or not affected_symbols:
        affected_symbols = sorted(
            {
                str(row.get("symbol")).strip().upper()
                for row in sample_rows
                if row.get("symbol")
            }
        )
    return {
        "affected_symbols": affected_symbols,
        "affected_dimension_counts": dimension_counts,
        "quarantined_sides": cluster_payload.get("quarantined_sides")
        or sorted((dimension_counts.get("side") or {}).keys()),
        "quarantined_timeframes": cluster_payload.get("quarantined_timeframes")
        or sorted((dimension_counts.get("timeframe") or {}).keys()),
        "quarantined_strategy_modes": cluster_payload.get("quarantined_strategy_modes")
        or sorted((dimension_counts.get("strategy_mode") or {}).keys()),
    }


def _advanced_indicator_runtime_summary(
    *,
    preemptive_matrix: dict[str, Any] | None,
    preemptive_status: dict[str, Any] | None = None,
    admission_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    matrix = preemptive_matrix if isinstance(preemptive_matrix, dict) else {}
    rows = matrix.get("rows") or matrix.get("sample_decisions") or []
    rows = [row for row in rows if isinstance(row, dict)]
    status_counts: dict[str, int] = {}
    block_reasons: dict[str, int] = {}
    caution_reasons: dict[str, int] = {}
    fvg_present = 0
    fvg_side_aligned = 0
    for row in rows:
        status = str(
            row.get("advanced_indicator_status")
            or "ADVANCED_INDICATOR_NOT_REPORTED"
        )
        status_counts[status] = status_counts.get(status, 0) + 1
        if row.get("fvg_present") is True:
            fvg_present += 1
        if row.get("fvg_side_aligned") is True:
            fvg_side_aligned += 1
        for reason in row.get("advanced_indicator_block_reasons") or []:
            text = str(reason)
            block_reasons[text] = block_reasons.get(text, 0) + 1
        for reason in row.get("advanced_indicator_caution_reasons") or []:
            text = str(reason)
            caution_reasons[text] = caution_reasons.get(text, 0) + 1
    accepted_block_count = None
    if isinstance(admission_status, dict):
        accepted_block_count = admission_status.get(
            "accepted_advanced_indicator_block_count"
        )
    return {
        "schema_version": "advanced_indicator_runtime_truth_v1",
        "status": (
            "ADVANCED_INDICATOR_DECISION_CONSUMPTION_ACTIVE"
            if rows
            else "ADVANCED_INDICATOR_WAITING_FOR_PREEMPTIVE_MATRIX"
        ),
        "candidate_count": len(rows),
        "preemptive_candidate_count": (
            preemptive_status.get("candidate_count")
            if isinstance(preemptive_status, dict)
            else matrix.get("candidate_count")
        ),
        "status_counts": status_counts,
        "block_reason_counts": block_reasons,
        "caution_reason_counts": caution_reasons,
        "fvg_present_count": fvg_present,
        "fvg_side_aligned_count": fvg_side_aligned,
        "accepted_advanced_indicator_block_count": accepted_block_count,
        "fvg_standalone_allows_trade": False,
        "fvg_alone_can_approve_trade": False,
        "sweep_risk_can_block_or_reduce": True,
        "displayed_without_decision_consumption": False,
        "routes_to_live": False,
        "places_real_order": False,
        "paper_only": True,
    }


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
        "confidence_directional_long": _float(row.get("confidence_directional_long")),
        "confidence_directional_short": _float(row.get("confidence_directional_short")),
        "confidence_hold": _float(row.get("confidence_hold")),
        "confidence_selected_action": _float(row.get("confidence_selected_action")),
        "confidence_post_cost_long": _float(row.get("confidence_post_cost_long")),
        "confidence_post_cost_short": _float(row.get("confidence_post_cost_short")),
        "confidence_executable_trade": _float(row.get("confidence_executable_trade")),
        "confidence_display_label": row.get("confidence_display_label"),
        "confidence_type": row.get("confidence_type"),
        "confidence_a_plus_eligible": row.get("confidence_a_plus_eligible") is True,
        "confidence_tradeability_block_reasons": _as_list(row.get("confidence_tradeability_block_reasons")),
        "paper_exploration_tier": row.get("paper_exploration_tier") or row.get("exploration_tier"),
        "exploration_tier": row.get("exploration_tier") or row.get("paper_exploration_tier"),
        "expected_net_pnl_usd": _float(row.get("expected_net_pnl_usd")),
        "expected_max_loss_usd": _float(row.get("expected_max_loss_usd") or row.get("max_loss_usd")),
        "why_not_a_plus": _as_list(row.get("block_reasons")),
        "why_not_live_ready": _as_list(row.get("live_ready_block_reasons") or row.get("block_reasons")),
        "risk_controller_decision": row.get("risk_decision") or row.get("risk_state"),
        "allocator_decision": row.get("allocator_decision"),
        "trainer_feedback_status": row.get("trainer_feedback_status"),
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


def _runtime_canonical_paper_account(client: Any | None) -> dict[str, Any]:
    portfolio: dict[str, Any] = {}
    session: dict[str, Any] = {}
    ledger: dict[str, Any] = {}
    if client is not None:
        for key, target in (
            ("v2:portfolio:state", portfolio),
            ("v2:paper:session", session),
        ):
            try:
                payload = _json_object_from_redis_raw(client.get(key))
            except Exception:
                payload = None
            if isinstance(payload, dict):
                target.update(payload)

    ledger_loaded = False

    def _ledger() -> dict[str, Any]:
        nonlocal ledger, ledger_loaded
        if ledger_loaded:
            return ledger
        ledger_loaded = True
        if client is None:
            return ledger
        try:
            payload = _json_object_from_redis_raw(client.get("v2:paper:ledger"))
        except Exception:
            payload = None
        if isinstance(payload, dict):
            ledger.update(payload)
        return ledger

    def _first_present(*values: Any) -> Any:
        for value in values:
            if value is not None and value != "":
                return value
        return None

    starting_equity = _float(
        _first_present(
            session.get("starting_equity_usd"),
            portfolio.get("starting_equity_usd"),
            portfolio.get("initial_capital"),
        )
    )
    if starting_equity is None:
        ledger_payload = _ledger()
        starting_equity = _float(
            _first_present(
                ledger_payload.get("starting_equity_usd"),
                ledger_payload.get("initial_capital"),
            )
        )
    equity = _float(portfolio.get("equity"))
    realized_pnl = _float(
        _first_present(
            portfolio.get("realized_net_pnl_usd"),
            portfolio.get("clean_session_valid_realized_pnl_usd"),
            portfolio.get("realized_pnl_usd"),
            portfolio.get("realized_pnl"),
        )
    )
    if realized_pnl is None:
        realized_pnl = _float(_first_present(_ledger().get("realized_pnl_usd"), 0.0))
    unrealized_pnl = _float(
        _first_present(
            portfolio.get("unrealized_pnl_usd"),
            portfolio.get("unrealized_pnl"),
        )
    )
    if unrealized_pnl is None:
        unrealized_pnl = _float(_first_present(_ledger().get("unrealized_pnl_usd"), 0.0))
    open_positions = _integer(
        portfolio.get("open_positions_count")
    )
    if open_positions is None:
        ledger_payload = _ledger()
        open_position_count = _first_present(ledger_payload.get("open_position_count"))
        if open_position_count is None:
            open_position_count = len(ledger_payload.get("open_positions") or [])
        open_positions = _integer(open_position_count)
    closed_trades = _integer(
        _first_present(
            portfolio.get("closed_trade_count"),
            portfolio.get("closed_positions_count"),
        )
    )
    if closed_trades is None:
        closed_trades = _integer(_ledger().get("closed_trade_count"))
    paper_session_id = (
        session.get("paper_session_id")
        or portfolio.get("paper_session_id")
        or session.get("session_id")
        or portfolio.get("session_id")
    )
    if paper_session_id is None:
        ledger_payload = _ledger()
        paper_session_id = (
            ledger_payload.get("paper_session_id")
            or ledger_payload.get("session_id")
        )
    source_keys = [
        key for key, payload in (
            ("v2:portfolio:state", portfolio),
            ("v2:paper:session", session),
            ("v2:paper:ledger", ledger if ledger_loaded else {}),
        )
        if payload
    ]
    return {
        "currency": "USDT",
        "paper_session_id": paper_session_id,
        "starting_equity": starting_equity,
        "starting_equity_usd": starting_equity,
        "initial_capital": starting_equity,
        "equity": equity,
        "available_balance": equity,
        "available_balance_usd": equity,
        "available_balance_scope": "PAPER_SIM_ACCOUNT_NOT_LIVE_SIGNED_ACCOUNT",
        "available_balance_source": "paper_equity_from_v2_portfolio_state",
        "used_balance": 0.0,
        "realized_pnl": realized_pnl,
        "realized_pnl_usd": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pnl_usd": unrealized_pnl,
        "open_position_count": open_positions or 0,
        "closed_trade_count": closed_trades or 0,
        "position_source": "redis:v2:portfolio:state",
        "source": "redis:" + "+".join(source_keys) if source_keys else "unavailable",
        "source_keys": source_keys,
        "account_scope": "PAPER_SIM_ACCOUNT",
        "paper_or_live": "paper",
        "contains_simulated_positions": True,
        "contains_live_positions": False,
        "contains_quarantined_positions": False,
        "equity_trusted": portfolio.get("equity_trusted", True),
        "pnl_trusted": portfolio.get("pnl_trusted", True),
        "reason_if_untrusted": portfolio.get("reason_if_untrusted"),
    }


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


def _enrich_overview_rows_from_redis(ticker_rows: list[dict[str, Any]]) -> None:
    """Merge ingestor-published funding/OI/long-short into overview rows.

    Reads only symbols the native ingestors already track (bounded pipeline
    read), so the overview table can show derivatives columns without any
    extra exchange calls. Rows without Redis data keep None values.
    """
    redis_client = get_redis()
    if redis_client is None or not ticker_rows:
        return
    try:
        rows_by_symbol = {
            row["symbol"]: row
            for row in ticker_rows[:256]
            if isinstance(row.get("symbol"), str)
        }
        if not rows_by_symbol:
            return
        ordered_symbols = list(rows_by_symbol)
        pipe = redis_client.pipeline()
        for symbol in ordered_symbols:
            pipe.get(f"v2:market:funding:{symbol}")
            pipe.get(f"v2:market:open_interest:{symbol}")
            pipe.get(f"v2:market:long_short:{symbol}")
        results = pipe.execute()
        for index, symbol in enumerate(ordered_symbols):
            row = rows_by_symbol[symbol]
            funding_raw, oi_raw, ls_raw = results[index * 3 : index * 3 + 3]
            try:
                funding = json.loads(funding_raw) if funding_raw else None
                if isinstance(funding, dict):
                    row["funding_rate"] = _float(funding.get("lastFundingRate"))
                    row["mark_price"] = _float(funding.get("markPrice"))
                oi = json.loads(oi_raw) if oi_raw else None
                if isinstance(oi, dict):
                    row["open_interest"] = _float(oi.get("openInterest"))
                long_short = json.loads(ls_raw) if ls_raw else None
                if isinstance(long_short, dict):
                    row["long_short_ratio"] = _float(
                        long_short.get("long_short_ratio") or long_short.get("longShortRatio")
                    )
            except (TypeError, ValueError):
                continue
    except Exception:
        return


def _epoch_ms_to_utc(value: Any) -> str | None:
    number = _float(value)
    if number is None:
        return None
    seconds = number / 1000.0 if number > 10_000_000_000 else number
    try:
        return datetime.fromtimestamp(seconds, UTC).isoformat().replace("+00:00", "Z")
    except (OSError, OverflowError, ValueError):
        return None


def _redis_market_overview_rows(limit: int = MARKET_OVERVIEW_REDIS_LIMIT) -> tuple[list[dict[str, Any]], str | None]:
    if not (_repo_root() / "v2" / "backend" / "app").exists():
        return [], None
    redis_client = get_redis()
    if redis_client is None:
        return [], None
    bounded_limit = max(1, min(500, int(limit)))
    symbols = [symbol for symbol in MARKET_OVERVIEW_REDIS_SYMBOLS if _strict_market_symbol(symbol)]
    if not symbols:
        return [], None
    keys = [f"v2:market:kline_current:binance:{symbol}:1m" for symbol in symbols[:bounded_limit]]
    try:
        pipe = redis_client.pipeline()
        for key in keys:
            pipe.get(key)
        raw_rows = pipe.execute()
    except Exception:
        return [], None

    rows: list[dict[str, Any]] = []
    newest_ms: float | None = None
    for raw in raw_rows:
        if raw is None:
            continue
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            payload = json.loads(str(raw))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        symbol = _strict_market_symbol(str(payload.get("symbol") or ""))
        if not symbol or not symbol.endswith("USDT"):
            continue
        ohlcv = payload.get("ohlcv") if isinstance(payload.get("ohlcv"), dict) else {}
        quote_volume = _float(payload.get("quote_volume") or ohlcv.get("quote_volume"))
        event_ms = _float(
            payload.get("available_at")
            or payload.get("ingested_at")
            or payload.get("event_time")
            or payload.get("ts")
        )
        if event_ms is not None:
            newest_ms = event_ms if newest_ms is None else max(newest_ms, event_ms)
        rows.append({
            "symbol": symbol,
            "last_price": _float(payload.get("close") or ohlcv.get("close")),
            "change_24h": None,
            "high_24h": None,
            "low_24h": None,
            "volume_24h": None,
            "turnover_24h": quote_volume,
            "trade_count_24h": int(_float(payload.get("num_trades") or ohlcv.get("num_trades")) or 0),
            "weighted_avg_price": None,
            "funding_rate": None,
            "mark_price": None,
            "open_interest": None,
            "long_short_ratio": None,
            "source": payload.get("source") or "redis:v2:market:kline_current",
            "event_time": _epoch_ms_to_utc(payload.get("event_time")),
            "available_at": _epoch_ms_to_utc(payload.get("available_at") or payload.get("ingested_at")),
            "feature_cutoff": _epoch_ms_to_utc(payload.get("candle_close_time") or payload.get("close_time")),
            "candle_closed_confirmed": bool(
                payload.get("candle_closed_confirmed")
                or payload.get("closed_candle")
                or payload.get("is_closed")
            ),
            "feature_eligible": bool(payload.get("feature_eligible")),
            "display_only_current_candle": not bool(
                payload.get("candle_closed_confirmed")
                or payload.get("closed_candle")
                or payload.get("is_closed")
            ),
        })
    rows.sort(key=lambda item: (_float(item.get("turnover_24h")) or 0.0, item["symbol"]), reverse=True)
    _enrich_overview_rows_from_redis(rows)
    return rows, _epoch_ms_to_utc(newest_ms) or _utc_now()


@router.get("/market/overview")
async def get_market_overview() -> dict[str, Any]:
    endpoint = "/api/v2/market/overview"
    redis_rows, redis_timestamp = _redis_market_overview_rows()
    if redis_rows:
        symbols = [row["symbol"] for row in redis_rows]
        return _base_response(
            endpoint=endpoint,
            data={
                "symbols": symbols,
                "count": len(symbols),
                "timeframes": ["1m", "3m", "5m", "15m", "1h", "4h", "1d", "1w"],
                "tickers": redis_rows,
                "canonical_runtime_source": "redis:v2:market:kline_current:binance:*:1m",
                "display_rows_are_current_candles": True,
                "feature_inputs_must_use_closed_candles": True,
            },
            source="redis:v2:market:kline_current:binance:*:1m",
            source_type="redis_live",
            timestamp=redis_timestamp,
            missing_fields=[],
            warnings=[
                "Market overview served from native ingestor Redis for control-center latency",
                "Rows are display-only current candles; feature/training paths must use closed-candle gates",
                "Live trading and exchange mutation remain disabled",
            ],
            mode="read_only",
        )
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
        _enrich_overview_rows_from_redis(ticker_rows)
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


@router.get("/markets")
async def get_markets_contract() -> dict[str, Any]:
    """Compatibility alias for frontend/mobile consumers expecting `/api/v2/markets`."""
    response = dict(await get_market_overview())
    response["endpoint"] = "/api/v2/markets"
    return response


@router.get("/derivatives")
async def get_derivatives_contract() -> dict[str, Any]:
    """Aggregate derivatives contract for `/api/v2/derivatives`.

    Uses the existing operator-truth builder in read-only mode. This route
    never places orders, calls test-order, changes leverage/margin, or writes
    Redis/exchange state.
    """
    endpoint = "/api/v2/derivatives"
    try:
        from app.services.operator_truth.trade_derivatives_runtime import (
            DERIVATIVES_OUT,
            build_derivatives_payload,
            json_load,
        )

        cached_payload = json_load(DERIVATIVES_OUT / "derivatives_payload.json", None)
        if isinstance(cached_payload, dict):
            payload = cached_payload
            payload_source = "operator_runtime/v2_derivatives/latest/derivatives_payload.json"
        else:
            payload = await run_in_threadpool(build_derivatives_payload)
            payload_source = "app.services.operator_truth.trade_derivatives_runtime.build_derivatives_payload"
    except Exception as exc:
        return _base_response(
            endpoint=endpoint,
            data={
                "schema_version": "v2_derivatives_payload_v1",
                "symbols": [],
                "modules": {},
                "live_submit_allowed": False,
                "live_submit_blocker": "DERIVATIVES_PAYLOAD_UNAVAILABLE",
            },
            source="app.services.operator_truth.trade_derivatives_runtime",
            source_type="unavailable",
            timestamp=None,
            missing_fields=["derivatives_payload"],
            warnings=[
                f"Derivatives payload builder failed: {type(exc).__name__}",
                "Read-only derivatives endpoint failed closed and did not mutate exchange state",
            ],
            mode="read_only",
        )

    modules = payload.get("modules") if isinstance(payload.get("modules"), dict) else {}
    required_modules = ("funding", "open_interest", "long_short", "basis", "liquidations")
    missing = [name for name in required_modules if name not in modules]
    for name in required_modules:
        module = modules.get(name)
        if isinstance(module, dict) and str(module.get("data_status") or "").startswith("NO_CURRENT_"):
            missing.append(name)

    return _base_response(
        endpoint=endpoint,
        data=payload,
        source=payload_source,
        source_type="static_payload" if modules else "unavailable",
        timestamp=_timestamp_from_payload(payload) or _utc_now(),
        missing_fields=sorted(set(missing)),
        warnings=[
            "Derivatives contract is read-only; live_submit_allowed remains false",
            "Public/Redis derivatives sources cannot approve final A+ execution by themselves",
        ],
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
    warnings: list[str] = []
    surface_timeout_seconds = float(os.environ.get("V2_DATA_HEALTH_SURFACE_TIMEOUT_SECONDS", "6"))

    async def _surface_payload(path: str) -> tuple[dict[str, Any] | None, str | None]:
        try:
            handled, payload = await asyncio.wait_for(
                _readonly_resource_direct_payload(path, None),
                timeout=surface_timeout_seconds,
            )
        except TimeoutError:
            return None, f"{path}: timeout_after_{surface_timeout_seconds:g}s"
        except Exception as exc:
            return None, f"{path}: {type(exc).__name__}: {exc}"
        if not handled or not isinstance(payload, dict):
            return None, f"{path}: route_not_resolved"
        return payload, None

    def _base_surface(
        *,
        name: str,
        endpoint: str,
        status: str,
        description: str,
        payload: dict[str, Any] | None = None,
        actual_payload_count: int | None = None,
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "name": name,
            "endpoint": endpoint,
            "status": status,
            "description": description,
        }
        if actual_payload_count is not None:
            row["actual_payload_count"] = actual_payload_count
        if isinstance(payload, dict):
            row["source_type"] = payload.get("source_type")
            row["stale"] = payload.get("stale")
            row["lag_ms"] = payload.get("lag_ms")
            row["missing_fields"] = payload.get("missing_fields") or []
            row["last_success"] = payload.get("received_at") or payload.get("timestamp")
        return row

    surfaces: list[dict[str, Any]] = []
    surface_paths = [
        "/api/v2/market/overview",
        "/api/v2/signals",
        "/api/v2/portfolio",
        "/api/v2/mobile/alerts?limit=30",
        "/api/v2/trainer/summary",
        "/api/v2/backtests",
    ]
    surface_results = dict(
        zip(
            surface_paths,
            await asyncio.gather(*(_surface_payload(path) for path in surface_paths)),
            strict=True,
        )
    )

    market_payload, market_error = surface_results["/api/v2/market/overview"]
    market_data = market_payload.get("data") if isinstance(market_payload, dict) else {}
    market_tickers = market_data.get("tickers") if isinstance(market_data, dict) else []
    market_count = len(market_tickers) if isinstance(market_tickers, list) else 0
    market_unavailable = not isinstance(market_payload, dict) or market_payload.get("source_type") == "unavailable"
    if market_error:
        warnings.append(market_error)
    market_status = (
        "ok"
        if not market_unavailable and market_count > 0 and market_payload.get("stale") is not True
        else "partial"
        if not market_unavailable and market_count > 0
        else "error"
    )
    surfaces.append(_base_surface(
        name="Market data",
        endpoint="/api/v2/market/overview",
        status=market_status,
        description=f"Exchange ticker feed with {market_count} current ticker rows",
        payload=market_payload,
        actual_payload_count=market_count,
    ))

    signal_payload, signal_error = surface_results["/api/v2/signals"]
    signal_data = signal_payload.get("data") if isinstance(signal_payload, dict) else {}
    active_signal = signal_data.get("active_signal") if isinstance(signal_data, dict) else None
    signal_unavailable = not isinstance(signal_payload, dict) or signal_payload.get("source_type") == "unavailable"
    if signal_error:
        warnings.append(signal_error)
    signal_status = (
        "ok"
        if not signal_unavailable and isinstance(active_signal, dict)
        else "partial"
        if not signal_unavailable
        else "error"
    )
    surfaces.append(_base_surface(
        name="Signal feed",
        endpoint="/api/v2/signals",
        status=signal_status,
        description="Latest paper signal payload from Redis/runtime fallback" if isinstance(active_signal, dict) else "Signal endpoint reachable; no active signal payload",
        payload=signal_payload,
        actual_payload_count=1 if isinstance(active_signal, dict) else 0,
    ))

    portfolio_payload, portfolio_error = surface_results["/api/v2/portfolio"]
    portfolio_data = portfolio_payload.get("data") if isinstance(portfolio_payload, dict) else {}
    positions = portfolio_data.get("positions") if isinstance(portfolio_data, dict) else []
    portfolio_count = len(positions) if isinstance(positions, list) else 0
    equity_present = isinstance(portfolio_data, dict) and portfolio_data.get("equity") is not None
    portfolio_unavailable = not isinstance(portfolio_payload, dict) or portfolio_payload.get("source_type") == "unavailable"
    if portfolio_error:
        warnings.append(portfolio_error)
    portfolio_status = (
        "ok"
        if not portfolio_unavailable and equity_present and portfolio_payload.get("stale") is not True
        else "partial"
        if not portfolio_unavailable and (equity_present or portfolio_count >= 0)
        else "error"
    )
    surfaces.append(_base_surface(
        name="Portfolio",
        endpoint="/api/v2/portfolio",
        status=portfolio_status,
        description=f"Paper portfolio state with equity {'present' if equity_present else 'missing'} and {portfolio_count} open rows",
        payload=portfolio_payload,
        actual_payload_count=1 if equity_present else portfolio_count,
    ))

    alerts_payload, alerts_error = surface_results["/api/v2/mobile/alerts?limit=30"]
    alerts_data = alerts_payload.get("data") if isinstance(alerts_payload, dict) else alerts_payload
    alert_rows = alerts_data.get("alerts") if isinstance(alerts_data, dict) else []
    alert_count = len(alert_rows) if isinstance(alert_rows, list) else 0
    alerts_unavailable = not isinstance(alerts_payload, dict) or alerts_payload.get("source_type") == "unavailable"
    if alerts_error:
        warnings.append(alerts_error)
    alerts_status = "ok" if not alerts_unavailable else "partial"
    surfaces.append(_base_surface(
        name="Alerts",
        endpoint="/api/v2/mobile/alerts",
        status=alerts_status,
        description=f"Read-only alert feed reachable with {alert_count} recent rows",
        payload=alerts_payload,
        actual_payload_count=alert_count,
    ))

    trainer_payload, trainer_error = surface_results["/api/v2/trainer/summary"]
    trainer_state = str(trainer_payload.get("state") or "").upper() if isinstance(trainer_payload, dict) else ""
    trainer_active = bool(trainer_payload.get("cuda_active")) or "ACTIVE" in trainer_state
    trainer_missing = trainer_state in {"", "MISSING_EVIDENCE", "BLOCKED_NO_TRUSTED_FEEDBACK", "UNKNOWN"}
    if trainer_error:
        warnings.append(trainer_error)
    trainer_status = "ok" if trainer_active and not trainer_missing else "partial" if isinstance(trainer_payload, dict) else "error"
    surfaces.append(_base_surface(
        name="Trainer",
        endpoint="/api/v2/trainer/summary",
        status=trainer_status,
        description=f"Trainer runtime state {trainer_state or 'UNKNOWN'}",
        payload=trainer_payload,
        actual_payload_count=1 if isinstance(trainer_payload, dict) and not trainer_missing else 0,
    ))

    backtests_payload, backtests_error = surface_results["/api/v2/backtests"]
    backtest_data = backtests_payload.get("data") if isinstance(backtests_payload, dict) else {}
    backtest_rows = (backtest_data.get("backtests") or backtest_data.get("runs") or []) if isinstance(backtest_data, dict) else []
    backtest_count = len(backtest_rows) if isinstance(backtest_rows, list) else 0
    if backtests_error:
        warnings.append(backtests_error)
    backtests_status = "ok" if backtest_count > 0 else "pending" if isinstance(backtests_payload, dict) else "error"
    surfaces.append(_base_surface(
        name="Backtests",
        endpoint="/api/v2/backtests",
        status=backtests_status,
        description=f"Backtest route reachable; {backtest_count} current run rows",
        payload=backtests_payload,
        actual_payload_count=backtest_count,
    ))

    websocket_status = "ok" if market_status == "ok" and signal_status in {"ok", "partial"} else "partial"
    surfaces.append({
        "name": "WebSocket",
        "endpoint": "/api/v2/ws/resource",
        "status": websocket_status,
        "description": "Versioned resource WebSocket route is the shared web/iOS stream; HTTP fallback remains enabled",
        "actual_payload_count": sum(1 for row in surfaces if row.get("actual_payload_count", 0) > 0),
        "source_type": "websocket_resource_contract",
        "stale": False,
        "missing_fields": [],
    })

    status_set = {str(row.get("status")) for row in surfaces}
    core_ok = market_status == "ok" and signal_status in {"ok", "partial"} and portfolio_status in {"ok", "partial"}
    overall = "error" if "error" in status_set and not core_ok else "partial" if status_set & {"partial", "pending"} else "ok"
    # Consolidated ingestor / provider-health roll-up (presence-based; read-only).
    try:
        ingestors_rollup = _ingestors_payload(get_redis())
    except Exception:  # pragma: no cover - display convenience must never break data health
        ingestors_rollup = {
            "overall_status": "UNKNOWN",
            "all_core_streams_present": False,
            "stream_present": {},
            "active_provider_count": 0,
            "stale_provider_count": 0,
        }
    return _base_response(
        endpoint=endpoint,
        data={
            "overall": overall,
            "surfaces": surfaces,
            "count": len(surfaces),
            "ingestors": ingestors_rollup,
        },
        source="v2_health_check",
        source_type="api",
        timestamp=_utc_now(),
        missing_fields=[],
        warnings=warnings,
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
    readiness_context = _paper_a_grade_readiness_context(get_redis())
    payload = {
        **payload,
        "real_trader_readiness": readiness_context,
        "a_grade_blocker_truth": readiness_context["a_grade_blocker_truth"],
        "exact_no_live_reason": readiness_context["exact_no_live_reason"],
        "readiness_blockers": readiness_context["readiness_blockers"],
        "top_blockers": readiness_context["readiness_blockers"][:8],
    }
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
        # Recomputed on a loop by v2_adaptive_capital_productivity_status (a ~2.5min
        # counterfactual sweep). Fresh within 10 min, stale beyond 30 min — matches
        # the analytical cadence rather than the tick-stream 30s/120s default.
        fresh_max_seconds=600,
        stale_min_seconds=1800,
    )
    response["real_trader_readiness"] = readiness_context
    response["a_grade_blocker_truth"] = readiness_context["a_grade_blocker_truth"]
    response["exact_no_live_reason"] = readiness_context["exact_no_live_reason"]
    response["readiness_blockers"] = readiness_context["readiness_blockers"]
    response["top_blockers"] = readiness_context["readiness_blockers"][:8]
    return response


@router.get("/allocator/status")
async def get_allocator_status() -> dict[str, Any]:
    response = dict(await get_adaptive_capital_dashboard())
    response["endpoint"] = "/api/v2/allocator/status"
    response["canonical_owner"] = "/api/v2/allocator/status"
    response["alias_of"] = "/api/v2/adaptive-capital/dashboard"
    data = response.get("data")
    if isinstance(data, dict):
        data["alias_of"] = "/api/v2/adaptive-capital/dashboard"
    return response


@router.get("/allocator")
async def get_allocator_contract() -> dict[str, Any]:
    response = dict(await get_allocator_status())
    response["endpoint"] = "/api/v2/allocator"
    response["canonical_owner"] = "/api/v2/allocator"
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
        await _send_websocket_json_bounded(websocket, await _market_stream_snapshot(symbol or "", timeframe or ""))
        await websocket.close(code=1008)
        return

    if not await _send_websocket_json_bounded(websocket, await _market_stream_snapshot(symbol, timeframe)):
        return

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
            if not await _send_websocket_json_bounded(websocket, await _market_stream_snapshot(symbol, timeframe)):
                return
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
                    if not await _send_websocket_json_bounded(
                        websocket,
                        _native_stream_snapshot(safe_symbol, state),
                    ):
                        return True
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
    try:
        canonical_pnl_payload = build_canonical_pnl(get_redis())
    except Exception:
        canonical_pnl_payload = {}
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
        _paper_initial_capital = (
            _float(portfolio_state.get("starting_equity_usd"))
            or _float(portfolio_state.get("initial_capital"))
            or _float(redis_hb.get("starting_equity_usd"))
            or _float(redis_hb.get("initial_capital"))
            or PAPER_INITIAL_CAPITAL
        )
        _paper_session_id = (
            portfolio_state.get("paper_session_id")
            or portfolio_state.get("session_id")
            or redis_hb.get("paper_session_id")
            or redis_hb.get("session_id")
        )
        def _first_not_none(*values: Any) -> Any:
            for value in values:
                if value is not None:
                    return value
            return None
        if not _repo_has_pnl and portfolio_state:
            _ps_equity = _float(portfolio_state.get("equity"))
            _ps_rpnl = _first_not_none(
                _float(portfolio_state.get("realized_net_pnl_usd")),
                _float(portfolio_state.get("clean_session_valid_realized_pnl_usd")),
                _float(portfolio_state.get("realized_pnl_usd")),
            )
            _ps_upnl = _first_not_none(
                _float(portfolio_state.get("unrealized_pnl_usd")),
                _float(portfolio_state.get("net_unrealized_pnl")),
            )
            if _ps_equity is not None:
                equity = _ps_equity
                realized_pnl = _ps_rpnl
                unrealized_pnl = _ps_upnl
        elif equity is None and redis_hb:
            realized_pnl = realized_pnl if realized_pnl is not None else _float(redis_hb.get("realized_pnl_usd"))
            unrealized_pnl = unrealized_pnl if unrealized_pnl is not None else _float(redis_hb.get("unrealized_pnl_usd"))
            equity = round(_paper_initial_capital + (realized_pnl or 0) + (unrealized_pnl or 0), 4)
        if position_metrics is not None:
            unrealized_pnl = position_metrics.get("unrealized_pnl_usd")
            should_synthesize_equity = (
                equity is None
                or (
                    _float(portfolio_state.get("equity")) is None
                    and repository_equity == _paper_initial_capital
                    and not _repo_has_pnl
                )
            )
            if should_synthesize_equity:
                base_realized_for_equity = realized_pnl if realized_pnl is not None else _float(redis_hb.get("realized_pnl_usd")) or 0.0
                equity = round(_paper_initial_capital + base_realized_for_equity + (unrealized_pnl or 0.0), 4)
        realized_gross_pnl = _first_not_none(
            _float(portfolio_state.get("realized_gross_pnl_usd")),
            _float(portfolio_state.get("gross_pnl_usd")),
        )
        realized_for_total = _float(realized_pnl)
        unrealized_for_total = _float(unrealized_pnl)
        total_pnl = _first_not_none(
            _float(portfolio_state.get("total_pnl_usd")),
            (realized_for_total + unrealized_for_total)
            if realized_for_total is not None and unrealized_for_total is not None
            else None,
        )
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
            # Canonical PnL source (Phase 2 implementation)
            "pnl_source_key": "v2:portfolio:state",
            "pnl_source_route": "/api/v2/portfolio",
            "pnl_source_type": "CANONICAL_CURRENT_SESSION_RUNTIME",
            "equity": equity,
            "paper_equity": equity,
            "paper_balance": equity,
            "available_balance": equity,
            "available_balance_usd": equity,
            "available_balance_scope": "PAPER_SIM_ACCOUNT_NOT_LIVE_SIGNED_ACCOUNT",
            "available_balance_source": "paper_equity_from_v2_portfolio_state_not_live_signed_account",
            "used_balance": _notional or 0.0,
            "paper_initial_capital": _paper_initial_capital,
            "initial_capital": _paper_initial_capital,
            "starting_equity_usd": _paper_initial_capital,
            "paper_session_id": _paper_session_id,
            "paper_equity_usd": (
                canonical_pnl_payload.get("paper_equity_usd")
                if portfolio_state else equity
            ),
            # Net PnL (primary economic metric)
            "realized_net_pnl_usd": _clamp_pnl(realized_pnl),
            "realized_gross_pnl_usd": _clamp_pnl(realized_gross_pnl),
            "total_pnl_usd": _clamp_pnl(total_pnl),
            "paper_realized_pnl_usd": (
                canonical_pnl_payload.get("paper_realized_pnl_usd")
                if portfolio_state else _clamp_pnl(realized_pnl)
            ),
            "paper_unrealized_pnl_usd": (
                canonical_pnl_payload.get("paper_unrealized_pnl_usd")
                if portfolio_state else _clamp_pnl(unrealized_pnl)
            ),
            "paper_total_pnl_usd": (
                canonical_pnl_payload.get("paper_total_pnl_usd")
                if portfolio_state else _clamp_pnl(total_pnl)
            ),
            # Legacy aliases (for backwards compatibility)
            "realized_pnl": _clamp_pnl(realized_pnl),
            "realized_pnl_usd": _clamp_pnl(realized_pnl),
            "unrealized_pnl": _clamp_pnl(unrealized_pnl),
            "unrealized_pnl_usd": _clamp_pnl(unrealized_pnl),
            "open_position_count": _open_count,
            "closed_trade_count": _closed_count,
            "total_open_notional": _notional,
            "position_pricing": position_metrics,
            "positions": positions,
            "mode": "paper",
            "trader_id": repository_account.get("trader_id"),
            "paper_account_id": repository_account.get("paper_account_id"),
            "account_scope": "authenticated_trader",
            "source_type": portfolio_state.get("source_type") or portfolio_state_source_type or "paper_sim_repository",
            "paper_or_live": "paper",
            "contains_simulated_positions": True,
            "contains_live_positions": False,
            "contains_quarantined_positions": bool(portfolio_state.get("contains_quarantined_positions")),
            "equity_trusted": portfolio_state.get("equity_trusted") is not False,
            "pnl_trusted": portfolio_state.get("pnl_trusted") is not False,
            # Canonical source fields (passed from portfolio_state)
            "pnl_source_key": portfolio_state.get("pnl_source_key", "v2:portfolio:state"),
            "pnl_source_route": portfolio_state.get("pnl_source_route", "/api/v2/portfolio"),
            "pnl_source_type": portfolio_state.get("pnl_source_type", "CANONICAL_CURRENT_SESSION_RUNTIME"),
            "pnl_conflict_detected": portfolio_state.get("pnl_conflict_detected", False),
            "pnl_conflict_reason": portfolio_state.get("pnl_conflict_reason"),
            "pnl_conflict_sources": portfolio_state.get("pnl_conflict_sources", []),
            "data_source": (
                canonical_pnl_payload.get("data_source")
                if portfolio_state else portfolio_state.get("pnl_source_key", "v2:portfolio:state")
            ),
            "staleness_seconds": (
                canonical_pnl_payload.get("staleness_seconds")
                if portfolio_state else portfolio_state.get("freshness_seconds")
            ),
            "freshness_status": (
                canonical_pnl_payload.get("freshness_status")
                if portfolio_state else None
            ),
            "closed_ledger_net_pnl_usd": portfolio_state.get("closed_ledger_net_pnl_usd"),
            "portfolio_realized_matches_closed_ledger": portfolio_state.get("portfolio_realized_matches_closed_ledger"),
            "equity_reconciles_within_1_cent": portfolio_state.get("equity_reconciles_within_1_cent"),
            "source_generated_utc": portfolio_state.get("generated_utc") or portfolio_state.get("generated_at"),
            "freshness_seconds": portfolio_state.get("freshness_seconds"),
            "reason_if_untrusted": portfolio_state.get("reason_if_untrusted"),
            "invalid_admission_accepted_excluded": portfolio_state.get("invalid_admission_accepted_excluded"),
            "invalid_admission_closed_trades_excluded": portfolio_state.get("invalid_admission_closed_trades_excluded"),
            "raw_equity_including_invalid_admissions_usd": portfolio_state.get("raw_equity_including_invalid_admissions_usd"),
            "clean_session_valid_equity_usd": portfolio_state.get("clean_session_valid_equity_usd"),
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
    pub_portfolio_state_from_redis = False
    pub_positions: list[dict[str, Any]] = []
    try:
        _pub_ps_raw = get_redis().get("v2:portfolio:state")
        if _pub_ps_raw:
            pub_portfolio_state = json.loads(_pub_ps_raw)
            pub_portfolio_state_from_redis = True
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
    runtime_position_missing: list[str] = []
    runtime_position_warnings: list[str] = []
    if not positions and pub_portfolio_state:
        positions, runtime_position_missing, runtime_position_warnings = _runtime_portfolio_positions(
            pub_portfolio_state,
            actor,
        )
    def _first_public_not_none(*values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None

    # Prefer canonical Redis portfolio state for PnL and equity. Use explicit
    # None checks so valid clean-session 0.0 PnL does not fall through to raw
    # heartbeat or legacy payload values.
    base_realized = _first_public_not_none(
        _float(pub_portfolio_state.get("realized_net_pnl_usd")),
        _float(pub_portfolio_state.get("clean_session_valid_realized_pnl_usd")),
        _float(pub_portfolio_state.get("realized_pnl_usd")),
        _float(account.get("realized_pnl") if scoped_paper and isinstance(account, dict) else None),
        _float(portfolio_data.get("realized_pnl_usd") if scoped_portfolio else None),
        _float(redis_hb_public.get("realized_pnl_usd")),
    )
    base_gross_realized = _first_public_not_none(
        _float(pub_portfolio_state.get("realized_gross_pnl_usd")),
        _float(pub_portfolio_state.get("gross_pnl_usd")),
    )
    base_unrealized = _first_public_not_none(
        _float(pub_portfolio_state.get("unrealized_pnl_usd")),
        _float(pub_portfolio_state.get("net_unrealized_pnl")),
        _float(account.get("unrealized_pnl") if scoped_paper and isinstance(account, dict) else None),
        _float(portfolio_data.get("net_unrealized_pnl") if scoped_portfolio else None),
        _float(redis_hb_public.get("unrealized_pnl_usd")),
    )
    _public_initial_capital = (
        _float(pub_portfolio_state.get("starting_equity_usd"))
        or _float(pub_portfolio_state.get("initial_capital"))
        or _float(redis_hb_public.get("starting_equity_usd"))
        or _float(redis_hb_public.get("initial_capital"))
        or PAPER_INITIAL_CAPITAL
    )
    base_total_pnl = _first_public_not_none(
        _float(pub_portfolio_state.get("total_pnl_usd")),
        (base_realized + base_unrealized)
        if base_realized is not None and base_unrealized is not None
        else None,
    )
    _public_session_id = (
        pub_portfolio_state.get("paper_session_id")
        or pub_portfolio_state.get("session_id")
        or redis_hb_public.get("paper_session_id")
        or redis_hb_public.get("session_id")
    )
    base_equity = (
        _float(pub_portfolio_state.get("equity"))
        or _float(account.get("equity") if scoped_paper and isinstance(account, dict) else None)
        or _float(portfolio_data.get("equity") if scoped_portfolio else None)
        or round(_public_initial_capital + (base_realized or 0) + (base_unrealized or 0), 4)
    )
    _ps_open_count = _first_public_not_none(
        _integer(pub_portfolio_state.get("open_positions_count")),
        _integer(pub_portfolio_state.get("open_position_count")),
    )
    _ps_closed_count = _first_public_not_none(
        _integer(pub_portfolio_state.get("closed_trade_count")),
        _integer(pub_portfolio_state.get("closed_positions_count")),
    )
    _clamp = lambda v: round(v, 4) if v is not None and abs(v) >= 0.001 else (0.0 if v is not None else None)
    data = {
        "equity": base_equity,
        "paper_equity": base_equity,
        "paper_balance": base_equity,
        "available_balance": base_equity,
        "available_balance_usd": base_equity,
        "available_balance_scope": "PAPER_SIM_ACCOUNT_NOT_LIVE_SIGNED_ACCOUNT",
        "available_balance_source": "paper_equity_from_v2_portfolio_state_not_live_signed_account",
        "used_balance": _first_public_not_none(
            _float(pub_portfolio_state.get("open_position_notional")),
            _float(redis_hb_public.get("total_open_notional")),
            0.0,
        ),
        "realized_pnl": _clamp(base_realized),
        "realized_pnl_usd": _clamp(base_realized),
        "realized_net_pnl_usd": _clamp(base_realized),
        "realized_gross_pnl_usd": _clamp(base_gross_realized),
        "unrealized_pnl": _clamp(base_unrealized),
        "unrealized_pnl_usd": _clamp(base_unrealized),
        "total_pnl_usd": _clamp(base_total_pnl),
        "paper_initial_capital": _public_initial_capital,
        "initial_capital": _public_initial_capital,
        "starting_equity_usd": _public_initial_capital,
        "paper_session_id": _public_session_id,
        "paper_equity_usd": canonical_pnl_payload.get("paper_equity_usd", base_equity),
        "paper_realized_pnl_usd": canonical_pnl_payload.get("paper_realized_pnl_usd", _clamp(base_realized)),
        "paper_unrealized_pnl_usd": canonical_pnl_payload.get("paper_unrealized_pnl_usd", _clamp(base_unrealized)),
        "paper_total_pnl_usd": canonical_pnl_payload.get("paper_total_pnl_usd", _clamp(base_total_pnl)),
        "open_position_count": _first_public_not_none(
            _ps_open_count,
            _integer(redis_hb_public.get("open_position_count")),
            len(positions),
        ),
        "closed_trade_count": _first_public_not_none(
            _ps_closed_count,
            _integer(redis_hb_public.get("closed_trade_count")),
        ),
        "total_open_notional": _first_public_not_none(
            _float(pub_portfolio_state.get("open_position_notional")),
            _float(redis_hb_public.get("total_open_notional")),
        ),
        "positions": positions,
        "mode": "paper",
        "trader_id": actor.get("trader_id") if actor else None,
        "paper_account_id": actor.get("paper_account_id") if actor else None,
        "account_scope": pub_portfolio_state.get("account_scope") or "PAPER_SIM_ACCOUNT",
        "source_type": pub_portfolio_state.get("source_type") or ("redis_live" if pub_portfolio_state_from_redis else "static_payload"),
        "paper_or_live": "paper",
        "contains_simulated_positions": True,
        "contains_live_positions": False,
        "contains_quarantined_positions": bool(pub_portfolio_state.get("contains_quarantined_positions")),
        "equity_trusted": pub_portfolio_state.get("equity_trusted") is not False,
        "pnl_trusted": pub_portfolio_state.get("pnl_trusted") is not False,
        "pnl_source_key": pub_portfolio_state.get("pnl_source_key", "v2:portfolio:state"),
        "pnl_source_route": pub_portfolio_state.get("pnl_source_route", "/api/v2/portfolio"),
        "pnl_source_type": pub_portfolio_state.get("pnl_source_type", "CANONICAL_CURRENT_SESSION_RUNTIME"),
        "data_source": canonical_pnl_payload.get("data_source") or "redis:v2:portfolio:state",
        "staleness_seconds": canonical_pnl_payload.get("staleness_seconds"),
        "freshness_status": canonical_pnl_payload.get("freshness_status"),
        "pnl_conflict_detected": pub_portfolio_state.get("pnl_conflict_detected", False),
        "pnl_conflict_reason": pub_portfolio_state.get("pnl_conflict_reason"),
        "pnl_conflict_sources": pub_portfolio_state.get("pnl_conflict_sources", []),
        "closed_ledger_net_pnl_usd": pub_portfolio_state.get("closed_ledger_net_pnl_usd"),
        "portfolio_realized_matches_closed_ledger": pub_portfolio_state.get("portfolio_realized_matches_closed_ledger"),
        "equity_reconciles_within_1_cent": pub_portfolio_state.get("equity_reconciles_within_1_cent"),
        "source_generated_utc": pub_portfolio_state.get("generated_utc") or pub_portfolio_state.get("generated_at"),
        "freshness_seconds": pub_portfolio_state.get("freshness_seconds"),
        "reason_if_untrusted": pub_portfolio_state.get("reason_if_untrusted"),
        "invalid_admission_accepted_excluded": pub_portfolio_state.get("invalid_admission_accepted_excluded"),
        "invalid_admission_closed_trades_excluded": pub_portfolio_state.get("invalid_admission_closed_trades_excluded"),
        "raw_equity_including_invalid_admissions_usd": pub_portfolio_state.get("raw_equity_including_invalid_admissions_usd"),
        "clean_session_valid_equity_usd": pub_portfolio_state.get("clean_session_valid_equity_usd"),
        "account_specific": bool(scoped_paper or scoped_portfolio),
        "portfolio_source": "redis:v2:portfolio:state" if pub_portfolio_state_from_redis else portfolio_source,
        "portfolio_source_type": "redis_live" if pub_portfolio_state_from_redis else "static_payload",
        "fallback_used": not pub_portfolio_state_from_redis,
        "fallback_source_visible": True,
    }
    missing = [key for key in ("equity", "realized_pnl", "unrealized_pnl") if data.get(key) is None]
    if not positions:
        missing.append("positions")
    if not data["account_specific"]:
        missing.append("trader_specific_repository")
    missing.extend(runtime_position_missing)
    warnings = [
        (
            "Canonical paper portfolio source is Redis v2:portfolio:state"
            if pub_portfolio_state_from_redis
            else "Paper/static payload fallback; not a brokerage account API"
        ),
        *runtime_position_warnings,
    ]
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
    # Source metadata: prefer Redis when available, fall back to static file timestamps.
    if pub_portfolio_state_from_redis:
        _pub_source = "redis:v2:portfolio:state"
        _pub_source_type: SourceType = "redis_live"
        _pub_timestamp = pub_portfolio_state.get("generated_utc") or _utc_now()
    else:
        _pub_source = f"{paper_source} + {portfolio_source}"
        _pub_source_type = "static_payload"
        _pub_timestamp = _timestamp_from_payload(paper) or _timestamp_from_payload(portfolio)
    return _base_response(
        endpoint=endpoint,
        data=data,
        source=_pub_source,
        source_type=_pub_source_type,
        timestamp=_pub_timestamp,
        missing_fields=[*dict.fromkeys(missing)],
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


@router.get("/account/summary")
async def get_account_summary(actor: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    endpoint = "/api/v2/account/summary"
    portfolio_response = await get_portfolio(actor)
    portfolio_data = portfolio_response.get("data") if isinstance(portfolio_response.get("data"), dict) else {}
    data = {
        "account_scope": portfolio_data.get("account_scope") or "PAPER_SIM_ACCOUNT",
        "source_type": portfolio_data.get("source_type") or portfolio_response.get("source_type") or "paper_sim_portfolio",
        "paper_or_live": "paper",
        "contains_simulated_positions": True,
        "contains_live_positions": False,
        "contains_quarantined_positions": bool(portfolio_data.get("contains_quarantined_positions")),
        "equity_trusted": portfolio_data.get("equity_trusted") is not False,
        "pnl_trusted": portfolio_data.get("pnl_trusted") is not False,
        "reason_if_untrusted": portfolio_data.get("reason_if_untrusted"),
        "equity": portfolio_data.get("equity"),
        "paper_equity": portfolio_data.get("paper_equity"),
        "paper_equity_usd": portfolio_data.get("paper_equity_usd"),
        "paper_session_id": portfolio_data.get("paper_session_id"),
        "initial_capital": portfolio_data.get("initial_capital")
        or portfolio_data.get("paper_initial_capital"),
        "starting_equity_usd": portfolio_data.get("starting_equity_usd")
        or portfolio_data.get("paper_initial_capital"),
        "paper_initial_capital": portfolio_data.get("paper_initial_capital"),
        "available_balance": portfolio_data.get("available_balance"),
        "available_balance_usd": portfolio_data.get("available_balance_usd"),
        "available_balance_scope": portfolio_data.get("available_balance_scope")
        or "PAPER_SIM_ACCOUNT_NOT_LIVE_SIGNED_ACCOUNT",
        "available_balance_source": portfolio_data.get("available_balance_source")
        or "paper_equity_from_v2_portfolio_state_not_live_signed_account",
        "realized_pnl": portfolio_data.get("realized_pnl"),
        "paper_realized_pnl_usd": portfolio_data.get("paper_realized_pnl_usd"),
        "unrealized_pnl": portfolio_data.get("unrealized_pnl"),
        "paper_unrealized_pnl_usd": portfolio_data.get("paper_unrealized_pnl_usd"),
        "paper_total_pnl_usd": portfolio_data.get("paper_total_pnl_usd"),
        "data_source": portfolio_data.get("data_source"),
        "staleness_seconds": portfolio_data.get("staleness_seconds"),
        "freshness_status": portfolio_data.get("freshness_status"),
        "open_position_count": portfolio_data.get("open_position_count"),
        "closed_trade_count": portfolio_data.get("closed_trade_count"),
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
    }
    return _base_response(
        endpoint=endpoint,
        data=data,
        source=str(portfolio_response.get("source") or "/api/v2/portfolio"),
        source_type=portfolio_response.get("source_type") or "paper_sim_portfolio",
        timestamp=portfolio_response.get("timestamp") or _utc_now(),
        missing_fields=list(portfolio_response.get("missing_fields") or []),
        warnings=[
            "Account summary is paper simulation scope, not a live signed exchange account",
            "Live trading remains disabled",
            *list(portfolio_response.get("warnings") or []),
        ],
        mode="paper",
        trader_context=_trader_context(actor),
    )


@router.get("/live/readiness")
async def get_live_readiness_summary(actor: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    endpoint = "/api/v2/live/readiness"
    redis_client = get_redis()
    try:
        from app.services.live_readiness import derive_gates  # noqa: PLC0415

        gates = derive_gates(redis_client)
    except Exception as exc:
        gates = []
        warning = f"Live readiness gate derivation unavailable: {exc}"
    else:
        warning = "Live readiness gates are read-only and live remains blocked"
    try:
        from app.api.v2.control_center_status import (  # noqa: PLC0415
            _current_a_grade_blocker_truth,
        )

        a_grade_blocker_truth = _current_a_grade_blocker_truth(redis_client)
    except Exception:
        a_grade_blocker_truth = {
            "schema_version": "control_center_a_grade_blocker_truth_v1",
            "status": "A_GRADE_BLOCKER_TRUTH_UNAVAILABLE",
            "available": False,
            "primary_blocker": "A_GRADE_BLOCKER_TRUTH_UNAVAILABLE",
            "finding_ids": [],
            "live_gate": "blocked_human_only",
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "order_submitted": False,
            "test_order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
        }
    a_grade_truth_status = str(a_grade_blocker_truth.get("status") or "")
    current_a_grade_blocker = (
        a_grade_blocker_truth.get("primary_blocker")
        if a_grade_truth_status == "A_GRADE_ADAPTATION_NOT_PROVEN"
        else None
    )
    if not current_a_grade_blocker and a_grade_truth_status != "NO_ACTIVE_BLOCKER_DETECTED":
        current_a_grade_blocker = a_grade_truth_status or "A_GRADE_BLOCKER_TRUTH_UNAVAILABLE"
    blocking_gates = [gate for gate in gates if gate.get("state") != "passed"]
    blocker_ids = [
        str(value)
        for value in [
            current_a_grade_blocker,
            *(
                a_grade_blocker_truth.get("finding_ids")
                if isinstance(a_grade_blocker_truth.get("finding_ids"), list)
                else []
            ),
            *[
                gate.get("id") or gate.get("source_route_or_key")
                for gate in blocking_gates
            ],
        ]
        if value
    ]
    readiness_blockers = list(dict.fromkeys(blocker_ids))
    data = {
        "account_scope": "LIVE_BINANCE_SIGNED_ACCOUNT",
        "source_type": "live_readiness_read_only_gate",
        "paper_or_live": "live",
        "contains_simulated_positions": False,
        "contains_live_positions": False,
        "contains_quarantined_positions": False,
        "equity_trusted": False,
        "pnl_trusted": False,
        "reason_if_untrusted": "LIVE_SIGNED_ACCOUNT_EQUITY_NOT_MIXED_WITH_PAPER_POSITIONS",
        "live_gate": "blocked_human_only",
        "live_ready": False if current_a_grade_blocker else not blocking_gates,
        "live_submit_allowed": False,
        "exact_no_live_reason": current_a_grade_blocker
        or (str(blocking_gates[0].get("id")) if blocking_gates else None),
        "readiness_blockers": readiness_blockers,
        "a_grade_blocker_truth": a_grade_blocker_truth,
        "places_real_order": False,
        "routes_to_live": False,
        "gates": gates,
    }
    return _base_response(
        endpoint=endpoint,
        data=data,
        source="app.services.live_readiness.derive_gates",
        source_type="computed",
        timestamp=_utc_now(),
        missing_fields=[] if gates else ["live_readiness_gates"],
        warnings=[
            warning,
            "No exchange state was mutated",
            "Paper portfolio positions are not mixed into live account truth",
        ],
        mode="read_only",
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


@router.get("/signals/current")
async def get_current_signal(
    symbol: str | None = Query(default=None),
    timeframe: str = Query(default="5m"),
    actor: UserRecord | None = Depends(optional_auth),
) -> dict[str, Any]:
    payload = await get_signals(symbol=symbol, timeframe=timeframe, actor=actor)
    endpoint_params: dict[str, str] = {}
    requested_symbol = _strict_market_symbol(symbol) if symbol else None
    safe_timeframe = _strict_timeframe(timeframe) or "5m"
    if requested_symbol:
        endpoint_params["symbol"] = requested_symbol
    if safe_timeframe != "5m":
        endpoint_params["timeframe"] = safe_timeframe
    endpoint = "/api/v2/signals/current" + (
        f"?{urllib.parse.urlencode(endpoint_params)}" if endpoint_params else ""
    )
    if isinstance(payload, dict):
        payload = dict(payload)
        payload["endpoint"] = endpoint
        payload["canonical_owner"] = "/api/v2/signals/current"
    return payload


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
        "confidence_directional_long": _float(payload.get("confidence_directional_long")),
        "confidence_directional_short": _float(payload.get("confidence_directional_short")),
        "confidence_hold": _float(payload.get("confidence_hold")),
        "confidence_selected_action": _float(payload.get("confidence_selected_action")),
        "confidence_post_cost_long": _float(payload.get("confidence_post_cost_long")),
        "confidence_post_cost_short": _float(payload.get("confidence_post_cost_short")),
        "confidence_executable_trade": _float(payload.get("confidence_executable_trade")),
        "confidence_display_label": payload.get("confidence_display_label"),
        "confidence_type": payload.get("confidence_type"),
        "confidence_a_plus_eligible": payload.get("confidence_a_plus_eligible") is True,
        "confidence_tradeability_block_reasons": _as_list(payload.get("confidence_tradeability_block_reasons")),
        "paper_exploration_tier": payload.get("paper_exploration_tier") or payload.get("exploration_tier"),
        "exploration_tier": payload.get("exploration_tier") or payload.get("paper_exploration_tier"),
        "expected_net_pnl_usd": _float(payload.get("expected_net_pnl_usd")),
        "expected_max_loss_usd": _float(payload.get("expected_max_loss_usd") or payload.get("max_loss_usd")),
        "why_not_a_plus": _as_list(payload.get("block_reasons")),
        "why_not_live_ready": _as_list(payload.get("live_ready_block_reasons") or payload.get("block_reasons")),
        "risk_controller_decision": payload.get("risk_decision") or payload.get("risk_state"),
        "allocator_decision": payload.get("allocator_decision"),
        "trainer_feedback_status": payload.get("trainer_feedback_status"),
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
        "confidence_directional_long": _float(payload.get("confidence_directional_long")),
        "confidence_directional_short": _float(payload.get("confidence_directional_short")),
        "confidence_hold": _float(payload.get("confidence_hold")),
        "confidence_selected_action": _float(payload.get("confidence_selected_action")),
        "confidence_post_cost_long": _float(payload.get("confidence_post_cost_long")),
        "confidence_post_cost_short": _float(payload.get("confidence_post_cost_short")),
        "confidence_executable_trade": _float(payload.get("confidence_executable_trade")),
        "confidence_display_label": payload.get("confidence_display_label"),
        "confidence_type": payload.get("confidence_type"),
        "confidence_a_plus_eligible": payload.get("confidence_a_plus_eligible") is True,
        "confidence_tradeability_block_reasons": _as_list(payload.get("confidence_tradeability_block_reasons")),
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
            "confidence_directional_long": _float(raw.get("confidence_directional_long")),
            "confidence_directional_short": _float(raw.get("confidence_directional_short")),
            "confidence_hold": _float(raw.get("confidence_hold")),
            "confidence_selected_action": _float(raw.get("confidence_selected_action")),
            "confidence_post_cost_long": _float(raw.get("confidence_post_cost_long")),
            "confidence_post_cost_short": _float(raw.get("confidence_post_cost_short")),
            "confidence_executable_trade": _float(raw.get("confidence_executable_trade")),
            "confidence_display_label": raw.get("confidence_display_label") if isinstance(raw.get("confidence_display_label"), str) else None,
            "confidence_type": raw.get("confidence_type") if isinstance(raw.get("confidence_type"), str) else None,
            "confidence_a_plus_eligible": raw.get("confidence_a_plus_eligible") is True,
            "confidence_tradeability_block_reasons": _as_list(raw.get("confidence_tradeability_block_reasons")),
            "paper_exploration_tier": raw.get("paper_exploration_tier") or raw.get("exploration_tier"),
            "exploration_tier": raw.get("exploration_tier") or raw.get("paper_exploration_tier"),
            "expected_net_pnl_usd": _float(raw.get("expected_net_pnl_usd")),
            "expected_max_loss_usd": _float(raw.get("expected_max_loss_usd") or raw.get("max_loss_usd")),
            "why_not_a_plus": _as_list(raw.get("block_reasons")),
            "why_not_live_ready": _as_list(raw.get("live_ready_block_reasons") or raw.get("block_reasons")),
            "risk_controller_decision": raw.get("risk_decision") or raw.get("risk_state"),
            "allocator_decision": raw.get("allocator_decision"),
            "trainer_feedback_status": raw.get("trainer_feedback_status"),
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
    confidence_selected_action = _float(
        p.get("confidence_selected_action") or s.get("confidence_selected_action")
    )
    confidence_executable_trade = _float(
        p.get("confidence_executable_trade") or s.get("confidence_executable_trade")
    )
    confidence_display_label = str(
        p.get("confidence_display_label")
        or s.get("confidence_display_label")
        or "Unproven confidence"
    )
    confidence_tradeability_block_reasons = _as_list(
        p.get("confidence_tradeability_block_reasons")
        or s.get("confidence_tradeability_block_reasons")
    )
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
    executable_pct = (
        f"{confidence_executable_trade * 100:.1f}%"
        if confidence_executable_trade is not None
        else "N/A"
    )
    summary = (
        f"The model selected {selected_action} with {dom_pct} selected-action confidence{secondary_clause}. "
        f"Executable post-cost confidence is {executable_pct} ({confidence_display_label})."
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
    if confidence_tradeability_block_reasons:
        confidence_narrative += (
            " Tradeability blockers: "
            + ", ".join(str(reason) for reason in confidence_tradeability_block_reasons[:6])
            + "."
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
        if any("coinglass" in n.lower() for n in alt_names):
            providers.append("CoinGlass")
        if any("moralis" in n.lower() for n in alt_names):
            providers.append("Moralis")
        if any(("santiment" in n.lower()) or ("sanbase" in n.lower()) for n in alt_names):
            providers.append("Santiment/Sanbase")
        if any("nansen" in n.lower() for n in alt_names):
            providers.append("legacy Nansen inactive")
        if any("lunarcrush" in n.lower() for n in alt_names):
            providers.append("legacy LunarCrush inactive")
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
        "confidence_selected_action": confidence_selected_action,
        "confidence_executable_trade": confidence_executable_trade,
        "confidence_display_label": confidence_display_label,
        "confidence_tradeability_block_reasons": confidence_tradeability_block_reasons,
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

    # --- Structured missing-feature alert (renderable by web + iOS AI pages) ---
    # The prediction is ALWAYS produced (features that are absent are masked, not
    # zero-filled), so the system stays operational end-to-end. This block tells
    # the UI exactly what is degraded and how severe, without blocking anything.
    missing_by_category = {
        "liquidation": liq_count,
        "alternative_data": alt_count,
        "paper_state": paper_count,
        "htf": htf_count,
        "orchestrator_feedback": orc_count,
        "other": other_count,
    }
    if data_coverage is None:
        _alert_severity = "unknown"
    elif data_coverage >= 95.0 and missing_feature_count == 0:
        _alert_severity = "none"
    elif data_coverage >= 80.0:
        _alert_severity = "info"
    elif data_coverage >= 60.0:
        _alert_severity = "warn"
    else:
        _alert_severity = "critical"
    missing_feature_alert = {
        "active": _alert_severity not in ("none", "unknown"),
        "severity": _alert_severity,
        "operational": True,
        "prediction_still_produced": True,
        "data_coverage_pct": data_coverage,
        "missing_feature_count": missing_feature_count,
        "stale_feature_count": stale_feature_count,
        "missing_by_category": {k: v for k, v in missing_by_category.items() if v},
        "missing_provider_names": sorted(
            {
                name
                for names in (feature_groups.get("alternative_data") or [],)
                for name in names
            }
        ),
        "message": dq_narrative,
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
        "missing_feature_alert": missing_feature_alert,
    }


def _build_signal_explanation(sig_payload: dict[str, Any] | None) -> dict[str, Any]:
    """Shorter explanation focused on the trading signal outcome."""
    s = sig_payload or {}
    action = str(s.get("action") or "UNKNOWN").strip().upper()
    confidence = _float(s.get("confidence"))
    confidence_executable_trade = _float(s.get("confidence_executable_trade"))
    confidence_display_label = str(s.get("confidence_display_label") or "Unproven confidence")
    confidence_tradeability_block_reasons = _as_list(s.get("confidence_tradeability_block_reasons"))
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
    exec_conf_str = (
        f"{confidence_executable_trade * 100:.1f}%"
        if confidence_executable_trade is not None
        else "N/A"
    )
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
        f"Signal: {action}. Selected-action confidence: {conf_str}. "
        f"Executable post-cost confidence: {exec_conf_str} ({confidence_display_label}). "
        f"Expected move after cost: {move_str}. After-cost price target: {pt_str}. "
        f"Market integrity: {int_str}. Data coverage: {cov_str}. "
        f"{gate_note} {paper_note} {risk_note} {orch_note} "
        f"Paper state: {paper_state.replace('_', ' ').title()}."
    )
    if confidence_tradeability_block_reasons:
        summary += " Confidence blockers: " + ", ".join(
            str(reason) for reason in confidence_tradeability_block_reasons[:6]
        ) + "."
    return {
        "summary": summary,
        "action": action,
        "confidence": confidence,
        "confidence_executable_trade": confidence_executable_trade,
        "confidence_display_label": confidence_display_label,
        "confidence_tradeability_block_reasons": confidence_tradeability_block_reasons,
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


PREEMPTIVE_MATRIX_API_ROW_LIMIT = 5
PREEMPTIVE_MATRIX_API_LIST_PREVIEW_LIMIT = 8
PREEMPTIVE_MATRIX_API_ROW_FIELDS = (
    "preemptive_decision_id",
    "preemptive_decision",
    "preemptive_action",
    "preemptive_allowed",
    "preemptive_shadow_only",
    "preemptive_reduce_size_required",
    "symbol",
    "side",
    "timeframe",
    "strategy_id",
    "source_tier",
    "pre_trade_expected_net_pnl_usd",
    "pre_trade_expected_gross_pnl_usd",
    "pre_trade_expected_cost_usd",
    "pre_trade_max_loss_usd",
    "pre_trade_loss_probability",
    "pre_trade_profit_probability",
    "confidence_overstatement_risk",
    "regime_compatibility_score",
    "exit_feasibility_score",
    "bucket_profit_factor",
    "guardian_new_entries_allowed",
    "continuous_edge_guardian_status",
    "reduce_size_guardian_approved",
    "reduce_size_guardian_approval_reason",
    "advanced_indicator_status",
    "advanced_indicator_confluence_score",
    "fvg_present",
    "fvg_side_aligned",
    "liquidity_sweep_state",
    "microstructure_trust_state",
    "microstructure_trust_score",
    "altdata_confluence_present",
    "altdata_trade_block_score",
    "altdata_reduce_size_score",
    "altdata_hedge_required_score",
    "altdata_wallet_distribution_score",
    "altdata_liquidation_sweep_risk_score",
    "altdata_social_euphoria_risk_score",
    "preemptive_decision_time",
    "preemptive_decision_time_et",
    "paper_session_id",
    "routes_to_live",
    "places_real_order",
)


def _compact_preemptive_matrix_row(row: dict[str, Any]) -> dict[str, Any]:
    compact = {key: row.get(key) for key in PREEMPTIVE_MATRIX_API_ROW_FIELDS if key in row}
    for key in (
        "preemptive_block_reasons",
        "preemptive_decision_reasons",
        "advanced_indicator_block_reasons",
        "advanced_indicator_caution_reasons",
        "provider_features_used",
        "provider_features_missing",
        "candidate_bucket_keys",
        "matched_quarantined_bucket_keys",
    ):
        value = row.get(key)
        if not isinstance(value, list):
            continue
        compact[f"{key}_count"] = len(value)
        compact[key] = value[:PREEMPTIVE_MATRIX_API_LIST_PREVIEW_LIMIT]
        if len(value) > PREEMPTIVE_MATRIX_API_LIST_PREVIEW_LIMIT:
            compact[f"{key}_omitted_count"] = len(value) - PREEMPTIVE_MATRIX_API_LIST_PREVIEW_LIMIT
    return compact


def _compact_preemptive_candidate_decision_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    rows = matrix.get("rows") or matrix.get("sample_decisions") or []
    rows = rows if isinstance(rows, list) else []
    compact = {
        key: value
        for key, value in matrix.items()
        if key not in {"rows", "sample_decisions"}
    }
    preview_rows = [
        _compact_preemptive_matrix_row(row)
        for row in rows[:PREEMPTIVE_MATRIX_API_ROW_LIMIT]
        if isinstance(row, dict)
    ]
    compact["rows"] = preview_rows
    compact["sample_decisions"] = preview_rows
    compact["full_row_count"] = len(rows)
    compact["preview_row_count"] = len(preview_rows)
    compact["payload_compacted"] = len(rows) > PREEMPTIVE_MATRIX_API_ROW_LIMIT
    compact["omitted_row_count"] = max(0, len(rows) - PREEMPTIVE_MATRIX_API_ROW_LIMIT)
    compact["debug_detail_source"] = "redis:v2:paper:preemptive_candidate_decision_matrix"
    compact.setdefault("paper_only", True)
    compact.setdefault("routes_to_live", False)
    compact.setdefault("places_real_order", False)
    return compact


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

    readiness_context = _paper_a_grade_readiness_context(get_redis())
    data = {
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
        "real_trader_readiness": readiness_context,
        "a_grade_blocker_truth": readiness_context["a_grade_blocker_truth"],
        "exact_no_live_reason": readiness_context["exact_no_live_reason"],
        "readiness_blockers": readiness_context["readiness_blockers"],
        "top_blockers": readiness_context["readiness_blockers"][:8],
    }
    response = _base_response(
        endpoint=endpoint,
        data=data,
        source="redis:v2:orchestrator",
        source_type="static_payload" if not missing else "unavailable",
        timestamp=timestamp,
        missing_fields=missing,
        warnings=["Live trading is BLOCKED -- orchestrator status is read-only"],
        mode="paper",
    )
    response["real_trader_readiness"] = readiness_context
    response["a_grade_blocker_truth"] = readiness_context["a_grade_blocker_truth"]
    response["exact_no_live_reason"] = readiness_context["exact_no_live_reason"]
    response["readiness_blockers"] = readiness_context["readiness_blockers"]
    response["top_blockers"] = readiness_context["readiness_blockers"][:8]
    return response


@router.get("/orchestrator")
async def get_orchestrator_contract() -> dict[str, Any]:
    """Compatibility alias for `/api/v2/orchestrator`."""
    response = dict(await get_orchestrator_status())
    response["endpoint"] = "/api/v2/orchestrator"
    return response


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
    governor_raw = _read_v2_redis_json_or_list("v2:paper:performance_governor_status")
    governor: dict[str, Any] = governor_raw if isinstance(governor_raw, dict) else {}
    circuit_raw = _read_v2_redis_json_or_list("v2:paper:performance_circuit_breaker_status")
    circuit: dict[str, Any] = circuit_raw if isinstance(circuit_raw, dict) else {}
    preemptive_edge_control_raw = _read_v2_redis_json_or_list(
        "v2:paper:preemptive_edge_control_status"
    )
    preemptive_edge_control_status: dict[str, Any] = (
        preemptive_edge_control_raw
        if isinstance(preemptive_edge_control_raw, dict)
        else {
            "schema_version": "preemptive_edge_control_status_v1",
            "status": "PREEMPTIVE_EDGE_CONTROL_STATUS_UNAVAILABLE",
            "candidate_count": 0,
            "accepted_count": 0,
            "hard_fail": True,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    )
    preemptive_matrix_raw = _read_v2_redis_json_or_list(
        "v2:paper:preemptive_candidate_decision_matrix"
    )
    preemptive_candidate_decision_matrix: dict[str, Any] = (
        preemptive_matrix_raw
        if isinstance(preemptive_matrix_raw, dict)
        else {
            "schema_version": "preemptive_candidate_decision_matrix_v1",
            "status": "PREEMPTIVE_CANDIDATE_DECISION_MATRIX_UNAVAILABLE",
            "candidate_count": 0,
            "sample_decisions": [],
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    )
    preemptive_rows = (
        preemptive_candidate_decision_matrix.get("rows")
        or preemptive_candidate_decision_matrix.get("sample_decisions")
        or []
    )
    preemptive_rows = preemptive_rows if isinstance(preemptive_rows, list) else []
    preemptive_candidate_decision_matrix_api = _compact_preemptive_candidate_decision_matrix(
        preemptive_candidate_decision_matrix
    )
    first_preemptive_sample = (
        preemptive_rows[0]
        if preemptive_rows and isinstance(preemptive_rows[0], dict)
        else {}
    )
    paper_preemptive_admission_raw = _read_v2_redis_json_or_list(
        "v2:paper:preemptive_admission_status"
    )
    paper_preemptive_admission_status: dict[str, Any] = (
        paper_preemptive_admission_raw
        if isinstance(paper_preemptive_admission_raw, dict)
        else {
            "schema_version": "paper_preemptive_admission_status_v1",
            "status": "PAPER_PREEMPTIVE_ADMISSION_STATUS_UNAVAILABLE",
            "hard_fail": True,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    )
    positive_edge_probation_policy_raw = _read_v2_redis_json_or_list(
        "v2:paper:positive_edge_probation_policy"
    )
    positive_edge_probation_policy: dict[str, Any] = (
        positive_edge_probation_policy_raw
        if isinstance(positive_edge_probation_policy_raw, dict)
        else {
            "schema_version": "positive_edge_probation_policy_v1",
            "status": "POSITIVE_EDGE_PROBATION_POLICY_UNAVAILABLE",
            "enabled": False,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    )
    positive_edge_probation_runtime_raw = _read_v2_redis_json_or_list(
        "v2:paper:positive_edge_probation_runtime_status"
    )
    positive_edge_probation_runtime_status: dict[str, Any] = (
        positive_edge_probation_runtime_raw
        if isinstance(positive_edge_probation_runtime_raw, dict)
        else {
            "schema_version": "positive_edge_probation_runtime_status_v1",
            "status": "POSITIVE_EDGE_PROBATION_RUNTIME_STATUS_UNAVAILABLE",
            "current_candidate_count": 0,
            "current_accepted_count": 0,
            "closed_probation_trade_count": 0,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_final_a_plus": False,
            "counts_as_live_ready": False,
        }
    )
    probation_5_trade_gate = (
        _read_v2_redis_json_or_list("v2:paper:probation_5_trade_gate") or {}
    )
    probation_20_trade_gate = (
        _read_v2_redis_json_or_list("v2:paper:probation_20_trade_gate") or {}
    )
    probation_50_trade_gate = (
        _read_v2_redis_json_or_list("v2:paper:probation_50_trade_gate") or {}
    )
    if not isinstance(probation_5_trade_gate, dict):
        probation_5_trade_gate = {}
    if not isinstance(probation_20_trade_gate, dict):
        probation_20_trade_gate = {}
    if not isinstance(probation_50_trade_gate, dict):
        probation_50_trade_gate = {}
    probation_5_display_status = probation_gate_display_status(probation_5_trade_gate)
    positive_edge_probation_summary = {
        "status": positive_edge_probation_runtime_status.get("status"),
        "policy_enabled": positive_edge_probation_policy.get("enabled") is True,
        "current_candidate_count": positive_edge_probation_runtime_status.get(
            "current_candidate_count"
        ),
        "current_accepted_count": positive_edge_probation_runtime_status.get(
            "current_accepted_count"
        ),
        "closed_probation_trade_count": positive_edge_probation_runtime_status.get(
            "closed_probation_trade_count"
        ),
        "next_gate": positive_edge_probation_runtime_status.get("next_gate"),
        "probation_5_trade_gate_status": probation_5_display_status,
        "probation_20_trade_gate_status": probation_20_trade_gate.get("status"),
        "probation_50_trade_gate_status": probation_50_trade_gate.get("status"),
        "counts_as_final_a_plus": False,
        "counts_as_live_ready": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "supply_state": (
            "NO_SAFE_TRADE_SUPPLY"
            if int(positive_edge_probation_runtime_status.get("current_candidate_count") or 0)
            <= 0
            else "POSITIVE_EDGE_PROBATION_SUPPLY_AVAILABLE"
        ),
    }
    advanced_indicator_summary = _advanced_indicator_runtime_summary(
        preemptive_matrix=preemptive_candidate_decision_matrix,
        preemptive_status=preemptive_edge_control_status,
        admission_status=paper_preemptive_admission_status,
    )
    adaptive_hedge_cross_margin = _adaptive_hedge_cross_margin_summary()
    provider_readiness = _provider_readiness_summary()
    halt_reasons = [
        str(reason)
        for reason in (
            governor.get("halt_reasons")
            or governor.get("state_reasons")
            or []
        )
        if reason
    ]
    state_reasons = [
        str(reason)
        for reason in (
            governor.get("state_reasons")
            or governor.get("halt_reasons")
            or []
        )
        if reason
    ]
    top_blockers = halt_reasons[:8]
    try:
        risk_readiness_context = _paper_a_grade_readiness_context(get_redis())
    except Exception:
        risk_readiness_context = _paper_a_grade_readiness_context(None)
    top_blockers = list(dict.fromkeys([
        *risk_readiness_context["readiness_blockers"],
        *top_blockers,
    ]))[:8]
    cluster_raw = circuit.get("recovery_high_confidence_loss_cluster_status")
    bucket_raw = circuit.get("bucket_quarantine_status")
    bucket_raw = bucket_raw if isinstance(bucket_raw, dict) else {}
    cluster_status: dict[str, Any] | None = None
    if isinstance(cluster_raw, dict):
        derived_cluster = _high_confidence_cluster_derived_dimensions(cluster_raw)
        cluster_detected = cluster_raw.get("cluster_detected") is True
        guardian_state = (
            governor.get("state")
            or governor.get("status")
            or circuit.get("state")
            or circuit.get("status")
        )
        guardian_new_entries_allowed = (
            governor.get("new_entries_allowed")
            if governor.get("new_entries_allowed") is not None
            else circuit.get("new_entries_allowed")
        )
        reduce_size_allowed = (
            circuit.get("new_entries_allowed") is True
            and guardian_new_entries_allowed is True
            and not cluster_detected
            and not bool(bucket_raw.get("blocked_bucket_keys"))
        )
        cluster_status = {
            "status": cluster_raw.get("status"),
            "active": cluster_detected,
            "cluster_detected": cluster_raw.get("cluster_detected"),
            "high_confidence_min_score": cluster_raw.get("high_confidence_min_score"),
            "high_confidence_loss_count": cluster_raw.get("high_confidence_loss_count"),
            "cluster_count": cluster_raw.get("high_confidence_loss_count"),
            "cluster_min_loss_count": cluster_raw.get("cluster_min_loss_count"),
            "affected_symbols": derived_cluster["affected_symbols"],
            "affected_dimension_counts": derived_cluster["affected_dimension_counts"],
            "affected_buckets": {
                "sides": derived_cluster["quarantined_sides"],
                "timeframes": derived_cluster["quarantined_timeframes"],
                "strategy_modes": derived_cluster["quarantined_strategy_modes"],
                "blocked_bucket_keys": (bucket_raw.get("blocked_bucket_keys") or [])[:20],
            },
            "guardian_state": guardian_state,
            "guardian_new_entries_allowed": guardian_new_entries_allowed,
            "REDUCE_SIZE_allowed": reduce_size_allowed,
            "reduce_size_bootstrap_allowed": reduce_size_allowed,
            "reduce_size_policy": "REDUCE_SIZE_BOOTSTRAP_PAPER_ONLY_NOT_FINAL_A_PLUS",
            "why_reduce_size_blocked": (
                "HIGH_CONFIDENCE_LOSS_CLUSTER_ACTIVE"
                if cluster_detected
                else "BUCKET_QUARANTINE_ACTIVE"
                if bucket_raw.get("blocked_bucket_keys")
                else "GUARDIAN_OR_GLOBAL_ENTRY_GATE_BLOCKED"
                if not reduce_size_allowed
                else None
            ),
            "post_patch_recovery_status": (
                "BLOCKED_CURRENT_CLUSTER_NO_POST_PATCH_RECOVERY_PROOF"
                if cluster_detected
                else "NO_ACTIVE_HIGH_CONFIDENCE_CLUSTER"
            ),
            "paper_only": cluster_raw.get("paper_only"),
            "routes_to_live": cluster_raw.get("routes_to_live"),
            "places_real_order": cluster_raw.get("places_real_order"),
            "sample_high_confidence_losses": [
                {
                    "symbol": row.get("symbol"),
                    "side": row.get("side"),
                    "timeframe": row.get("timeframe"),
                    "strategy_id": row.get("strategy_id"),
                    "confidence_calibrated": row.get("confidence_calibrated"),
                    "realized_pnl_bps": row.get("realized_pnl_bps"),
                    "exit_reason": row.get("exit_reason"),
                }
                for row in (
                    cluster_raw.get("sample_high_confidence_losses")
                    if isinstance(cluster_raw.get("sample_high_confidence_losses"), list)
                    else []
                )[:5]
                if isinstance(row, dict)
            ],
        }

    missing: list[str] = []
    # An empty latest-decision payload with a live heartbeat means the gateway
    # is alive but has produced no recent winners — not an offline gateway.
    if not gateway_latest and heartbeat is None:
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
    _governor_state = (
        governor.get("state")
        or governor.get("status")
        or governor.get("governor_state")
    )
    _risk_status = (
        str(_governor_state)
        if _governor_state
        else str(heartbeat.get("classification")) if heartbeat and heartbeat.get("classification") else None
    )
    if not _risk_status:
        _risk_status = "FAIL_CLOSED_NO_RECENT_RISK_RECORDS" if missing else "FAIL_CLOSED_READ_ONLY"

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
            "status": _risk_status,
            "risk_status": _risk_status,
            "classification": _risk_status,
            "fail_closed_reason": _governor_state or ("missing:" + ",".join(missing) if missing else "read_only_live_gate_blocked"),
            "new_entries_allowed": governor.get("new_entries_allowed"),
            "halt_reasons": halt_reasons,
            "state_reasons": state_reasons,
            "top_blockers": top_blockers,
            "real_trader_readiness": risk_readiness_context,
            "a_grade_blocker_truth": risk_readiness_context["a_grade_blocker_truth"],
            "exact_no_live_reason": risk_readiness_context["exact_no_live_reason"],
            "readiness_blockers": risk_readiness_context["readiness_blockers"],
            "recovery_high_confidence_loss_cluster_status": cluster_status,
            "preemptive_edge_control_status": preemptive_edge_control_status,
            "preemptive_candidate_decision_matrix": preemptive_candidate_decision_matrix_api,
            "paper_preemptive_admission_status": paper_preemptive_admission_status,
            "positive_edge_probation": positive_edge_probation_summary,
            "advanced_indicators": advanced_indicator_summary,
            "adaptive_hedge_cross_margin": adaptive_hedge_cross_margin,
            "provider_readiness": provider_readiness,
            "positive_edge_probation_policy": positive_edge_probation_policy,
            "positive_edge_probation_runtime_status": (
                positive_edge_probation_runtime_status
            ),
            "probation_5_trade_gate": probation_5_trade_gate,
            "probation_20_trade_gate": probation_20_trade_gate,
            "probation_50_trade_gate": probation_50_trade_gate,
            "preemptive_prevention": {
                "status": (
                    "PREEMPTIVE_EDGE_CONTROL_ACTIVE"
                    if preemptive_edge_control_status.get("candidate_count")
                    is not None
                    and preemptive_edge_control_status.get("status")
                    != "PREEMPTIVE_EDGE_CONTROL_STATUS_UNAVAILABLE"
                    else "PREEMPTIVE_EDGE_CONTROL_NOT_YET_PUBLISHED"
                ),
                "candidate_count": preemptive_edge_control_status.get("candidate_count"),
                "decision_counts": preemptive_edge_control_status.get("decision_counts") or {},
                "action_counts": preemptive_edge_control_status.get("action_counts") or {},
                "preemptive_decision_id": first_preemptive_sample.get(
                    "preemptive_decision_id"
                ),
                "preemptive_action": first_preemptive_sample.get("preemptive_action"),
                "preemptive_allowed": first_preemptive_sample.get("preemptive_allowed") is True,
                "preemptive_block_reasons": (
                    first_preemptive_sample.get("preemptive_block_reasons")
                    or first_preemptive_sample.get("preemptive_decision_reasons")
                    or []
                ),
                "pre_trade_expected_net_pnl_usd": first_preemptive_sample.get(
                    "pre_trade_expected_net_pnl_usd"
                ),
                "pre_trade_loss_probability": first_preemptive_sample.get(
                    "pre_trade_loss_probability"
                ),
                "guardian_new_entries_allowed": (
                    first_preemptive_sample.get("guardian_new_entries_allowed") is True
                ),
                "continuous_edge_guardian_status": first_preemptive_sample.get(
                    "continuous_edge_guardian_status"
                ),
                "reduce_size_guardian_approved": (
                    first_preemptive_sample.get("reduce_size_guardian_approved") is True
                ),
                "accepted_without_preemptive_decision": (
                    preemptive_edge_control_status.get(
                        "accepted_without_preemptive_decision"
                    )
                ),
                "accepted_high_loss_probability_count": (
                    preemptive_edge_control_status.get(
                        "accepted_high_loss_probability_count"
                    )
                ),
                "reduced_size_without_guardian_approval_count": (
                    preemptive_edge_control_status.get(
                        "reduced_size_without_guardian_approval_count"
                    )
                ),
                "hard_fail": preemptive_edge_control_status.get("hard_fail") is True,
                "advanced_indicators": advanced_indicator_summary,
                "advanced_indicator_status": advanced_indicator_summary.get("status"),
                "advanced_indicator_block_reason_counts": (
                    advanced_indicator_summary.get("block_reason_counts") or {}
                ),
                "advanced_indicator_caution_reason_counts": (
                    advanced_indicator_summary.get("caution_reason_counts") or {}
                ),
                "positive_edge_probation_status": (
                    positive_edge_probation_summary.get("status")
                ),
                "positive_edge_probation_supply_state": (
                    positive_edge_probation_summary.get("supply_state")
                ),
                "positive_edge_probation_candidates": (
                    positive_edge_probation_summary.get("current_candidate_count")
                ),
                "positive_edge_probation_accepted": (
                    positive_edge_probation_summary.get("current_accepted_count")
                ),
                "closed_probation_trade_count": (
                    positive_edge_probation_summary.get("closed_probation_trade_count")
                ),
                "probation_5_trade_gate_status": (
                    positive_edge_probation_summary.get("probation_5_trade_gate_status")
                ),
                "probation_counts_as_final_a_plus": False,
                "probation_counts_as_live_ready": False,
                "why_trade_was_prevented": (
                    paper_preemptive_admission_status.get("prevention_reasons")
                    or paper_preemptive_admission_status.get("top_rejection_reasons")
                    or []
                ),
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            },
            "hedge_cross_margin": adaptive_hedge_cross_margin,
            "providers": provider_readiness,
            "profit_factor": governor.get("profit_factor"),
            "expectancy_usd": (
                round(
                    float(governor.get("realized_pnl_usd") or 0.0)
                    / max(1, int(governor.get("closed_outcome_count") or 0)),
                    8,
                )
                if governor.get("closed_outcome_count")
                else None
            ),
            "realized_pnl_usd": governor.get("realized_pnl_usd"),
            "expectancy_bps": (
                governor.get("notional_weighted_expectancy_bps")
                or governor.get("expectancy_bps")
                or governor.get("expectancy")
            ),
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
    _resp["status"] = _risk_status
    _resp["risk_status"] = _risk_status
    _resp["halt_reasons"] = halt_reasons
    _resp["state_reasons"] = state_reasons
    _resp["top_blockers"] = top_blockers
    _resp["real_trader_readiness"] = risk_readiness_context
    _resp["a_grade_blocker_truth"] = risk_readiness_context["a_grade_blocker_truth"]
    _resp["exact_no_live_reason"] = risk_readiness_context["exact_no_live_reason"]
    _resp["readiness_blockers"] = risk_readiness_context["readiness_blockers"]
    _resp["new_entries_allowed"] = governor.get("new_entries_allowed")
    _resp["recovery_high_confidence_loss_cluster_status"] = cluster_status
    _resp["preemptive_edge_control_status"] = preemptive_edge_control_status
    _resp["preemptive_candidate_decision_matrix"] = preemptive_candidate_decision_matrix_api
    _resp["paper_preemptive_admission_status"] = paper_preemptive_admission_status
    _resp["positive_edge_probation"] = positive_edge_probation_summary
    _resp["advanced_indicators"] = advanced_indicator_summary
    _resp["adaptive_hedge_cross_margin"] = adaptive_hedge_cross_margin
    # Hedge-engine posture roll-up (read-only, on-demand per negative position; never orders).
    try:
        _hedge_block = _hedge_payload(get_redis())
    except Exception:  # pragma: no cover - display convenience must never break risk status
        _hedge_block = {
            "schema_version": "enterprise_hedge_snapshot_v1",
            "hedge_engine_active": True,
            "open_position_count": 0,
            "negative_position_count": 0,
            "hedge_required_candidates": [],
            "places_real_order": False,
            "routes_to_live": False,
        }
    # Surface on both the outer envelope and the unwrapped `data` dict (the web/iOS
    # realtime hook reads `raw.data`, so it must be present there too).
    _resp["hedge"] = _hedge_block
    if isinstance(_resp.get("data"), dict):
        _resp["data"]["hedge"] = _hedge_block
    _resp["provider_readiness"] = provider_readiness
    _resp["positive_edge_probation_policy"] = positive_edge_probation_policy
    _resp["positive_edge_probation_runtime_status"] = positive_edge_probation_runtime_status
    _resp["probation_5_trade_gate"] = probation_5_trade_gate
    _resp["probation_20_trade_gate"] = probation_20_trade_gate
    _resp["probation_50_trade_gate"] = probation_50_trade_gate
    _resp["preemptive_prevention"] = _resp["data"].get("preemptive_prevention")
    _resp["recent_decisions"] = _normalized_decisions
    _resp["active_profile"] = profile_summary
    # Risk gateway heartbeat updates once per cycle (~5-15 min), not per-second.
    # Override stale if classification confirms gateway is live and lag < 15 min.
    _hb_classification = (heartbeat.get("classification") or "") if heartbeat else ""
    _lag = _resp.get("lag_ms")
    if _hb_classification in ("V2_RISK_GATEWAY_LIVE_OK", "RUNTIME_ARTIFACT_CURRENT", "V2_RISK_GATEWAY_OK"):
        _resp["stale"] = _lag is None or _lag > 900_000
    return _resp


@router.get("/risk")
async def get_risk_contract() -> dict[str, Any]:
    """Compatibility alias for `/api/v2/risk`."""
    response = dict(await get_risk_status())
    response["endpoint"] = "/api/v2/risk"
    return response


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


def _paper_a_grade_readiness_context(client: Any) -> dict[str, Any]:
    try:
        from app.api.v2.control_center_status import (  # noqa: PLC0415
            _current_a_grade_blocker_truth,
        )

        truth = _current_a_grade_blocker_truth(client)
        if not isinstance(truth, dict):
            raise TypeError("A-grade blocker truth was not a dict")
    except Exception:
        truth = {
            "schema_version": "control_center_a_grade_blocker_truth_v1",
            "status": "A_GRADE_BLOCKER_TRUTH_UNAVAILABLE",
            "available": False,
            "primary_blocker": "A_GRADE_BLOCKER_TRUTH_UNAVAILABLE",
            "finding_ids": [],
            "live_gate": "blocked_human_only",
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "order_submitted": False,
            "test_order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
        }

    status = str(truth.get("status") or "")
    primary_blocker = (
        truth.get("primary_blocker")
        if status == "A_GRADE_ADAPTATION_NOT_PROVEN"
        else None
    )
    if not primary_blocker and status != "NO_ACTIVE_BLOCKER_DETECTED":
        primary_blocker = status or "A_GRADE_BLOCKER_TRUTH_UNAVAILABLE"
    finding_ids = truth.get("finding_ids") if isinstance(truth.get("finding_ids"), list) else []
    blockers = [
        str(value)
        for value in [primary_blocker, *finding_ids]
        if value
    ]
    if not blockers:
        blockers = ["LIVE_GATE_BLOCKED_HUMAN_ONLY"]
    blockers = list(dict.fromkeys(blockers))
    return {
        "live_gate": "blocked_human_only",
        "operator_flip_required": True,
        "live_ready": False,
        "live_submit_allowed": False,
        "exact_no_live_reason": blockers[0],
        "readiness_blockers": blockers,
        "a_grade_blocker_truth": truth,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "routes_to_live": False,
        "places_real_order": False,
    }


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
        readiness_context = _paper_a_grade_readiness_context(None)
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
            "real_trader_readiness": readiness_context,
            "a_grade_blocker_truth": readiness_context["a_grade_blocker_truth"],
            "top_blockers": readiness_context["readiness_blockers"][:8],
        }, ["Redis unavailable for paper activity; returned structured empty paper state"]
    readiness_context = _paper_a_grade_readiness_context(client)
    hb_raw = client.get("v2:paper:heartbeat")
    heartbeat: dict[str, Any] = json.loads(hb_raw) if hb_raw else {}
    portfolio_raw = client.get("v2:portfolio:state")
    portfolio: dict[str, Any] = json.loads(portfolio_raw) if portfolio_raw else {}
    if not isinstance(portfolio, dict):
        portfolio = {}

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
    canonical_realized_pnl = _float(
        portfolio.get("realized_net_pnl_usd")
        if portfolio.get("realized_net_pnl_usd") is not None
        else portfolio.get("clean_session_valid_realized_pnl_usd")
        if portfolio.get("clean_session_valid_realized_pnl_usd") is not None
        else portfolio.get("realized_pnl_usd")
    )
    canonical_unrealized_pnl = _float(portfolio.get("unrealized_pnl_usd"))
    canonical_total_pnl = _float(portfolio.get("total_pnl_usd"))
    if canonical_total_pnl is None and canonical_realized_pnl is not None:
        canonical_total_pnl = canonical_realized_pnl + (canonical_unrealized_pnl or 0.0)
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
            "realized_pnl_usd": (
                canonical_realized_pnl
                if canonical_realized_pnl is not None
                else heartbeat.get("realized_pnl_usd") or 0.0
            ),
            "realized_net_pnl_usd": canonical_realized_pnl,
            "unrealized_pnl_usd": (
                canonical_unrealized_pnl
                if canonical_unrealized_pnl is not None
                else position_metrics["unrealized_pnl_usd"]
            ),
            "total_pnl_usd": canonical_total_pnl,
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
            "pnl_source_key": portfolio.get("pnl_source_key") or "v2:portfolio:state",
            "pnl_source_route": portfolio.get("pnl_source_route") or "/api/v2/portfolio",
            "pnl_source_type": (
                portfolio.get("pnl_source_type")
                or "CANONICAL_CURRENT_SESSION_RUNTIME"
                if portfolio
                else "fallback:v2:paper:heartbeat"
            ),
            "pnl_conflict_detected": bool(portfolio.get("pnl_conflict_detected")),
            "pnl_source_conflict_detected": bool(portfolio.get("pnl_source_conflict_detected")),
        },
        "stream": {
            "source": "v2:paper:* Redis",
            "transport": "websocket_or_http_polling_fallback",
            "interval_ms": 1000,
            "live_trading_enabled": False,
            "exchange_mutation_enabled": False,
        },
        "real_trader_readiness": readiness_context,
        "a_grade_blocker_truth": readiness_context["a_grade_blocker_truth"],
        "top_blockers": readiness_context["readiness_blockers"][:8],
    }
    return data, warnings


@router.get("/paper/status")
async def get_paper_status(actor: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    endpoint = "/api/v2/paper/status"

    def _load() -> dict[str, Any]:
        try:
            client = get_redis()
            readiness_context = _paper_a_grade_readiness_context(client)
            hb_raw = client.get("v2:paper:heartbeat")
            heartbeat: dict[str, Any] = json.loads(hb_raw) if hb_raw else {}
            portfolio_raw = client.get("v2:portfolio:state")
            portfolio: dict[str, Any] = json.loads(portfolio_raw) if portfolio_raw else {}
            if not isinstance(portfolio, dict):
                portfolio = {}

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

            canonical_realized_pnl = _float(
                portfolio.get("realized_net_pnl_usd")
                if portfolio.get("realized_net_pnl_usd") is not None
                else portfolio.get("clean_session_valid_realized_pnl_usd")
                if portfolio.get("clean_session_valid_realized_pnl_usd") is not None
                else portfolio.get("realized_pnl_usd")
            )
            canonical_unrealized_pnl = _float(portfolio.get("unrealized_pnl_usd"))
            canonical_total_pnl = _float(portfolio.get("total_pnl_usd"))
            if canonical_total_pnl is None and canonical_realized_pnl is not None:
                canonical_total_pnl = canonical_realized_pnl + (canonical_unrealized_pnl or 0.0)

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
                    "realized_pnl_usd": (
                        canonical_realized_pnl
                        if canonical_realized_pnl is not None
                        else heartbeat.get("realized_pnl_usd") or 0.0
                    ),
                    "realized_net_pnl_usd": canonical_realized_pnl,
                    "unrealized_pnl_usd": (
                        canonical_unrealized_pnl
                        if canonical_unrealized_pnl is not None
                        else position_metrics["unrealized_pnl_usd"] if positions else (heartbeat.get("unrealized_pnl_usd") or 0.0)
                    ),
                    "total_pnl_usd": canonical_total_pnl,
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
                    "pnl_source_key": portfolio.get("pnl_source_key") or "v2:portfolio:state",
                    "pnl_source_route": portfolio.get("pnl_source_route") or "/api/v2/portfolio",
                    "pnl_source_type": (
                        portfolio.get("pnl_source_type")
                        or "CANONICAL_CURRENT_SESSION_RUNTIME"
                        if portfolio
                        else "fallback:v2:paper:heartbeat"
                    ),
                    "pnl_conflict_detected": bool(portfolio.get("pnl_conflict_detected")),
                    "pnl_source_conflict_detected": bool(portfolio.get("pnl_source_conflict_detected")),
                },
                "real_trader_readiness": readiness_context,
                "a_grade_blocker_truth": readiness_context["a_grade_blocker_truth"],
                "top_blockers": readiness_context["readiness_blockers"][:8],
                "_warnings": position_warnings,
            }
        except Exception as exc:
            readiness_context = _paper_a_grade_readiness_context(None)
            return {
                "error": str(exc),
                "positions": [],
                "closed_trades": [],
                "equity_curve": [],
                "reason_breakdown": {},
                "risk_profile": {},
                "summary": {},
                "real_trader_readiness": readiness_context,
                "a_grade_blocker_truth": readiness_context["a_grade_blocker_truth"],
                "top_blockers": readiness_context["readiness_blockers"][:8],
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


def _paper_a_plus_runtime_truth_block(client: Any) -> dict[str, Any]:
    """A+ goal Phase 12: session performance, entry freeze, A+ gate, trainer
    learning and real-trader readiness truth shared by web routes."""

    def _get(key: str) -> dict[str, Any]:
        try:
            raw = client.get(key)
            parsed = json.loads(raw) if raw else None
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    governor = _get("v2:paper:performance_governor_status")
    halt = _get("v2:paper:new_entry_emergency_halt_status")
    freeze = _get("v2:paper:entry_freeze")
    a_plus = _get("v2:paper:a_plus_gate:status")
    trainer = _get("v2:trainer:hybrid_cuda:status")
    circuit = _get("v2:paper:performance_circuit_breaker_status")
    bucket_quarantine = (
        circuit.get("bucket_quarantine_status")
        if isinstance(circuit.get("bucket_quarantine_status"), dict)
        else _get("v2:paper:bucket_quarantine_status")
    )
    if not isinstance(bucket_quarantine, dict):
        bucket_quarantine = {}
    cluster_raw = circuit.get("recovery_high_confidence_loss_cluster_status")
    cluster_raw = cluster_raw if isinstance(cluster_raw, dict) else {}
    rejected = a_plus.get("rejected_reason_matrix")
    top_blockers = list(freeze.get("future_gate_blockers") or [])
    for reason in halt.get("halt_reasons") or []:
        if reason not in top_blockers:
            top_blockers.append(reason)
    for reason in circuit.get("block_reasons") or []:
        if reason not in top_blockers:
            top_blockers.append(reason)
    readiness_context = _paper_a_grade_readiness_context(client)
    top_blockers = list(dict.fromkeys([
        *readiness_context["readiness_blockers"],
        *top_blockers,
    ]))

    reduced_semantics, _ = _read_json(
        "operator_runtime/v2_paper_trade_management/latest/"
        "a_plus_gate_after_trust_semantics_status.json"
    )
    reduced_hash_chain, _ = _read_json(
        "operator_runtime/v2_paper_trade_management/latest/"
        "a_plus_reduced_size_bootstrap_hash_chain.json"
    )
    reduced_ts = (
        _timestamp_from_payload(reduced_semantics)
        or _timestamp_from_payload(reduced_hash_chain)
    )
    reduced_lag_ms = _lag_ms(reduced_ts)
    reduced_bootstrap = {
        "schema_version": "runtime_reduced_size_bootstrap_truth_v1",
        "source": (
            "operator_runtime/v2_paper_trade_management/latest/"
            "a_plus_gate_after_trust_semantics_status.json + "
            "a_plus_reduced_size_bootstrap_hash_chain.json"
        ),
        "generated_at": reduced_ts,
        "lag_ms": reduced_lag_ms,
        "stale": reduced_lag_ms is None or reduced_lag_ms > 900_000,
        "final_a_plus_candidates": (
            reduced_semantics.get("final_a_plus_candidates")
            if isinstance(reduced_semantics, dict)
            else None
        ),
        "reduced_size_bootstrap_candidates": (
            reduced_semantics.get("reduced_size_bootstrap_candidates")
            if isinstance(reduced_semantics, dict)
            else None
        ),
        "closed_rows": (
            reduced_hash_chain.get("closed_rows")
            if isinstance(reduced_hash_chain, dict)
            else None
        ),
        "counts_as_final_a_plus": (
            reduced_semantics.get("reduced_size_counts_as_final_a_plus") is True
            or reduced_hash_chain.get("counts_as_final_a_plus") is True
            if isinstance(reduced_hash_chain, dict) and isinstance(reduced_semantics, dict)
            else False
        ),
        "b_grade_counts_as_final_a_plus": (
            reduced_semantics.get("b_grade_counts_as_final_a_plus") is True
            if isinstance(reduced_semantics, dict)
            else False
        ),
        "routes_to_live": (
            reduced_hash_chain.get("routes_to_live") is True
            if isinstance(reduced_hash_chain, dict)
            else False
        ),
        "paper_only": (
            reduced_hash_chain.get("paper_only") is not False
            if isinstance(reduced_hash_chain, dict)
            else True
        ),
        "policy": "REDUCE_SIZE_BOOTSTRAP_PAPER_ONLY_NOT_FINAL_A_PLUS",
    }
    cluster_detected = cluster_raw.get("cluster_detected") is True
    guardian_state = (
        a_plus.get("guardian_status")
        or a_plus.get("continuous_edge_guardian_status")
        or circuit.get("state")
        or circuit.get("status")
    )
    guardian_new_entries_allowed = (
        a_plus.get("guardian_new_entries_allowed")
        if a_plus.get("guardian_new_entries_allowed") is not None
        else a_plus.get("continuous_edge_guardian_new_entries_allowed")
    )
    reduce_size_allowed = (
        halt.get("new_entries_allowed") is True
        and guardian_new_entries_allowed is True
        and not cluster_detected
        and not bool(bucket_quarantine.get("blocked_bucket_keys"))
    )
    derived_cluster = _high_confidence_cluster_derived_dimensions(cluster_raw)
    high_confidence_cluster = {
        "schema_version": "runtime_high_confidence_loss_cluster_truth_v1",
        "status": (
            cluster_raw.get("status")
            or ("BLOCKED_HIGH_CONFIDENCE_LOSS_CLUSTER" if cluster_detected else "CLEAR")
        ),
        "active": cluster_detected,
        "cluster_detected": cluster_detected,
        "cluster_count": cluster_raw.get("high_confidence_loss_count"),
        "high_confidence_loss_count": cluster_raw.get("high_confidence_loss_count"),
        "affected_symbols": derived_cluster["affected_symbols"],
        "affected_buckets": {
            "sides": derived_cluster["quarantined_sides"],
            "timeframes": derived_cluster["quarantined_timeframes"],
            "strategy_modes": derived_cluster["quarantined_strategy_modes"],
            "blocked_bucket_keys": (bucket_quarantine.get("blocked_bucket_keys") or [])[:20],
        },
        "affected_dimension_counts": derived_cluster["affected_dimension_counts"],
        "guardian_state": guardian_state,
        "guardian_new_entries_allowed": guardian_new_entries_allowed,
        "reduce_size_bootstrap_allowed": reduce_size_allowed,
        "reduce_size_policy": "REDUCE_SIZE_BOOTSTRAP_PAPER_ONLY_NOT_FINAL_A_PLUS",
        "why_reduce_size_blocked": (
            "HIGH_CONFIDENCE_LOSS_CLUSTER_ACTIVE"
            if cluster_detected
            else "BUCKET_QUARANTINE_ACTIVE"
            if bucket_quarantine.get("blocked_bucket_keys")
            else "GUARDIAN_OR_GLOBAL_ENTRY_GATE_BLOCKED"
            if not reduce_size_allowed
            else None
        ),
        "post_patch_recovery_status": (
            "BLOCKED_CURRENT_CLUSTER_NO_POST_PATCH_RECOVERY_PROOF"
            if cluster_detected
            else "NO_ACTIVE_HIGH_CONFIDENCE_CLUSTER"
        ),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    return {
        "performance": {
            "profit_factor": governor.get("profit_factor"),
            "expectancy_usd": (
                round(
                    float(governor.get("realized_pnl_usd") or 0.0)
                    / max(1, int(governor.get("closed_outcome_count") or 0)),
                    8,
                )
                if governor.get("closed_outcome_count")
                else None
            ),
            "realized_pnl_usd": governor.get("realized_pnl_usd"),
            "notional_weighted_expectancy_bps": governor.get("notional_weighted_expectancy_bps"),
            "win_rate": governor.get("win_rate"),
            "closed_outcome_count": governor.get("closed_outcome_count"),
            "governor_state": governor.get("state"),
        },
        "entry_freeze": {
            "new_entries_allowed": halt.get("new_entries_allowed"),
            "halt_reasons": halt.get("halt_reasons"),
            "future_gate_blockers": freeze.get("future_gate_blockers"),
            "allow_close": halt.get("allow_close"),
            "allow_reduce": halt.get("allow_reduce"),
        },
        "a_plus_gate": {
            "evaluated_candidates": a_plus.get("evaluated_candidates"),
            "a_plus_candidates": a_plus.get("a_plus_candidates"),
            "rejected_reason_matrix": dict(list(rejected.items())[:8]) if isinstance(rejected, dict) else None,
            "gate_is_hard_entry_condition": a_plus.get("gate_is_hard_entry_condition"),
        },
        "reduced_size_bootstrap": reduced_bootstrap,
        "high_confidence_loss_cluster": high_confidence_cluster,
        "post_patch_recovery": {
            "status": high_confidence_cluster["post_patch_recovery_status"],
            "do_not_mix_pre_patch_rows": True,
            "five_trade_gate": (
                "BLOCKED_CURRENT_CLUSTER"
                if cluster_detected
                else "NOT_EVALUATED_NO_POST_PATCH_SAMPLE"
            ),
            "fifty_trade_gate": "NOT_EVALUATED_NO_POST_PATCH_SAMPLE",
            "three_hundred_trade_gate": "NOT_EVALUATED_NO_POST_PATCH_SAMPLE",
        },
        "trainer_learning": {
            "effective_trainer_mode": trainer.get("effective_trainer_mode"),
            "online_learning_status": trainer.get("online_learning_status"),
            "last_successful_weight_update_at": trainer.get("last_successful_weight_update_at"),
            "checkpoint_id": trainer.get("checkpoint_id"),
        },
        "real_trader_readiness": readiness_context,
        "a_grade_blocker_truth": readiness_context["a_grade_blocker_truth"],
        "top_blockers": top_blockers[:6],
    }


@router.get("/paper/runtime-status")
async def get_paper_runtime_status(
    actor: UserRecord | None = Depends(optional_auth),
    debug: bool = False,
) -> dict[str, Any]:
    """Real-time paper runtime status synthesized from Redis — replaces stale static file."""

    def _coinapi_provider_unusable_status(client: Any, source: Any) -> str | None:
        if "coinapi" not in str(source or "").lower():
            return None
        try:
            keys = list(client.keys("v2:market:coinapi:rest:status:*") or [])[:20]
        except Exception:
            keys = []
        if not keys:
            return "COINAPI_STATUS_KEYS_MISSING_NOT_CURRENT_SOURCE"

        sampled = 0
        upstream_errors = 0
        usable_payloads = 0
        for key in keys:
            try:
                raw = client.get(key)
                payload = json.loads(raw) if raw else {}
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            sampled += 1
            http_status_raw = payload.get("http_status")
            try:
                http_status = int(http_status_raw)
            except (TypeError, ValueError):
                http_status = None
            has_upstream_error = (
                (http_status is not None and http_status >= 400)
                or bool(payload.get("error"))
                or bool(payload.get("upstream_error"))
                or bool(payload.get("provider_unusable_reason"))
            )
            has_usable_market_data = bool(
                payload.get("orderbook_present")
                or payload.get("ohlcv_present_timeframes")
                or payload.get("ohlcv")
            )
            if has_upstream_error:
                upstream_errors += 1
            elif has_usable_market_data:
                usable_payloads += 1

        if sampled and upstream_errors >= max(1, sampled // 2):
            return "COINAPI_HTTP_FORBIDDEN_OR_EXPIRED_NOT_CURRENT_SOURCE"
        if sampled and usable_payloads == 0:
            return "COINAPI_NO_USABLE_OHLCV_OR_ORDERBOOK_NOT_CURRENT_SOURCE"
        if not sampled:
            return "COINAPI_STATUS_PAYLOADS_UNREADABLE_NOT_CURRENT_SOURCE"
        return None

    def _build_primary() -> dict[str, Any]:
        try:
            client = get_redis()
            now = _utc_now()
            if client is None:
                raise RuntimeError("redis_unavailable")
            readiness_context = _paper_a_grade_readiness_context(client)

            def _read(key: str) -> dict[str, Any]:
                try:
                    return _json_object_from_redis_raw(client.get(key)) or {}
                except Exception:
                    return {}

            hb = _read("v2:paper:heartbeat")
            tm = _read("v2:paper:trade_management:status")

            def _contract(key: str, embedded_key: str, fallback: dict[str, Any]) -> dict[str, Any]:
                payload = _read(key)
                if not payload:
                    embedded = tm.get(embedded_key)
                    payload = embedded if isinstance(embedded, dict) else {}
                payload = _compact_paper_runtime_contract(payload) if payload else dict(fallback)
                payload.setdefault("available", bool(payload))
                payload.setdefault("source", f"redis:{key}")
                payload.setdefault("paper_only", True)
                payload.setdefault("routes_to_live", False)
                payload.setdefault("places_real_order", False)
                return _compact_paper_runtime_response(payload)

            preemptive_status = _contract(
                "v2:paper:preemptive_edge_control_status",
                "preemptive_edge_control_status",
                {
                    "schema_version": "preemptive_edge_control_status_v1",
                    "status": "PREEMPTIVE_EDGE_CONTROL_STATUS_UNAVAILABLE",
                    "available": False,
                    "candidate_count": 0,
                    "accepted_count": 0,
                    "decision_counts": {},
                },
            )
            preemptive_matrix = _contract(
                "v2:paper:preemptive_candidate_decision_matrix",
                "preemptive_candidate_decision_matrix",
                {
                    "schema_version": "preemptive_candidate_decision_matrix_v1",
                    "status": "PREEMPTIVE_CANDIDATE_DECISION_MATRIX_UNAVAILABLE",
                    "available": False,
                    "candidate_count": 0,
                    "sample_decisions": [],
                },
            )
            probation_runtime = _contract(
                "v2:paper:positive_edge_probation_runtime_status",
                "positive_edge_probation_runtime_status",
                {
                    "schema_version": "positive_edge_probation_runtime_status_v1",
                    "status": "POSITIVE_EDGE_PROBATION_RUNTIME_STATUS_UNAVAILABLE",
                    "available": False,
                    "current_candidate_count": 0,
                    "current_accepted_count": 0,
                    "closed_probation_trade_count": 0,
                    "counts_as_final_a_plus": False,
                    "counts_as_live_ready": False,
                },
            )
            probation_5_gate = _contract(
                "v2:paper:probation_5_trade_gate",
                "probation_5_trade_gate",
                {
                    "schema_version": "positive_edge_probation_trade_gate_v1",
                    "status": "PROBATION_5_TRADE_GATE_WAITING_OR_BLOCKED",
                    "available": False,
                    "closed_count": 0,
                },
            )
            paper_no_bad_entry_runtime_status = _contract(
                "v2:paper:no_bad_entry_runtime_status",
                "paper_no_bad_entry_runtime_status",
                {
                    "schema_version": "paper_no_bad_entry_runtime_status_v1",
                    "status": "PAPER_NO_BAD_ENTRY_RUNTIME_STATUS_UNAVAILABLE",
                    "available": False,
                    "hard_fail": True,
                    "generated_at": now,
                },
            )
            paper_entry_freeze = _read("v2:paper:entry_freeze")
            hb_ts = hb.get("heartbeat_generated_at") or hb.get("started_at") or now
            hb_age = _lag_ms(hb_ts if isinstance(hb_ts, str) else None)
            heartbeat_fresh = hb_age is not None and hb_age < 900_000
            probation_candidates = _integer(probation_runtime.get("current_candidate_count")) or 0
            probation_accepted = _integer(probation_runtime.get("current_accepted_count")) or 0
            closed_probation = _integer(probation_runtime.get("closed_probation_trade_count")) or 0
            preemptive_rows = preemptive_matrix.get("sample_decisions")
            if not isinstance(preemptive_rows, list):
                preemptive_rows = []
            first_preemptive = preemptive_rows[0] if preemptive_rows and isinstance(preemptive_rows[0], dict) else {}
            account = _runtime_canonical_paper_account(client)
            runtime_admission_status = (
                tm.get("paper_runtime_admission_status")
                if isinstance(tm.get("paper_runtime_admission_status"), dict)
                else {}
            )
            runtime_cost_capture_status = (
                tm.get("paper_runtime_cost_capture_status")
                if isinstance(tm.get("paper_runtime_cost_capture_status"), dict)
                else {}
            )
            a_grade_gate_key = "v2:paper:a_grade_gate_burndown_status"
            a_grade_gate_status = _read(a_grade_gate_key)
            a_grade_gate_source = f"redis:{a_grade_gate_key}" if a_grade_gate_status else ""
            if not a_grade_gate_status:
                embedded_a_grade_gate = tm.get("paper_a_grade_gate_burndown_status")
                if isinstance(embedded_a_grade_gate, dict):
                    a_grade_gate_status = embedded_a_grade_gate
                    a_grade_gate_source = (
                        "redis:v2:paper:trade_management:status."
                        "paper_a_grade_gate_burndown_status"
                    )
            a_grade_gate_status = (
                _compact_paper_runtime_contract(a_grade_gate_status)
                if a_grade_gate_status
                else {
                    "schema_version": "paper_a_grade_gate_burndown_status_v1",
                    "status": "A_GRADE_GATE_BURNDOWN_STATUS_UNAVAILABLE",
                    "available": False,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "A_grade_rows": 0,
                    "a_grade_rows": 0,
                    "near_A_grade_rows": 0,
                    "near_a_grade_rows": 0,
                    "source_tier_a_grade_execution_rows": 0,
                    "predicate_counts": {},
                    "generated_at": now,
                }
            )
            a_grade_gate_status.setdefault(
                "source", a_grade_gate_source or f"redis:{a_grade_gate_key}"
            )
            a_grade_gate_status.setdefault("available", bool(a_grade_gate_source))
            a_grade_rows = (
                _integer(a_grade_gate_status.get("A_grade_rows"))
                if a_grade_gate_status.get("A_grade_rows") is not None
                else _integer(a_grade_gate_status.get("a_grade_rows"))
            ) or 0
            near_a_grade_rows = (
                _integer(a_grade_gate_status.get("near_A_grade_rows"))
                if a_grade_gate_status.get("near_A_grade_rows") is not None
                else _integer(a_grade_gate_status.get("near_a_grade_rows"))
            ) or 0
            source_tier_a_grade_execution_rows = (
                _integer(a_grade_gate_status.get("source_tier_a_grade_execution_rows"))
                if a_grade_gate_status.get("source_tier_a_grade_execution_rows") is not None
                else _integer(
                    a_grade_gate_status.get("source_tier_A_grade_execution_rows")
                )
            ) or 0
            a_grade_gate_status["A_grade_rows"] = a_grade_rows
            a_grade_gate_status["a_grade_rows"] = a_grade_rows
            a_grade_gate_status["near_A_grade_rows"] = near_a_grade_rows
            a_grade_gate_status["near_a_grade_rows"] = near_a_grade_rows
            a_grade_gate_status["source_tier_a_grade_execution_rows"] = (
                source_tier_a_grade_execution_rows
            )
            guardian_gate_status = (
                a_grade_gate_status.get("guardian_gate_status")
                if isinstance(a_grade_gate_status.get("guardian_gate_status"), dict)
                else {}
            )
            if guardian_gate_status:
                failure_reasons = guardian_gate_status.get("failure_reasons")
                a_grade_gate_status.setdefault(
                    "guardian_status", guardian_gate_status.get("status")
                )
                a_grade_gate_status.setdefault(
                    "guardian_new_entries_allowed",
                    guardian_gate_status.get("a_grade_new_entries_allowed"),
                )
                a_grade_gate_status.setdefault(
                    "guardian_block_all_new_a_grade_entries",
                    guardian_gate_status.get("block_all_new_a_grade_entries"),
                )
                a_grade_gate_status.setdefault(
                    "guardian_failure_reason_count",
                    len(failure_reasons) if isinstance(failure_reasons, list) else 0,
                )
            a_grade_predicates = (
                a_grade_gate_status.get("predicate_counts")
                if isinstance(a_grade_gate_status.get("predicate_counts"), dict)
                else {}
            )
            if not isinstance(a_grade_gate_status.get("pass_conditions"), dict):
                root_cause_counts = a_grade_gate_status.get("root_cause_counts")
                root_cause_counts = (
                    root_cause_counts if isinstance(root_cause_counts, dict) else {}
                )
                a_grade_gate_status["pass_conditions"] = {
                    "A_grade_rows_gt_zero": a_grade_rows > 0,
                    "source_owned_zero_supply_root_cause_mapped": bool(
                        a_grade_gate_status.get("closest_gap_reason")
                        or root_cause_counts
                    ),
                    "a_grade_new_entries_allowed": (
                        a_grade_gate_status.get("guardian_new_entries_allowed") is True
                    ),
                    "ready_allowed": False,
                }
            def _first_runtime_integer(*values: Any, default: int = 0) -> int:
                for value in values:
                    parsed = _integer(value)
                    if parsed is not None:
                        return parsed
                return default

            intent_rows = _first_runtime_integer(
                runtime_cost_capture_status.get("paper_intent_rows"),
                runtime_admission_status.get("intents_built"),
                a_grade_gate_status.get("prediction_rows"),
            )
            order_applicable_rows = _integer(
                runtime_cost_capture_status.get("order_cost_applicable_rows")
            )
            if order_applicable_rows is None:
                order_applicable_rows = intent_rows
            production_grade_cost_rows = _first_runtime_integer(
                runtime_cost_capture_status.get("production_grade_cost_rows"),
                a_grade_gate_status.get("production_grade_cost_rows"),
                a_grade_predicates.get("production_grade_cost_rows"),
            )
            production_grade_cost_order_applicable_rows = _integer(
                runtime_cost_capture_status.get(
                    "production_grade_cost_order_applicable_rows"
                )
            )
            if production_grade_cost_order_applicable_rows is None:
                production_grade_cost_order_applicable_rows = min(
                    production_grade_cost_rows,
                    order_applicable_rows,
                )
            total_row_cost_coverage = _float(
                runtime_cost_capture_status.get(
                    "production_grade_cost_total_row_coverage"
                )
            )
            if total_row_cost_coverage is None:
                total_row_cost_coverage = (
                    production_grade_cost_rows / intent_rows if intent_rows else 0.0
                )
            cost_coverage = _float(
                runtime_cost_capture_status.get("production_grade_cost_coverage")
            )
            if cost_coverage is None:
                cost_coverage = (
                    production_grade_cost_order_applicable_rows / order_applicable_rows
                    if order_applicable_rows
                    else 0.0
                )
            cost_coverage_basis = str(
                runtime_cost_capture_status.get(
                    "production_grade_cost_coverage_basis"
                )
                or ""
            )
            if (
                order_applicable_rows == 0
                and intent_rows > 0
                and total_row_cost_coverage > cost_coverage
            ):
                cost_coverage = total_row_cost_coverage
                cost_coverage_basis = (
                    "all_intent_rows_no_order_applicable_api_repaired"
                )
            elif order_applicable_rows == 0 and intent_rows > 0:
                cost_coverage_basis = "all_intent_rows_no_order_applicable"
            elif not cost_coverage_basis:
                cost_coverage_basis = "order_applicable_rows"
            no_order_explained_rows = _first_runtime_integer(
                runtime_cost_capture_status.get("no_order_explained_rows")
            )
            unexplained_missing_cost_rows = _first_runtime_integer(
                runtime_cost_capture_status.get("unexplained_missing_cost_rows")
            )
            no_order_missing_cost_rows = _first_runtime_integer(
                runtime_cost_capture_status.get("no_order_missing_cost_rows")
            )
            paper_fill_allowed_rows = _first_runtime_integer(
                runtime_cost_capture_status.get("paper_fill_allowed_rows"),
                runtime_admission_status.get("accepted_count"),
            )
            routes_to_live_rows = _first_runtime_integer(
                runtime_cost_capture_status.get("routes_to_live_rows")
            )
            places_real_order_rows = _first_runtime_integer(
                runtime_cost_capture_status.get("places_real_order_rows")
            )
            runtime_state = "PAPER_RUNTIME_ONLINE_ACTIVE" if heartbeat_fresh else "PAPER_RUNTIME_STALE_HEARTBEAT"
            blockers: list[dict[str, Any]] = []
            if probation_candidates <= 0:
                blockers.append({
                    "id": "POSITIVE_EDGE_PROBATION_SUPPLY_ZERO",
                    "severity": "runtime_blocker",
                    "detail": "No current positive-edge probation candidates are available.",
                    "source": probation_runtime.get("source"),
                })
            if paper_entry_freeze.get("new_entries_allowed") is False:
                blockers.append({
                    "id": "PAPER_ENTRY_FREEZE",
                    "severity": "runtime_blocker",
                    "detail": "Paper new entries are currently frozen by runtime gate.",
                    "source": "redis:v2:paper:entry_freeze",
                })
            if a_grade_rows <= 0:
                a_grade_blocker = {
                    "id": "A_GRADE_SUPPLY_ZERO",
                    "severity": "runtime_blocker",
                    "detail": "No strict A-grade paper rows are currently available.",
                    "source": a_grade_gate_status.get("source"),
                    "status": a_grade_gate_status.get(
                        "status",
                        "A_GRADE_GATE_STATUS_UNAVAILABLE",
                    ),
                    "guardian_status": a_grade_gate_status.get("guardian_status"),
                    "guardian_new_entries_allowed": a_grade_gate_status.get(
                        "guardian_new_entries_allowed"
                    ),
                }
                for field in (
                    "A_grade_rows",
                    "a_grade_rows",
                    "near_A_grade_rows",
                    "near_a_grade_rows",
                    "closest_gap_reason",
                    "predicate_counts",
                    "root_cause_counts",
                    "dominant_current_runtime_reasons",
                    "source_rows",
                    "guardian_block_all_new_a_grade_entries",
                    "guardian_failure_reason_count",
                    "source_tier_a_grade_execution_rows",
                    "pass_conditions",
                ):
                    if field in a_grade_gate_status:
                        a_grade_blocker[field] = a_grade_gate_status[field]
                blockers.append({
                    **a_grade_blocker,
                })
            return {
                "schema_version": "paper_runtime_status_primary_v1",
                "generated_at": now,
                "generated_at_utc": now,
                "generated_at_et": _to_et(now) or _et_now(),
                "timestamp_et": _to_et(now) or _et_now(),
                "received_at": now,
                "received_et": _et_now(),
                "endpoint": "/api/v2/paper/runtime-status",
                "source": "redis_live",
                "source_type": "paper_runtime_redis_live",
                "canonical_owner": "/api/v2/paper/runtime-status",
                "staleness_seconds": round(hb_age / 1000, 3) if hb_age is not None else None,
                "freshness_status": "fresh" if heartbeat_fresh else "stale",
                "data_quality_status": "fresh" if heartbeat_fresh else "degraded",
                "runtime": hb.get("worker_id", "v2_trade_management_paper_loop"),
                "runtime_state": runtime_state,
                "account_scope": "PAPER_SIM_ACCOUNT",
                "paper_or_live": "paper",
                "contains_simulated_positions": True,
                "contains_live_positions": False,
                "contains_quarantined_positions": False,
                "equity_trusted": False,
                "pnl_trusted": False,
                "reason_if_untrusted": "PAPER_RUNTIME_STATUS_IS_OPERATIONAL_HEALTH_NOT_PORTFOLIO_EQUITY_TRUTH",
                "live_gate": "blocked_human_only",
                "live_gate_status": "blocked_human_only",
                "places_real_order": False,
                "routes_to_live": False,
                "mode": "paper",
                "real_trader_readiness": readiness_context,
                "a_grade_blocker_truth": readiness_context["a_grade_blocker_truth"],
                "exact_no_live_reason": readiness_context["exact_no_live_reason"],
                "readiness_blockers": readiness_context["readiness_blockers"],
                "top_blockers": readiness_context["readiness_blockers"][:8],
                "continuous_loop_available": heartbeat_fresh,
                "loop_interval_seconds": 10,
                "writes_only_local_v2_artifacts": True,
                "legacy_redis_writes": bool(hb.get("writes_legacy_redis", False)),
                "exchange_orders": False,
                "leverage_changes": False,
                "margin_mode_changes": False,
                "redis_trim_approval_created": False,
                "preemptive_edge_control": {
                    "status": (
                        "PREEMPTIVE_EDGE_CONTROL_ACTIVE"
                        if preemptive_status.get("available") is True
                        else "PREEMPTIVE_EDGE_CONTROL_NOT_YET_PUBLISHED"
                    ),
                    "decision_counts": preemptive_status.get("decision_counts") or {},
                    "action_counts": preemptive_status.get("action_counts") or {},
                    "preemptive_decision_id": first_preemptive.get("preemptive_decision_id"),
                    "preemptive_action": first_preemptive.get("preemptive_action"),
                    "preemptive_allowed": first_preemptive.get("preemptive_allowed") is True,
                    "preemptive_block_reasons": (
                        first_preemptive.get("preemptive_block_reasons")
                        or first_preemptive.get("preemptive_decision_reasons")
                        or []
                    ),
                    "candidate_count": preemptive_status.get("candidate_count"),
                    "accepted_count": preemptive_status.get("accepted_count"),
                    "hard_fail": preemptive_status.get("hard_fail") is True,
                    "positive_edge_probation_status": probation_runtime.get("status"),
                    "positive_edge_probation_supply_state": (
                        "NO_SAFE_TRADE_SUPPLY"
                        if probation_candidates <= 0
                        else "POSITIVE_EDGE_PROBATION_SUPPLY_AVAILABLE"
                    ),
                    "positive_edge_probation_candidates": probation_candidates,
                    "positive_edge_probation_accepted": probation_accepted,
                    "closed_probation_trade_count": closed_probation,
                    "probation_5_trade_gate_status": probation_gate_display_status(probation_5_gate),
                    "probation_counts_as_final_a_plus": False,
                    "probation_counts_as_live_ready": False,
                    "why_trade_was_prevented": [
                        item.get("id")
                        for item in blockers
                        if isinstance(item, dict)
                    ],
                    "governor_auto_action": (
                        "halt_new_entries"
                        if paper_entry_freeze.get("new_entries_allowed") is False
                        else "evaluate_preemptive_candidate"
                    ),
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                },
                "preemptive_edge_control_status": preemptive_status,
                "preemptive_candidate_decision_matrix": preemptive_matrix,
                "positive_edge_probation": {
                    "status": probation_runtime.get("status"),
                    "current_candidate_count": probation_candidates,
                    "current_accepted_count": probation_accepted,
                    "closed_probation_trade_count": closed_probation,
                    "probation_5_trade_gate_status": probation_gate_display_status(probation_5_gate),
                    "counts_as_final_a_plus": False,
                    "counts_as_live_ready": False,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                },
                "positive_edge_probation_runtime_status": probation_runtime,
                "probation_5_trade_gate": probation_5_gate,
                "paper_no_bad_entry_runtime_status": paper_no_bad_entry_runtime_status,
                "paper_loop": {
                    "state": hb.get("cycle_state", "RUNNING_CYCLE"),
                    "tick_id": hb.get("candidate_id", ""),
                    "candidate_id": hb.get("candidate_id"),
                    "policy_id": hb.get("policy_id"),
                    "paper_policy_owner": hb.get("paper_policy_owner"),
                    "current_allowed_paper_owner": hb.get("current_allowed_paper_owner"),
                    "policy_fingerprint": hb.get("policy_fingerprint") or hb.get("selector_policy_fingerprint"),
                    "model_source": hb.get("model_source"),
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "paper_entry_freeze": paper_entry_freeze,
                    "paper_new_entries_halted": paper_entry_freeze.get("new_entries_allowed") is False,
                    "last_tick_at": hb_ts or now,
                    "paper_event_count": _integer(
                        hb.get("paper_event_count")
                        or hb.get("persistent_accepted_fill_count")
                        or hb.get("accepted_count")
                    ) or 0,
                    "order_cost_applicable_rows": order_applicable_rows,
                    "production_grade_cost_rows": production_grade_cost_rows,
                    "production_grade_cost_order_applicable_rows": (
                        production_grade_cost_order_applicable_rows
                    ),
                    "production_grade_cost_coverage": cost_coverage,
                    "production_grade_cost_coverage_basis": cost_coverage_basis,
                    "production_grade_cost_total_row_coverage": total_row_cost_coverage,
                    "no_order_explained_rows": no_order_explained_rows,
                    "unexplained_missing_cost_rows": unexplained_missing_cost_rows,
                    "no_order_missing_cost_rows": no_order_missing_cost_rows,
                    "paper_fill_allowed_rows": paper_fill_allowed_rows,
                    "routes_to_live_rows": routes_to_live_rows,
                    "places_real_order_rows": places_real_order_rows,
                    "a_grade_rows": a_grade_rows,
                    "near_a_grade_rows": near_a_grade_rows,
                    "source_tier_a_grade_execution_rows": (
                        source_tier_a_grade_execution_rows
                    ),
                    "guardian_status": a_grade_gate_status.get("guardian_status"),
                    "guardian_new_entries_allowed": a_grade_gate_status.get(
                        "guardian_new_entries_allowed"
                    ),
                    "guardian_block_all_new_a_grade_entries": (
                        a_grade_gate_status.get("guardian_block_all_new_a_grade_entries")
                    ),
                    "a_grade_predicate_counts": a_grade_predicates,
                    "paper_a_grade_gate_burndown_status": a_grade_gate_status,
                    "preemptive_edge_control_status": preemptive_status,
                    "preemptive_candidate_decision_matrix": preemptive_matrix,
                    "positive_edge_probation": probation_runtime,
                    "probation_5_trade_gate": probation_5_gate,
                    "paper_no_bad_entry_runtime_status": paper_no_bad_entry_runtime_status,
                },
                "paper_account": account,
                "safety": {
                    "live_trading_enabled": False,
                    "exchange_orders_enabled": False,
                    "leverage_changes_enabled": False,
                    "margin_mode_changes_enabled": False,
                    "legacy_redis_writes_enabled": False,
                    "live_gate_status": "blocked_human_only",
                },
                "blockers": blockers,
                "freshness": {
                    "status": "REALTIME_RUNTIME_EVIDENCE" if heartbeat_fresh else "STALE_HEARTBEAT",
                    "generated_at": now,
                    "runtime_age_seconds": int(hb_age / 1000) if hb_age is not None else None,
                    "source_type": "redis_live",
                },
                "primary_api_payload_compacted": True,
                "debug_detail_route": "/api/v2/paper/runtime-status?debug=true",
            }
        except Exception as exc:
            now = _utc_now()
            readiness_context = _paper_a_grade_readiness_context(None)
            return {
                "schema_version": "paper_runtime_status_primary_v1",
                "generated_at": now,
                "generated_at_utc": now,
                "generated_at_et": _to_et(now) or _et_now(),
                "runtime": "v2_trade_management_paper_loop",
                "runtime_state": "PAPER_RUNTIME_EVIDENCE_ERROR",
                "account_scope": "PAPER_SIM_ACCOUNT",
                "source": "redis_live",
                "source_type": "paper_runtime_error",
                "canonical_owner": "/api/v2/paper/runtime-status",
                "freshness_status": "unavailable",
                "data_quality_status": "unavailable",
                "live_gate": "blocked_human_only",
                "places_real_order": False,
                "routes_to_live": False,
                "mode": "paper",
                "real_trader_readiness": readiness_context,
                "a_grade_blocker_truth": readiness_context["a_grade_blocker_truth"],
                "exact_no_live_reason": readiness_context["exact_no_live_reason"],
                "readiness_blockers": readiness_context["readiness_blockers"],
                "top_blockers": readiness_context["readiness_blockers"][:8],
                "error": str(exc),
                "exchange_orders": False,
                "legacy_redis_writes": False,
                "leverage_changes": False,
                "margin_mode_changes": False,
                "continuous_loop_available": False,
                "primary_api_payload_compacted": True,
                "debug_detail_route": "/api/v2/paper/runtime-status?debug=true",
            }

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
            market_freshness_state = (
                "MARKET_FEED_CURRENT"
                if market_age_s is not None and market_age_s < 600
                else "MARKET_FEED_STALE"
            )
            market_source = market_hb.get("source", "coinapi_rest")
            if market_freshness_state != "MARKET_FEED_CURRENT" and "coinapi" in str(market_source).lower():
                market_source = "coinapi_stale_or_unavailable_not_current_source"
            coinapi_unusable_reason = _coinapi_provider_unusable_status(client, market_source)
            if coinapi_unusable_reason:
                market_source = "coinapi_provider_unusable_not_current_source"
                market_freshness_state = "MARKET_FEED_PROVIDER_UNUSABLE_NOT_CURRENT"

            paper_event_count = int(
                hb.get("paper_event_count")
                or hb.get("persistent_accepted_fill_count")
                or hb.get("accepted_count")
                or 0
            )

            tm_raw = client.get("v2:paper:trade_management:status")
            trade_management_status = _json_object_from_redis_raw(tm_raw) or {}
            def _paper_contract_from_key(
                key: str,
                embedded_key: str,
                fallback: dict[str, Any],
            ) -> dict[str, Any]:
                try:
                    raw = client.get(key)
                except Exception:
                    raw = None
                payload = _json_object_from_redis_raw(raw)
                if not payload:
                    embedded = trade_management_status.get(embedded_key)
                    if isinstance(embedded, dict):
                        payload = embedded
                if not payload:
                    payload = dict(fallback)
                else:
                    payload = _compact_paper_runtime_contract(payload)
                    payload.setdefault("available", True)
                payload.setdefault("source", f"redis:{key}")
                payload.setdefault("paper_only", True)
                payload.setdefault("routes_to_live", False)
                payload.setdefault("places_real_order", False)
                return payload

            preemptive_edge_control_status = _paper_contract_from_key(
                "v2:paper:preemptive_edge_control_status",
                "preemptive_edge_control_status",
                {
                    "schema_version": "preemptive_edge_control_status_v1",
                    "status": "PREEMPTIVE_EDGE_CONTROL_STATUS_UNAVAILABLE",
                    "available": False,
                    "candidate_count": 0,
                    "accepted_count": 0,
                    "decision_counts": {},
                    "hard_fail": True,
                    "generated_at": now,
                },
            )
            preemptive_candidate_decision_matrix = _paper_contract_from_key(
                "v2:paper:preemptive_candidate_decision_matrix",
                "preemptive_candidate_decision_matrix",
                {
                    "schema_version": "preemptive_candidate_decision_matrix_v1",
                    "status": "PREEMPTIVE_CANDIDATE_DECISION_MATRIX_UNAVAILABLE",
                    "available": False,
                    "candidate_count": 0,
                    "sample_decisions": [],
                    "generated_at": now,
                },
            )
            preemptive_rows = (
                preemptive_candidate_decision_matrix.get("rows")
                or preemptive_candidate_decision_matrix.get("sample_decisions")
                or []
            )
            preemptive_rows = preemptive_rows if isinstance(preemptive_rows, list) else []
            first_preemptive_sample = (
                preemptive_rows[0]
                if preemptive_rows and isinstance(preemptive_rows[0], dict)
                else {}
            )
            paper_preemptive_admission_status = _paper_contract_from_key(
                "v2:paper:preemptive_admission_status",
                "paper_preemptive_admission_status",
                {
                    "schema_version": "paper_preemptive_admission_status_v1",
                    "status": "PAPER_PREEMPTIVE_ADMISSION_STATUS_UNAVAILABLE",
                    "available": False,
                    "hard_fail": True,
                    "accepted_without_preemptive_decision": None,
                    "accepted_high_loss_probability_count": None,
                    "reduced_size_without_guardian_approval_count": None,
                    "generated_at": now,
                },
            )
            paper_no_bad_entry_runtime_status = _paper_contract_from_key(
                "v2:paper:no_bad_entry_runtime_status",
                "paper_no_bad_entry_runtime_status",
                {
                    "schema_version": "paper_no_bad_entry_runtime_status_v1",
                    "status": "PAPER_NO_BAD_ENTRY_RUNTIME_STATUS_UNAVAILABLE",
                    "available": False,
                    "hard_fail": True,
                    "generated_at": now,
                },
            )
            positive_edge_probation_policy = _paper_contract_from_key(
                "v2:paper:positive_edge_probation_policy",
                "positive_edge_probation_policy",
                {
                    "schema_version": "positive_edge_probation_policy_v1",
                    "status": "POSITIVE_EDGE_PROBATION_POLICY_UNAVAILABLE",
                    "enabled": False,
                    "available": False,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "generated_at": now,
                },
            )
            positive_edge_probation_runtime_status = _paper_contract_from_key(
                "v2:paper:positive_edge_probation_runtime_status",
                "positive_edge_probation_runtime_status",
                {
                    "schema_version": "positive_edge_probation_runtime_status_v1",
                    "status": "POSITIVE_EDGE_PROBATION_RUNTIME_STATUS_UNAVAILABLE",
                    "available": False,
                    "current_candidate_count": 0,
                    "current_accepted_count": 0,
                    "closed_probation_trade_count": 0,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "counts_as_final_a_plus": False,
                    "counts_as_live_ready": False,
                    "generated_at": now,
                },
            )
            probation_5_trade_gate = _paper_contract_from_key(
                "v2:paper:probation_5_trade_gate",
                "probation_5_trade_gate",
                {
                    "schema_version": "positive_edge_probation_trade_gate_v1",
                    "status": "PROBATION_5_TRADE_GATE_WAITING_OR_BLOCKED",
                    "available": False,
                    "closed_count": 0,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "generated_at": now,
                },
            )
            probation_20_trade_gate = _paper_contract_from_key(
                "v2:paper:probation_20_trade_gate",
                "probation_20_trade_gate",
                {
                    "schema_version": "positive_edge_probation_trade_gate_v1",
                    "status": "PROBATION_20_TRADE_GATE_WAITING_OR_BLOCKED",
                    "available": False,
                    "closed_count": 0,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "generated_at": now,
                },
            )
            probation_50_trade_gate = _paper_contract_from_key(
                "v2:paper:probation_50_trade_gate",
                "probation_50_trade_gate",
                {
                    "schema_version": "positive_edge_probation_trade_gate_v1",
                    "status": "PROBATION_50_TRADE_GATE_WAITING_OR_BLOCKED",
                    "available": False,
                    "closed_count": 0,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "generated_at": now,
                },
            )
            probation_candidate_count = _integer(
                positive_edge_probation_runtime_status.get("current_candidate_count")
            ) or 0
            probation_5_display_status = probation_gate_display_status(
                probation_5_trade_gate
            )
            positive_edge_probation_summary = {
                "status": positive_edge_probation_runtime_status.get("status"),
                "policy_enabled": positive_edge_probation_policy.get("enabled") is True,
                "current_candidate_count": probation_candidate_count,
                "current_accepted_count": _integer(
                    positive_edge_probation_runtime_status.get("current_accepted_count")
                )
                or 0,
                "closed_probation_trade_count": _integer(
                    positive_edge_probation_runtime_status.get(
                        "closed_probation_trade_count"
                    )
                )
                or 0,
                "next_gate": positive_edge_probation_runtime_status.get("next_gate"),
                "probation_5_trade_gate_status": probation_5_display_status,
                "probation_20_trade_gate_status": probation_20_trade_gate.get("status"),
                "probation_50_trade_gate_status": probation_50_trade_gate.get("status"),
                "supply_state": (
                    "NO_SAFE_TRADE_SUPPLY"
                    if probation_candidate_count <= 0
                    else "POSITIVE_EDGE_PROBATION_SUPPLY_AVAILABLE"
                ),
                "counts_as_final_a_plus": False,
                "counts_as_live_ready": False,
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            }
            advanced_indicator_summary = _advanced_indicator_runtime_summary(
                preemptive_matrix=preemptive_candidate_decision_matrix,
                preemptive_status=preemptive_edge_control_status,
                admission_status=paper_preemptive_admission_status,
            )
            adaptive_hedge_cross_margin = _adaptive_hedge_cross_margin_summary()
            provider_readiness = _provider_readiness_summary()
            runtime_admission_status = (
                trade_management_status.get("paper_runtime_admission_status")
                if isinstance(trade_management_status.get("paper_runtime_admission_status"), dict)
                else {}
            )
            runtime_cost_capture_status = (
                trade_management_status.get("paper_runtime_cost_capture_status")
                if isinstance(trade_management_status.get("paper_runtime_cost_capture_status"), dict)
                else {}
            )
            paper_entry_freeze = (
                trade_management_status.get("paper_entry_freeze")
                if isinstance(trade_management_status.get("paper_entry_freeze"), dict)
                else {}
            )

            def _first_integer(default: int, *values: Any) -> int:
                for value in values:
                    parsed = _integer(value)
                    if parsed is not None:
                        return int(parsed)
                return int(default)

            a_grade_gate_key = "v2:paper:a_grade_gate_burndown_status"
            try:
                a_grade_gate_raw = client.get(a_grade_gate_key)
            except Exception:
                a_grade_gate_raw = None
            a_grade_gate_status = _json_object_from_redis_raw(a_grade_gate_raw)
            a_grade_gate_source = f"redis:{a_grade_gate_key}" if a_grade_gate_status else ""
            if not a_grade_gate_status:
                fallback_a_grade_gate = trade_management_status.get("paper_a_grade_gate_burndown_status")
                if isinstance(fallback_a_grade_gate, dict):
                    a_grade_gate_status = fallback_a_grade_gate
                    a_grade_gate_source = (
                        "redis:v2:paper:trade_management:status.paper_a_grade_gate_burndown_status"
                    )
            if a_grade_gate_status:
                a_grade_gate_status = _compact_paper_runtime_contract(a_grade_gate_status)
                a_grade_gate_status.setdefault("source", a_grade_gate_source)
                a_grade_gate_status.setdefault("available", True)
                a_grade_rows = _first_integer(
                    0,
                    a_grade_gate_status.get("A_grade_rows"),
                    a_grade_gate_status.get("a_grade_rows"),
                )
                near_a_grade_rows = _first_integer(
                    0,
                    a_grade_gate_status.get("near_A_grade_rows"),
                    a_grade_gate_status.get("near_a_grade_rows"),
                )
                source_tier_a_grade_execution_rows = _first_integer(
                    0,
                    a_grade_gate_status.get("source_tier_a_grade_execution_rows"),
                    a_grade_gate_status.get("source_tier_A_grade_execution_rows"),
                )
                a_grade_gate_status["A_grade_rows"] = a_grade_rows
                a_grade_gate_status["a_grade_rows"] = a_grade_rows
                a_grade_gate_status["near_A_grade_rows"] = near_a_grade_rows
                a_grade_gate_status["near_a_grade_rows"] = near_a_grade_rows
                a_grade_gate_status["source_tier_a_grade_execution_rows"] = (
                    source_tier_a_grade_execution_rows
                )
                guardian_gate_status = (
                    a_grade_gate_status.get("guardian_gate_status")
                    if isinstance(a_grade_gate_status.get("guardian_gate_status"), dict)
                    else {}
                )
                if guardian_gate_status:
                    failure_reasons = guardian_gate_status.get("failure_reasons")
                    a_grade_gate_status.setdefault("guardian_status", guardian_gate_status.get("status"))
                    a_grade_gate_status.setdefault(
                        "guardian_new_entries_allowed",
                        guardian_gate_status.get("a_grade_new_entries_allowed"),
                    )
                    a_grade_gate_status.setdefault(
                        "guardian_block_all_new_a_grade_entries",
                        guardian_gate_status.get("block_all_new_a_grade_entries"),
                    )
                    a_grade_gate_status.setdefault(
                        "guardian_failure_reason_count",
                        len(failure_reasons) if isinstance(failure_reasons, list) else 0,
                    )
                pass_conditions = a_grade_gate_status.get("pass_conditions")
                if not isinstance(pass_conditions, dict):
                    root_cause_counts = a_grade_gate_status.get("root_cause_counts")
                    root_cause_counts = (
                        root_cause_counts if isinstance(root_cause_counts, dict) else {}
                    )
                    a_grade_gate_status["pass_conditions"] = {
                        "A_grade_rows_gt_zero": a_grade_rows > 0,
                        "source_owned_zero_supply_root_cause_mapped": bool(
                            a_grade_gate_status.get("closest_gap_reason")
                            or root_cause_counts
                        ),
                        "a_grade_new_entries_allowed": (
                            a_grade_gate_status.get("guardian_new_entries_allowed")
                            is True
                        ),
                        "ready_allowed": False,
                    }
            else:
                a_grade_rows = 0
                near_a_grade_rows = 0
                source_tier_a_grade_execution_rows = 0
                a_grade_gate_status = {
                    "schema_version": "paper_a_grade_gate_burndown_status_v1",
                    "status": "A_GRADE_GATE_BURNDOWN_STATUS_UNAVAILABLE",
                    "source": f"redis:{a_grade_gate_key}",
                    "available": False,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "A_grade_rows": 0,
                    "a_grade_rows": 0,
                    "near_A_grade_rows": 0,
                    "near_a_grade_rows": 0,
                    "source_tier_a_grade_execution_rows": 0,
                    "predicate_counts": {},
                    "generated_at": now,
                }
            a_grade_predicates = (
                a_grade_gate_status.get("predicate_counts")
                if isinstance(a_grade_gate_status.get("predicate_counts"), dict)
                else {}
            )

            intent_rows = _first_integer(
                0,
                runtime_cost_capture_status.get("paper_intent_rows"),
                runtime_admission_status.get("intents_built"),
                a_grade_gate_status.get("prediction_rows"),
            )
            order_applicable_rows = _first_integer(
                intent_rows,
                runtime_cost_capture_status.get("order_cost_applicable_rows"),
            )
            production_grade_cost_rows = _first_integer(
                0,
                runtime_cost_capture_status.get("production_grade_cost_rows"),
                a_grade_gate_status.get("production_grade_cost_rows"),
                a_grade_predicates.get("production_grade_cost_rows"),
            )
            production_grade_cost_order_applicable_rows = _first_integer(
                min(production_grade_cost_rows, order_applicable_rows),
                runtime_cost_capture_status.get("production_grade_cost_order_applicable_rows"),
            )
            no_order_explained_rows = _first_integer(
                0, runtime_cost_capture_status.get("no_order_explained_rows")
            )
            unexplained_missing_cost_rows = _first_integer(
                0, runtime_cost_capture_status.get("unexplained_missing_cost_rows")
            )
            no_order_missing_cost_rows = _first_integer(
                0, runtime_cost_capture_status.get("no_order_missing_cost_rows")
            )
            paper_fill_allowed_rows = _first_integer(
                0,
                runtime_cost_capture_status.get("paper_fill_allowed_rows"),
                runtime_admission_status.get("accepted_count"),
            )
            routes_to_live_rows = _first_integer(
                0, runtime_cost_capture_status.get("routes_to_live_rows")
            )
            places_real_order_rows = _first_integer(
                0, runtime_cost_capture_status.get("places_real_order_rows")
            )
            total_row_cost_coverage = _float(
                runtime_cost_capture_status.get("production_grade_cost_total_row_coverage")
            )
            if total_row_cost_coverage is None:
                total_row_cost_coverage = production_grade_cost_rows / intent_rows if intent_rows else 0.0
            cost_coverage = _float(runtime_cost_capture_status.get("production_grade_cost_coverage"))
            if cost_coverage is None:
                cost_coverage = (
                    production_grade_cost_order_applicable_rows / order_applicable_rows
                    if order_applicable_rows
                    else 0.0
                )
            cost_coverage_basis = str(
                runtime_cost_capture_status.get("production_grade_cost_coverage_basis") or ""
            )
            if (
                order_applicable_rows == 0
                and intent_rows > 0
                and total_row_cost_coverage > cost_coverage
            ):
                cost_coverage = total_row_cost_coverage
                cost_coverage_basis = "all_intent_rows_no_order_applicable_api_repaired"
            if not cost_coverage_basis:
                cost_coverage_basis = (
                    "order_applicable_rows"
                    if order_applicable_rows
                    else "all_intent_rows_no_order_applicable"
                )

            latest_signal, latest_sig_ts = _latest_signal_from_bounded_keys(client)

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

            active_runtime_owner_key = "v2:paper:active_runtime_owner_status"
            try:
                active_runtime_owner_raw = client.get(active_runtime_owner_key)
            except Exception:
                active_runtime_owner_raw = None
            paper_active_runtime_owner_status = _json_object_from_redis_raw(
                active_runtime_owner_raw
            )
            if not paper_active_runtime_owner_status:
                fallback_active_owner = trade_management_status.get(
                    "paper_active_runtime_owner_status"
                )
                if isinstance(fallback_active_owner, dict):
                    paper_active_runtime_owner_status = fallback_active_owner
            if not paper_active_runtime_owner_status:
                fallback_active_owner = hb.get("paper_active_runtime_owner_status")
                if isinstance(fallback_active_owner, dict):
                    paper_active_runtime_owner_status = fallback_active_owner
            if paper_active_runtime_owner_status:
                paper_active_runtime_owner_status = _compact_paper_runtime_contract(
                    paper_active_runtime_owner_status
                )
                paper_active_runtime_owner_status.setdefault(
                    "source", f"redis:{active_runtime_owner_key}"
                )
                paper_active_runtime_owner_status.setdefault("available", True)
            else:
                paper_active_runtime_owner_status = {
                    "schema_version": "paper_active_runtime_owner_status_v1",
                    "status": "PAPER_ACTIVE_RUNTIME_OWNER_STATUS_UNAVAILABLE",
                    "source": f"redis:{active_runtime_owner_key}",
                    "available": False,
                    "active_new_entry_owner": "UNKNOWN",
                    "canonical_paper_writer_count": 0,
                    "forbidden_entry_process_count": None,
                    "duplicate_paper_writer_count": None,
                    "paper_online_runtime_active": None,
                    "paper_online_runtime_enabled": None,
                    "old_policy_new_entry_writer_active": None,
                    "toy_momentum_entry_writer_active": None,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "generated_at": now,
                }
            active_runtime_owner_contract_status = str(
                paper_active_runtime_owner_status.get("status") or ""
            )

            policy_owner_handoff_key = "v2:paper:policy_owner_handoff_runtime_proof"
            try:
                policy_owner_handoff_raw = client.get(policy_owner_handoff_key)
            except Exception:
                policy_owner_handoff_raw = None
            paper_policy_owner_handoff_runtime_proof = _json_object_from_redis_raw(
                policy_owner_handoff_raw
            )
            if not paper_policy_owner_handoff_runtime_proof:
                fallback_policy_owner_handoff = trade_management_status.get(
                    "paper_policy_owner_handoff_runtime_proof"
                )
                if isinstance(fallback_policy_owner_handoff, dict):
                    paper_policy_owner_handoff_runtime_proof = fallback_policy_owner_handoff
            if not paper_policy_owner_handoff_runtime_proof:
                fallback_policy_owner_handoff = hb.get(
                    "paper_policy_owner_handoff_runtime_proof"
                )
                if isinstance(fallback_policy_owner_handoff, dict):
                    paper_policy_owner_handoff_runtime_proof = fallback_policy_owner_handoff
            if paper_policy_owner_handoff_runtime_proof:
                paper_policy_owner_handoff_runtime_proof = _compact_paper_runtime_contract(
                    paper_policy_owner_handoff_runtime_proof
                )
                paper_policy_owner_handoff_runtime_proof.setdefault(
                    "source", f"redis:{policy_owner_handoff_key}"
                )
                paper_policy_owner_handoff_runtime_proof.setdefault("available", True)
            else:
                paper_policy_owner_handoff_runtime_proof = {
                    "schema_version": "paper_policy_owner_handoff_runtime_proof_v1",
                    "status": "PAPER_POLICY_OWNER_HANDOFF_RUNTIME_PROOF_UNAVAILABLE",
                    "source": f"redis:{policy_owner_handoff_key}",
                    "available": False,
                    "paper_new_entry_owner": "UNKNOWN",
                    "new_old_policy_entry_count": None,
                    "new_challenger_candidate_count": 0,
                    "new_challenger_intent_count": 0,
                    "challenger_identity_preserved_to_outcome": False,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "generated_at": now,
                }
            policy_owner_handoff_status = str(
                paper_policy_owner_handoff_runtime_proof.get("status") or ""
            )

            b_grade_canary_supply_key = "v2:paper:b_grade_canary_supply_status"
            try:
                b_grade_canary_supply_raw = client.get(b_grade_canary_supply_key)
            except Exception:
                b_grade_canary_supply_raw = None
            b_grade_canary_supply_status = _json_object_from_redis_raw(b_grade_canary_supply_raw)
            if b_grade_canary_supply_status:
                b_grade_canary_supply_status = _compact_paper_runtime_contract(
                    b_grade_canary_supply_status
                )
                b_grade_canary_supply_status.setdefault("source", f"redis:{b_grade_canary_supply_key}")
                b_grade_canary_supply_status.setdefault("available", True)
            else:
                b_grade_canary_supply_status = {
                    "schema_version": "paper_b_grade_canary_supply_status_v1",
                    "status": "B_GRADE_CANARY_SUPPLY_STATUS_UNAVAILABLE",
                    "source": f"redis:{b_grade_canary_supply_key}",
                    "available": False,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "counts_as_a_grade_evidence": False,
                    "canary_candidates": 0,
                    "canary_intents": 0,
                    "canary_pending_rows": 0,
                    "root_cause_counts": {},
                    "generated_at": now,
                }
            b_grade_canary_status = str(b_grade_canary_supply_status.get("status") or "")

            trainer_quality_key = "v2:paper:trainer_model_quality_runtime_status"
            try:
                trainer_quality_raw = client.get(trainer_quality_key)
            except Exception:
                trainer_quality_raw = None
            paper_trainer_model_quality_runtime_status = _json_object_from_redis_raw(
                trainer_quality_raw
            )
            if not paper_trainer_model_quality_runtime_status:
                fallback_trainer_quality = trade_management_status.get(
                    "paper_trainer_model_quality_runtime_status"
                )
                if isinstance(fallback_trainer_quality, dict):
                    paper_trainer_model_quality_runtime_status = fallback_trainer_quality
            if not paper_trainer_model_quality_runtime_status:
                fallback_trainer_quality = hb.get("paper_trainer_model_quality_runtime_status")
                if isinstance(fallback_trainer_quality, dict):
                    paper_trainer_model_quality_runtime_status = fallback_trainer_quality
            if paper_trainer_model_quality_runtime_status:
                paper_trainer_model_quality_runtime_status = _compact_paper_runtime_contract(
                    paper_trainer_model_quality_runtime_status
                )
                paper_trainer_model_quality_runtime_status.setdefault(
                    "source", f"redis:{trainer_quality_key}"
                )
                paper_trainer_model_quality_runtime_status.setdefault("available", True)
            else:
                paper_trainer_model_quality_runtime_status = {
                    "schema_version": "paper_trainer_model_quality_runtime_status_v1",
                    "status": "TRAINER_MODEL_QUALITY_RUNTIME_STATUS_UNAVAILABLE",
                    "source": f"redis:{trainer_quality_key}",
                    "available": False,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "counts_as_a_grade_evidence": False,
                    "a_grade_promotion_allowed": False,
                    "weights_update": False,
                    "quality_metrics_current": False,
                    "trusted_rows_loaded": 0,
                    "optimizer_steps_last_hour": 0,
                    "parameter_hash_changed": False,
                    "checkpoint_written": False,
                    "checkpoint_reload_verified": False,
                    "after_cost_expectancy_bps": None,
                    "generated_at": now,
                }

            churn_equity_bleed_key = "v2:paper:churn_equity_bleed_governor_status"
            try:
                churn_equity_bleed_raw = client.get(churn_equity_bleed_key)
            except Exception:
                churn_equity_bleed_raw = None
            paper_churn_equity_bleed_governor_status = _json_object_from_redis_raw(
                churn_equity_bleed_raw
            )
            if not paper_churn_equity_bleed_governor_status:
                fallback_churn = trade_management_status.get(
                    "paper_churn_equity_bleed_governor_status"
                )
                if isinstance(fallback_churn, dict):
                    paper_churn_equity_bleed_governor_status = fallback_churn
            if not paper_churn_equity_bleed_governor_status:
                fallback_churn = hb.get("paper_churn_equity_bleed_governor_status")
                if isinstance(fallback_churn, dict):
                    paper_churn_equity_bleed_governor_status = fallback_churn
            if paper_churn_equity_bleed_governor_status:
                paper_churn_equity_bleed_governor_status = (
                    _compact_paper_runtime_contract(
                        paper_churn_equity_bleed_governor_status
                    )
                )
                paper_churn_equity_bleed_governor_status.setdefault(
                    "source", f"redis:{churn_equity_bleed_key}"
                )
                paper_churn_equity_bleed_governor_status.setdefault("available", True)
            else:
                paper_churn_equity_bleed_governor_status = {
                    "schema_version": "paper_churn_equity_bleed_governor_status_v1",
                    "status": "PAPER_CHURN_EQUITY_BLEED_GOVERNOR_STATUS_UNAVAILABLE",
                    "source": f"redis:{churn_equity_bleed_key}",
                    "available": False,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "duplicate_new_entries": None,
                    "same_candle_reentry_unexplained": None,
                    "cost_drag_within_envelope": None,
                    "economic_trade_count_reconciles": None,
                    "generated_at": now,
                }

            forward_canary_key = "v2:paper:forward_canary_evidence_status"
            try:
                forward_canary_raw = client.get(forward_canary_key)
            except Exception:
                forward_canary_raw = None
            paper_forward_canary_evidence_status = _json_object_from_redis_raw(forward_canary_raw)
            if not paper_forward_canary_evidence_status:
                fallback_forward_canary = trade_management_status.get(
                    "paper_forward_canary_evidence_status"
                )
                if isinstance(fallback_forward_canary, dict):
                    paper_forward_canary_evidence_status = fallback_forward_canary
            if not paper_forward_canary_evidence_status:
                fallback_forward_canary = hb.get("paper_forward_canary_evidence_status")
                if isinstance(fallback_forward_canary, dict):
                    paper_forward_canary_evidence_status = fallback_forward_canary
            if paper_forward_canary_evidence_status:
                paper_forward_canary_evidence_status = _compact_paper_runtime_contract(
                    paper_forward_canary_evidence_status
                )
                paper_forward_canary_evidence_status.setdefault("source", f"redis:{forward_canary_key}")
                paper_forward_canary_evidence_status.setdefault("available", True)
                required_symbol_count = _first_integer(
                    0,
                    paper_forward_canary_evidence_status.get("required_symbol_count"),
                    paper_forward_canary_evidence_status.get("required_initial_symbols"),
                    paper_forward_canary_evidence_status.get("minimum_required_symbol_count"),
                )
                if required_symbol_count:
                    paper_forward_canary_evidence_status["required_symbol_count"] = (
                        required_symbol_count
                    )
                    paper_forward_canary_evidence_status["required_initial_symbols"] = (
                        required_symbol_count
                    )
                    paper_forward_canary_evidence_status[
                        "minimum_required_symbol_count"
                    ] = required_symbol_count
                valid_side_counts = paper_forward_canary_evidence_status.get(
                    "valid_side_counts"
                )
                side_counts = paper_forward_canary_evidence_status.get("side_counts")
                if not isinstance(side_counts, dict) and isinstance(valid_side_counts, dict):
                    paper_forward_canary_evidence_status["side_counts"] = valid_side_counts
                elif not isinstance(valid_side_counts, dict) and isinstance(side_counts, dict):
                    paper_forward_canary_evidence_status["valid_side_counts"] = side_counts
                shortfalls = paper_forward_canary_evidence_status.get(
                    "forward_canary_shortfalls"
                )
                if not isinstance(shortfalls, dict):
                    required_outcomes = _first_integer(
                        0,
                        paper_forward_canary_evidence_status.get(
                            "required_forward_canary_economic_outcomes"
                        ),
                    )
                    valid_outcomes = _first_integer(
                        0,
                        paper_forward_canary_evidence_status.get(
                            "valid_forward_canary_economic_outcomes"
                        ),
                        paper_forward_canary_evidence_status.get(
                            "post_cutover_valid_forward_canary_economic_outcomes"
                        ),
                    )
                    valid_symbols = _first_integer(
                        0,
                        paper_forward_canary_evidence_status.get("valid_symbol_count"),
                    )
                    counts = paper_forward_canary_evidence_status.get(
                        "valid_side_counts"
                    )
                    counts = counts if isinstance(counts, dict) else {}
                    paper_forward_canary_evidence_status["forward_canary_shortfalls"] = {
                        "valid_forward_canary_economic_outcomes": max(
                            0, required_outcomes - valid_outcomes
                        ),
                        "valid_symbol_count": max(
                            0, required_symbol_count - valid_symbols
                        ),
                        "long_outcomes": max(0, 1 - _first_integer(0, counts.get("long"))),
                        "short_outcomes": max(0, 1 - _first_integer(0, counts.get("short"))),
                    }
            else:
                paper_forward_canary_evidence_status = {
                    "schema_version": "paper_forward_canary_evidence_status_v1",
                    "status": "FORWARD_CANARY_EVIDENCE_STATUS_UNAVAILABLE",
                    "source": f"redis:{forward_canary_key}",
                    "available": False,
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                    "counts_as_a_grade_evidence": False,
                    "valid_forward_canary_economic_outcomes": 0,
                    "post_cutover_valid_forward_canary_economic_outcomes": 0,
                    "generated_at": now,
                }
            forward_canary_status = str(
                paper_forward_canary_evidence_status.get("status") or ""
            )
            trajectory_rel = (
                "operator_runtime/v2_continuous_edge_guardian/latest/"
                "one_thousand_x_trajectory_status.json"
            )
            one_thousand_x_trajectory_status, _trajectory_source = _read_json(
                trajectory_rel
            )
            if isinstance(one_thousand_x_trajectory_status, dict):
                one_thousand_x_trajectory_status = dict(
                    one_thousand_x_trajectory_status
                )
                one_thousand_x_trajectory_status.setdefault("source", trajectory_rel)
                one_thousand_x_trajectory_status.setdefault("available", True)
                one_thousand_x_trajectory_status.setdefault(
                    "guaranteed_profit_claim", False
                )
                one_thousand_x_trajectory_status.setdefault(
                    "leverage_increase_allowed_because_behind", False
                )
            else:
                one_thousand_x_trajectory_status = {
                    "schema_version": "one_thousand_x_trajectory_status_v1",
                    "status": "ONE_THOUSAND_X_TRAJECTORY_STATUS_UNAVAILABLE",
                    "current_status": "INSUFFICIENT_EVIDENCE",
                    "source": trajectory_rel,
                    "available": False,
                    "guaranteed_profit_claim": False,
                    "leverage_increase_allowed_because_behind": False,
                    "generated_at": now,
                }
            trajectory_status = str(
                one_thousand_x_trajectory_status.get("trajectory_status")
                or one_thousand_x_trajectory_status.get("current_status")
                or one_thousand_x_trajectory_status.get("status")
                or ""
            )

            runtime_state = "PAPER_RUNTIME_ONLINE_ACTIVE" if heartbeat_fresh else "PAPER_RUNTIME_HEARTBEAT_STALE"
            blockers = [
                {
                    "id": "LIVE_GATE_BLOCKED_HUMAN_ONLY",
                    "severity": "expected_safety_gate",
                    "detail": "Live order routing remains blocked_human_only.",
                },
            ]
            if (
                active_runtime_owner_contract_status
                == "PAPER_ACTIVE_RUNTIME_OWNER_STATUS_UNAVAILABLE"
            ):
                blockers.append(
                    {
                        "id": "PAPER_ACTIVE_RUNTIME_OWNER_STATUS_UNAVAILABLE",
                        "severity": "missing_runtime_contract",
                        "detail": "Active paper runtime has not published the process/service owner validation contract.",
                        "source": f"redis:{active_runtime_owner_key}",
                    }
                )
            elif (
                active_runtime_owner_contract_status
                != "PASS_ACTIVE_RUNTIME_OWNER_VALIDATION"
            ):
                blockers.append(
                    {
                        "id": "PAPER_ACTIVE_RUNTIME_OWNER_VALIDATION_BLOCKED",
                        "severity": "runtime_blocker",
                        "detail": "Active process/service validation does not prove a single canonical paper writer with forbidden legacy paper writers absent.",
                        "source": paper_active_runtime_owner_status.get("source")
                        or f"redis:{active_runtime_owner_key}",
                        "status": active_runtime_owner_contract_status,
                        "canonical_paper_writer_count": (
                            paper_active_runtime_owner_status.get(
                                "canonical_paper_writer_count"
                            )
                        ),
                        "forbidden_entry_process_count": (
                            paper_active_runtime_owner_status.get(
                                "forbidden_entry_process_count"
                            )
                        ),
                        "duplicate_paper_writer_count": (
                            paper_active_runtime_owner_status.get(
                                "duplicate_paper_writer_count"
                            )
                        ),
                    }
                )
            if (
                policy_owner_handoff_status
                == "PAPER_POLICY_OWNER_HANDOFF_RUNTIME_PROOF_UNAVAILABLE"
            ):
                blockers.append(
                    {
                        "id": "PAPER_POLICY_OWNER_HANDOFF_RUNTIME_PROOF_UNAVAILABLE",
                        "severity": "missing_runtime_contract",
                        "detail": "Active paper runtime has not published the challenger handoff proof.",
                        "source": f"redis:{policy_owner_handoff_key}",
                    }
                )
            elif (
                policy_owner_handoff_status
                != "PASSED_PAPER_POLICY_OWNER_HANDOFF_RUNTIME_PROOF"
            ):
                blockers.append(
                    {
                        "id": "PAPER_POLICY_OWNER_HANDOFF_RUNTIME_PROOF_BLOCKED",
                        "severity": "runtime_blocker",
                        "detail": "Active paper runtime does not prove old policy opens are blocked and challenger identity is preserved.",
                        "source": (
                            paper_policy_owner_handoff_runtime_proof.get("source")
                            or f"redis:{policy_owner_handoff_key}"
                        ),
                        "status": policy_owner_handoff_status,
                        "new_old_policy_entry_count": (
                            paper_policy_owner_handoff_runtime_proof.get(
                                "new_old_policy_entry_count"
                            )
                        ),
                        "new_challenger_candidate_count": (
                            paper_policy_owner_handoff_runtime_proof.get(
                                "new_challenger_candidate_count"
                            )
                        ),
                        "new_challenger_intent_count": (
                            paper_policy_owner_handoff_runtime_proof.get(
                                "new_challenger_intent_count"
                            )
                        ),
                    }
                )
            if b_grade_canary_status == "BLOCKED_ZERO_B_GRADE_CANARY_SUPPLY":
                blockers.append(
                    {
                        "id": "B_GRADE_CANARY_SUPPLY_ZERO",
                        "severity": "runtime_blocker",
                        "detail": "Active paper runtime reports zero B-grade canary candidate, intent, and pending rows.",
                        "source": f"redis:{b_grade_canary_supply_key}",
                        "root_cause_counts": b_grade_canary_supply_status.get("root_cause_counts") or {},
                    }
                )
            elif b_grade_canary_status == "B_GRADE_CANARY_SUPPLY_STATUS_UNAVAILABLE":
                blockers.append(
                    {
                        "id": "B_GRADE_CANARY_SUPPLY_STATUS_UNAVAILABLE",
                        "severity": "missing_runtime_contract",
                        "detail": "Active paper runtime has not published the B-grade canary supply contract.",
                        "source": f"redis:{b_grade_canary_supply_key}",
                    }
                )

            if forward_canary_status == "FORWARD_CANARY_EVIDENCE_STATUS_UNAVAILABLE":
                blockers.append(
                    {
                        "id": "FORWARD_CANARY_EVIDENCE_STATUS_UNAVAILABLE",
                        "severity": "missing_runtime_contract",
                        "detail": "Active paper runtime has not published the forward canary evidence contract.",
                        "source": f"redis:{forward_canary_key}",
                    }
                )
            elif forward_canary_status != "FORWARD_CANARY_EVIDENCE_REQUIREMENTS_MET":
                blockers.append(
                    {
                        "id": "FORWARD_CANARY_EVIDENCE_NOT_READY",
                        "severity": "runtime_blocker",
                        "detail": "Post-cutover challenger paper canary economic outcomes or symbol coverage are not sufficient for A-grade readiness.",
                        "source": paper_forward_canary_evidence_status.get("source")
                        or f"redis:{forward_canary_key}",
                        "status": forward_canary_status,
                        "valid_forward_canary_economic_outcomes": (
                            paper_forward_canary_evidence_status.get(
                                "valid_forward_canary_economic_outcomes"
                            )
                        ),
                        "post_cutover_valid_forward_canary_economic_outcomes": (
                            paper_forward_canary_evidence_status.get(
                                "post_cutover_valid_forward_canary_economic_outcomes"
                            )
                        ),
                        "required_forward_canary_economic_outcomes": (
                            paper_forward_canary_evidence_status.get(
                                "required_forward_canary_economic_outcomes"
                            )
                        ),
                        "valid_symbol_count": paper_forward_canary_evidence_status.get(
                            "valid_symbol_count"
                        ),
                        "valid_side_counts": paper_forward_canary_evidence_status.get(
                            "valid_side_counts"
                        ),
                        "required_symbol_count": paper_forward_canary_evidence_status.get(
                            "required_symbol_count"
                        ),
                        "required_initial_symbols": (
                            paper_forward_canary_evidence_status.get(
                                "required_initial_symbols"
                            )
                        ),
                        "forward_canary_shortfalls": (
                            paper_forward_canary_evidence_status.get(
                                "forward_canary_shortfalls"
                            )
                        ),
                        "failed_forward_canary_blocker_details": (
                            paper_forward_canary_evidence_status.get(
                                "failed_forward_canary_blocker_details"
                            )
                        ),
                        "production_grade_cost_coverage": (
                            paper_forward_canary_evidence_status.get(
                                "production_grade_cost_coverage"
                            )
                        ),
                        "pass_conditions": paper_forward_canary_evidence_status.get(
                            "pass_conditions"
                        )
                        or {},
                        "non_counting_reasons": (
                            paper_forward_canary_evidence_status.get(
                                "non_counting_reasons"
                            )
                            or {}
                        ),
                    }
                )
            if a_grade_gate_status.get("available") is True and a_grade_rows <= 0:
                blockers.append(
                    {
                        "id": "A_GRADE_SUPPLY_ZERO",
                        "severity": "runtime_blocker",
                        "detail": "Paper A-grade burndown reports zero A-grade rows; guardian/source-tier status remains authoritative.",
                        "source": a_grade_gate_status.get("source") or f"redis:{a_grade_gate_key}",
                        "status": a_grade_gate_status.get("status")
                        or "A_GRADE_GATE_STATUS_UNAVAILABLE",
                        "A_grade_rows": a_grade_rows,
                        "a_grade_rows": a_grade_rows,
                        "near_A_grade_rows": near_a_grade_rows,
                        "near_a_grade_rows": near_a_grade_rows,
                        "closest_gap_reason": a_grade_gate_status.get(
                            "closest_gap_reason"
                        ),
                        "predicate_counts": a_grade_gate_status.get(
                            "predicate_counts"
                        )
                        or {},
                        "root_cause_counts": a_grade_gate_status.get(
                            "root_cause_counts"
                        )
                        or {},
                        "dominant_current_runtime_reasons": a_grade_gate_status.get(
                            "dominant_current_runtime_reasons"
                        )
                        or {},
                        "source_rows": a_grade_gate_status.get("source_rows") or {},
                        "guardian_status": a_grade_gate_status.get("guardian_status"),
                        "guardian_new_entries_allowed": a_grade_gate_status.get(
                            "guardian_new_entries_allowed"
                        ),
                        "guardian_block_all_new_a_grade_entries": (
                            a_grade_gate_status.get(
                                "guardian_block_all_new_a_grade_entries"
                            )
                        ),
                        "guardian_failure_reason_count": a_grade_gate_status.get(
                            "guardian_failure_reason_count"
                        ),
                        "source_tier_a_grade_execution_rows": (
                            source_tier_a_grade_execution_rows
                        ),
                        "pass_conditions": a_grade_gate_status.get("pass_conditions")
                        or {},
                    }
                )
            if trajectory_status != "ON_TRACK_90D_A_PLUS_EVIDENCE":
                blockers.append(
                    {
                        "id": "ONE_THOUSAND_X_TRAJECTORY_NOT_READY",
                        "severity": "runtime_blocker",
                        "detail": "1000x trajectory is not proven; status must remain honest and cannot imply live readiness.",
                        "source": one_thousand_x_trajectory_status.get("source")
                        or trajectory_rel,
                        "status": trajectory_status
                        or "ONE_THOUSAND_X_TRAJECTORY_STATUS_UNAVAILABLE",
                        "blocker": one_thousand_x_trajectory_status.get("blocker"),
                        "target_multiple": one_thousand_x_trajectory_status.get(
                            "target_multiple"
                        ),
                        "target_horizon_days": one_thousand_x_trajectory_status.get(
                            "target_horizon_days"
                        ),
                        "required_daily_return_pct": (
                            one_thousand_x_trajectory_status.get(
                                "required_daily_return_pct"
                            )
                        ),
                        "required_daily_geometric_return": (
                            one_thousand_x_trajectory_status.get(
                                "required_daily_geometric_return"
                            )
                        ),
                        "required_monthly_geometric_return": (
                            one_thousand_x_trajectory_status.get(
                                "required_monthly_geometric_return"
                            )
                        ),
                        "actual_1d_return": one_thousand_x_trajectory_status.get(
                            "actual_1d_return"
                        ),
                        "actual_7d_return": one_thousand_x_trajectory_status.get(
                            "actual_7d_return"
                        ),
                        "actual_30d_return": one_thousand_x_trajectory_status.get(
                            "actual_30d_return"
                        ),
                        "drawdown_adjusted_growth_rate": (
                            one_thousand_x_trajectory_status.get(
                                "drawdown_adjusted_growth_rate"
                            )
                        ),
                        "lower_confidence_bound_growth_rate": (
                            one_thousand_x_trajectory_status.get(
                                "lower_confidence_bound_growth_rate"
                            )
                        ),
                        "days_ahead_or_behind_target": (
                            one_thousand_x_trajectory_status.get(
                                "days_ahead_or_behind_target"
                            )
                        ),
                        "projection_days": one_thousand_x_trajectory_status.get(
                            "projection_days"
                        ),
                        "A_plus_rows": one_thousand_x_trajectory_status.get(
                            "A_plus_rows"
                        ),
                        "B_grade_rows": one_thousand_x_trajectory_status.get(
                            "B_grade_rows"
                        ),
                        "current_A_plus_daily_return_pct": (
                            one_thousand_x_trajectory_status.get(
                                "current_A_plus_daily_return_pct"
                            )
                        ),
                        "current_B_grade_daily_return_pct": (
                            one_thousand_x_trajectory_status.get(
                                "current_B_grade_daily_return_pct"
                            )
                        ),
                        "required_operator_text": (
                            one_thousand_x_trajectory_status.get(
                                "required_operator_text"
                            )
                            or []
                        ),
                        "required_edge": one_thousand_x_trajectory_status.get(
                            "required_edge"
                        ),
                        "required_capital": one_thousand_x_trajectory_status.get(
                            "required_capital"
                        ),
                        "missing_trajectory_evidence_fields": (
                            one_thousand_x_trajectory_status.get(
                                "missing_trajectory_evidence_fields"
                            )
                            or []
                        ),
                        "guaranteed_profit_claim": (
                            one_thousand_x_trajectory_status.get(
                                "guaranteed_profit_claim"
                            )
                            is True
                        ),
                        "leverage_increase_allowed_because_behind": (
                            one_thousand_x_trajectory_status.get(
                                "leverage_increase_allowed_because_behind"
                            )
                            is True
                        ),
                    }
                )

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
                # A+ goal Phase 12: session performance / freeze / A+ gate /
                # trainer learning / real-trader readiness truth for the web.
                **_paper_a_plus_runtime_truth_block(client),
                "preemptive_edge_control": {
                    "status": (
                        "PREEMPTIVE_EDGE_CONTROL_ACTIVE"
                        if preemptive_edge_control_status.get("available") is True
                        else "PREEMPTIVE_EDGE_CONTROL_NOT_YET_PUBLISHED"
                    ),
                    "decision_counts": (
                        preemptive_edge_control_status.get("decision_counts") or {}
                    ),
                    "action_counts": (
                        preemptive_edge_control_status.get("action_counts") or {}
                    ),
                    "preemptive_decision_id": first_preemptive_sample.get(
                        "preemptive_decision_id"
                    ),
                    "preemptive_action": first_preemptive_sample.get(
                        "preemptive_action"
                    ),
                    "preemptive_allowed": (
                        first_preemptive_sample.get("preemptive_allowed") is True
                    ),
                    "preemptive_block_reasons": (
                        first_preemptive_sample.get("preemptive_block_reasons")
                        or first_preemptive_sample.get("preemptive_decision_reasons")
                        or []
                    ),
                    "pre_trade_expected_net_pnl_usd": (
                        first_preemptive_sample.get("pre_trade_expected_net_pnl_usd")
                    ),
                    "pre_trade_loss_probability": (
                        first_preemptive_sample.get("pre_trade_loss_probability")
                    ),
                    "guardian_new_entries_allowed": (
                        first_preemptive_sample.get("guardian_new_entries_allowed")
                        is True
                    ),
                    "continuous_edge_guardian_status": (
                        first_preemptive_sample.get("continuous_edge_guardian_status")
                    ),
                    "reduce_size_guardian_approved": (
                        first_preemptive_sample.get("reduce_size_guardian_approved")
                        is True
                    ),
                    "candidate_count": preemptive_edge_control_status.get(
                        "candidate_count"
                    ),
                    "accepted_count": preemptive_edge_control_status.get(
                        "accepted_count"
                    ),
                    "hard_fail": preemptive_edge_control_status.get("hard_fail") is True,
                    "advanced_indicators": advanced_indicator_summary,
                    "advanced_indicator_status": advanced_indicator_summary.get("status"),
                    "advanced_indicator_block_reason_counts": (
                        advanced_indicator_summary.get("block_reason_counts") or {}
                    ),
                    "advanced_indicator_caution_reason_counts": (
                        advanced_indicator_summary.get("caution_reason_counts") or {}
                    ),
                    "positive_edge_probation_status": (
                        positive_edge_probation_summary.get("status")
                    ),
                    "positive_edge_probation_supply_state": (
                        positive_edge_probation_summary.get("supply_state")
                    ),
                    "positive_edge_probation_candidates": (
                        positive_edge_probation_summary.get("current_candidate_count")
                    ),
                    "positive_edge_probation_accepted": (
                        positive_edge_probation_summary.get("current_accepted_count")
                    ),
                    "closed_probation_trade_count": (
                        positive_edge_probation_summary.get("closed_probation_trade_count")
                    ),
                    "probation_5_trade_gate_status": (
                        positive_edge_probation_summary.get("probation_5_trade_gate_status")
                    ),
                    "probation_counts_as_final_a_plus": False,
                    "probation_counts_as_live_ready": False,
                    "why_trade_was_prevented": (
                        paper_preemptive_admission_status.get("prevention_reasons")
                        or paper_preemptive_admission_status.get(
                            "top_rejection_reasons"
                        )
                        or []
                    ),
                    "governor_auto_action": (
                        "halt_new_entries"
                        if paper_entry_freeze.get("new_entries_allowed") is False
                        else "evaluate_preemptive_candidate"
                    ),
                    "next_remediation": (
                        "Wait for governor clearance and evaluate only post-patch closes"
                        if paper_entry_freeze.get("new_entries_allowed") is False
                        else "Observe accepted rows for preemptive decision compliance"
                    ),
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                },
                "preemptive_edge_control_status": preemptive_edge_control_status,
                "preemptive_candidate_decision_matrix": (
                    preemptive_candidate_decision_matrix
                ),
                "advanced_indicators": advanced_indicator_summary,
                "adaptive_hedge_cross_margin": adaptive_hedge_cross_margin,
                "provider_readiness": provider_readiness,
                "hedge_cross_margin": adaptive_hedge_cross_margin,
                "providers": provider_readiness,
                "paper_preemptive_admission_status": paper_preemptive_admission_status,
                "paper_no_bad_entry_runtime_status": paper_no_bad_entry_runtime_status,
                "positive_edge_probation": positive_edge_probation_summary,
                "positive_edge_probation_policy": positive_edge_probation_policy,
                "positive_edge_probation_runtime_status": (
                    positive_edge_probation_runtime_status
                ),
                "probation_5_trade_gate": probation_5_trade_gate,
                "probation_20_trade_gate": probation_20_trade_gate,
                "probation_50_trade_gate": probation_50_trade_gate,
                "account_scope": "PAPER_SIM_ACCOUNT",
                "source_type": "paper_runtime_redis_live",
                "paper_or_live": "paper",
                "contains_simulated_positions": True,
                "contains_live_positions": False,
                "contains_quarantined_positions": False,
                "equity_trusted": False,
                "pnl_trusted": False,
                "reason_if_untrusted": "PAPER_RUNTIME_STATUS_IS_OPERATIONAL_HEALTH_NOT_PORTFOLIO_EQUITY_TRUTH",
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
                    "source": market_source,
                    "source_pointer": "v2:market:coinapi:ohlcv:heartbeat",
                    "generated_at": market_ts or now,
                    "last_event_at": market_ts or None,
                    "age_seconds": market_age_s,
                    "freshness_state": market_freshness_state,
                    "provider_current": coinapi_unusable_reason is None,
                    "provider_unusable_reason": coinapi_unusable_reason,
                    "errors": [coinapi_unusable_reason] if coinapi_unusable_reason else [],
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
                    "paper_only": hb.get("paper_only"),
                    "routes_to_live": hb.get("routes_to_live"),
                    "places_real_order": hb.get("places_real_order"),
                    "paper_entry_freeze": paper_entry_freeze,
                    "paper_new_entries_halted": (
                        paper_entry_freeze.get("paper_new_entries_halted") is True
                        or paper_entry_freeze.get("new_entries_allowed") is False
                    ),
                    "paper_owner_attribution_status": hb.get("paper_owner_attribution_status"),
                    "paper_active_runtime_owner_status": paper_active_runtime_owner_status,
                    "paper_policy_owner_handoff_runtime_proof": (
                        paper_policy_owner_handoff_runtime_proof
                    ),
                    "old_policy_new_entry_count": (
                        paper_policy_owner_handoff_runtime_proof.get(
                            "new_old_policy_entry_count"
                        )
                    ),
                    "new_challenger_candidate_count": (
                        paper_policy_owner_handoff_runtime_proof.get(
                            "new_challenger_candidate_count"
                        )
                    ),
                    "new_challenger_intent_count": (
                        paper_policy_owner_handoff_runtime_proof.get(
                            "new_challenger_intent_count"
                        )
                    ),
                    "challenger_identity_preserved_to_outcome": (
                        paper_policy_owner_handoff_runtime_proof.get(
                            "challenger_identity_preserved_to_outcome"
                        )
                    ),
                    "last_tick_at": hb_ts or now,
                    "paper_event_count": paper_event_count,
                    "last_paper_event_count": paper_event_count,
                    "last_shadow_decision_count": int(hb.get("shadow_observation_count") or 0),
                    "last_risk_block_count": int(hb.get("blocked_count") or 0),
                    "intents_built": hb.get("intents_built"),
                    "intents_accepted": hb.get("intents_accepted"),
                    "intents_blocked": hb.get("intents_blocked"),
                    "order_cost_applicable_rows": order_applicable_rows,
                    "production_grade_cost_rows": production_grade_cost_rows,
                    "production_grade_cost_order_applicable_rows": production_grade_cost_order_applicable_rows,
                    "production_grade_cost_coverage": cost_coverage,
                    "production_grade_cost_coverage_basis": cost_coverage_basis,
                    "production_grade_cost_total_row_coverage": total_row_cost_coverage,
                    "no_order_explained_rows": no_order_explained_rows,
                    "unexplained_missing_cost_rows": unexplained_missing_cost_rows,
                    "no_order_missing_cost_rows": no_order_missing_cost_rows,
                    "paper_fill_allowed_rows": paper_fill_allowed_rows,
                    "routes_to_live_rows": routes_to_live_rows,
                    "places_real_order_rows": places_real_order_rows,
                    "a_grade_rows": a_grade_rows,
                    "near_a_grade_rows": near_a_grade_rows,
                    "source_tier_a_grade_execution_rows": source_tier_a_grade_execution_rows,
                    "guardian_status": a_grade_gate_status.get("guardian_status"),
                    "guardian_new_entries_allowed": a_grade_gate_status.get(
                        "guardian_new_entries_allowed"
                    ),
                    "guardian_block_all_new_a_grade_entries": a_grade_gate_status.get(
                        "guardian_block_all_new_a_grade_entries"
                    ),
                    "a_grade_predicate_counts": a_grade_predicates,
                    "paper_a_grade_gate_burndown_status": a_grade_gate_status,
                    "b_grade_canary_supply_status": b_grade_canary_supply_status,
                    "paper_trainer_model_quality_runtime_status": (
                        paper_trainer_model_quality_runtime_status
                    ),
                    "trainer_model_quality_runtime_status": (
                        paper_trainer_model_quality_runtime_status
                    ),
                    "paper_churn_equity_bleed_governor_status": (
                        paper_churn_equity_bleed_governor_status
                    ),
                    "paper_forward_canary_evidence_status": paper_forward_canary_evidence_status,
                    "one_thousand_x_trajectory_runtime_status": (
                        one_thousand_x_trajectory_status
                    ),
                    "preemptive_edge_control_status": preemptive_edge_control_status,
                    "preemptive_candidate_decision_matrix": (
                        preemptive_candidate_decision_matrix
                    ),
                    "paper_preemptive_admission_status": (
                        paper_preemptive_admission_status
                    ),
                    "paper_no_bad_entry_runtime_status": (
                        paper_no_bad_entry_runtime_status
                    ),
                    "positive_edge_probation": positive_edge_probation_summary,
                    "positive_edge_probation_policy": positive_edge_probation_policy,
                    "positive_edge_probation_runtime_status": (
                        positive_edge_probation_runtime_status
                    ),
                    "probation_5_trade_gate": probation_5_trade_gate,
                    "probation_20_trade_gate": probation_20_trade_gate,
                    "probation_50_trade_gate": probation_50_trade_gate,
                },
                "paper_account": _runtime_canonical_paper_account(client),
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
                "blockers": blockers,
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
                "account_scope": "PAPER_SIM_ACCOUNT",
                "source_type": "paper_runtime_error",
                "paper_or_live": "paper",
                "contains_simulated_positions": True,
                "contains_live_positions": False,
                "contains_quarantined_positions": False,
                "equity_trusted": False,
                "pnl_trusted": False,
                "reason_if_untrusted": "PAPER_RUNTIME_STATUS_UNAVAILABLE",
                "live_gate_status": "blocked_human_only",
                "mode": "paper",
                "error": str(exc),
                "exchange_orders": False,
                "legacy_redis_writes": False,
                "leverage_changes": False,
                "margin_mode_changes": False,
                "continuous_loop_available": False,
            }

    data = await run_in_threadpool(_build if debug else _build_primary)
    generated_at = data.get("generated_at") if isinstance(data, dict) else None
    if isinstance(data, dict):
        data.setdefault("generated_et", _to_et(generated_at) or _et_now())
        data.setdefault("timestamp_et", data.get("generated_et"))
        data.setdefault("received_et", _et_now())
    return data


@router.get("/paper/fills")
async def get_paper_fills(actor: UserRecord | None = Depends(optional_auth)) -> dict[str, Any]:
    """Public endpoint: paper engine fill history from v2:paper:intents (filled entries only)."""
    endpoint = "/api/v2/paper/fills"

    def _load() -> dict[str, Any]:
        try:
            client = get_redis()
            readiness_context = _paper_a_grade_readiness_context(client)
            intents = _paper_intents_from_redis(client)
            fills = _paper_fills_from_intents(intents)
            return {
                "fills": fills[:500],
                "total": len(fills),
                "real_trader_readiness": readiness_context,
                "a_grade_blocker_truth": readiness_context["a_grade_blocker_truth"],
                "exact_no_live_reason": readiness_context["exact_no_live_reason"],
                "readiness_blockers": readiness_context["readiness_blockers"],
                "top_blockers": readiness_context["readiness_blockers"][:8],
                "live_ready": False,
                "live_submit_allowed": False,
            }
        except Exception as exc:
            readiness_context = _paper_a_grade_readiness_context(None)
            return {
                "fills": [],
                "total": 0,
                "error": str(exc),
                "real_trader_readiness": readiness_context,
                "a_grade_blocker_truth": readiness_context["a_grade_blocker_truth"],
                "exact_no_live_reason": readiness_context["exact_no_live_reason"],
                "readiness_blockers": readiness_context["readiness_blockers"],
                "top_blockers": readiness_context["readiness_blockers"][:8],
                "live_ready": False,
                "live_submit_allowed": False,
            }

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
            readiness_context = _paper_a_grade_readiness_context(None)
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
                "real_trader_readiness": readiness_context,
                "a_grade_blocker_truth": readiness_context["a_grade_blocker_truth"],
                "top_blockers": readiness_context["readiness_blockers"][:8],
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
    async with track_current_task("websocket:paper-activity"):
        client_id = _websocket_client_id(websocket)
        registered, total_count, client_count = _try_register_paper_activity_websocket(client_id)
        await websocket.accept()
        if not registered:
            await _send_websocket_json_bounded(websocket, {
                "data": None,
                "source": "v2:paper:* Redis",
                "source_type": "unavailable",
                "endpoint": "/api/v2/ws/paper-activity",
                "timestamp": _utc_now(),
                "received_at": _utc_now(),
                "lag_ms": None,
                "stale": True,
                "missing_fields": ["paper_activity_websocket_capacity"],
                "warnings": ["Paper activity websocket capacity limit reached; use enterprise realtime multiplexing or HTTP fallback"],
                "mode": "paper",
                "transport": "websocket",
                "active_websocket_count": total_count,
                "active_websocket_count_for_client": client_count,
                "max_active_websocket_count": max(1, PAPER_ACTIVITY_WS_MAX_ACTIVE),
                "max_active_websocket_count_per_client": max(1, PAPER_ACTIVITY_WS_MAX_ACTIVE_PER_CLIENT),
            })
            with contextlib.suppress(Exception):
                await websocket.close(code=1013)
            return
        try:
            requested_interval = int(websocket.query_params.get("interval_ms", "1000"))
        except ValueError:
            requested_interval = 1000
        interval_seconds = max(0.5, min(10.0, requested_interval / 1000))
        disconnect_task = create_registered_task(
            _watch_websocket_disconnect(websocket),
            label="websocket-disconnect:paper-activity",
        )
        try:
            while _websocket_is_connected(websocket) and not shutdown_started() and not disconnect_task.done():
                try:
                    data, warnings = await _bounded_run_in_threadpool(
                        _load_paper_activity_payload,
                        timeout=READONLY_RESOURCE_RESOLVE_TIMEOUT_SECONDS,
                    )
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
                except asyncio.CancelledError:
                    raise
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
                if not await _send_websocket_json_bounded(websocket, payload):
                    return
                wait_result = await _wait_for_next_websocket_iteration(interval_seconds, disconnect_task)
                if wait_result in {"shutdown", "disconnect"}:
                    break
            if shutdown_started():
                await _close_websocket_for_service_restart(websocket)
        except WebSocketDisconnect:
            return
        except asyncio.CancelledError:
            raise
        finally:
            _unregister_paper_activity_websocket(client_id)
            await _cancel_websocket_disconnect_task(disconnect_task)


@router.websocket("/ws/paper-activity")
async def api_v2_paper_activity_stream(websocket: WebSocket) -> None:
    await _paper_activity_websocket(websocket)


@stream_router.websocket("/ws/paper-activity")
async def root_paper_activity_stream(websocket: WebSocket) -> None:
    await _paper_activity_websocket(websocket)


async def _readonly_resource_websocket(websocket: WebSocket) -> None:
    async with track_current_task("websocket:readonly-resource"):
        await websocket.accept()
        target = _safe_readonly_resource_target(websocket.query_params.get("path"))
        try:
            requested_interval = int(websocket.query_params.get("interval_ms", "15000"))
        except ValueError:
            requested_interval = 15000
        interval_seconds = max(0.5, min(120.0, requested_interval / 1000))
        if target is None:
            await _send_websocket_json_bounded(websocket, {
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
        disconnect_task = create_registered_task(
            _watch_websocket_disconnect(websocket),
            label="websocket-disconnect:readonly-resource",
        )
        try:
            while _websocket_is_connected(websocket) and not shutdown_started() and not disconnect_task.done():
                started = time.monotonic()
                try:
                    payload = await _readonly_resource_resolve_payload(target, headers)
                    payload = _readonly_resource_ws_payload(target, payload, started)
                except asyncio.CancelledError:
                    raise
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
                if not await _send_websocket_json_bounded(websocket, payload):
                    return
                wait_result = await _wait_for_next_websocket_iteration(interval_seconds, disconnect_task)
                if wait_result in {"shutdown", "disconnect"}:
                    break
            if shutdown_started():
                await _close_websocket_for_service_restart(websocket)
        except WebSocketDisconnect:
            return
        except asyncio.CancelledError:
            raise
        finally:
            await _cancel_websocket_disconnect_task(disconnect_task)


@router.websocket("/ws/resource")
async def api_v2_readonly_resource_stream(websocket: WebSocket) -> None:
    await _readonly_resource_websocket(websocket)


@stream_router.websocket("/ws/resource")
async def root_readonly_resource_stream(websocket: WebSocket) -> None:
    await _readonly_resource_websocket(websocket)
