"""Public-safe market stream alert history.

This module persists local stream-alert summaries for public market data only.
It does not read private account data, does not sign requests, does not call an
exchange, and does not enable live trading. The history is local evidence only;
it is not production alerting/dashboard integration.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.market_stream_alert_notifier import (
    market_stream_alert_notifier_status,
    notify_market_stream_alert,
)


_ALERT_HISTORY_LOCK = threading.Lock()
MARKET_STREAM_ALERT_HISTORY_KIND = "local_market_stream_alert_history"


def _repo_root() -> Path:
    return Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))


def _history_path() -> Path:
    configured = os.environ.get("ALPHAFORGE_MARKET_STREAM_ALERT_HISTORY_STORE", "").strip()
    if configured:
        return Path(configured)
    repo_root = _repo_root()
    if (repo_root / "backend" / "app").exists():
        return repo_root / "backend" / "market_stream_alert_history.jsonl"
    return repo_root / "v2" / "backend" / "market_stream_alert_history.jsonl"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _production_alerting_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_MARKET_STREAM_PRODUCTION_ALERTING_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def _production_validation_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_MARKET_STREAM_PRODUCTION_VALIDATION_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def production_market_stream_validation_evidence() -> dict[str, Any]:
    artifact_path = _production_validation_artifact_path()
    if artifact_path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "warnings": ["Production stream validation artifact is not configured"],
        }
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warnings": [f"Production stream validation artifact could not be read: {exc}"],
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warnings": ["Production stream validation artifact must be a JSON object"],
        }
    status_value = str(payload.get("status") or payload.get("production_stream_validation_status") or "").strip().lower()
    public_stream_connected = payload.get("public_stream_connected") is True
    native_stream_validated = payload.get("native_stream_validated") is True
    symbol_timeframe_filter_verified = payload.get("symbol_timeframe_filter_verified") is True
    freshness_enforced = payload.get("freshness_enforced") is True
    stale_detection_verified = payload.get("stale_detection_verified") is True
    telemetry_persisted = payload.get("telemetry_persisted") is True
    fallback_labeling_verified = payload.get("fallback_labeling_verified") is True
    no_static_presented_as_live = payload.get("no_static_presented_as_live") is True
    public_market_data_only = payload.get("public_market_data_only") is True
    contains_credentials = payload.get("contains_credentials") is True
    live_disabled = payload.get("live_trading_enabled") is False
    exchange_disabled = payload.get("exchange_mutation_enabled") is False
    valid = (
        status_value in {"pass", "passed", "ok", "verified"}
        and public_stream_connected
        and native_stream_validated
        and symbol_timeframe_filter_verified
        and freshness_enforced
        and stale_detection_verified
        and telemetry_persisted
        and fallback_labeling_verified
        and no_static_presented_as_live
        and public_market_data_only
        and not contains_credentials
        and live_disabled
        and exchange_disabled
    )
    warnings = list(payload.get("warnings") or []) if isinstance(payload.get("warnings"), list) else []
    if not valid:
        warnings.append(
            "Production stream validation artifact must prove native public stream connectivity, symbol/timeframe filtering, freshness/stale handling, telemetry persistence, fallback labeling, no fake-live data, public-only data, no credentials, and disabled live/exchange mutation"
        )
    return {
        "configured": True,
        "valid": valid,
        "status": "verified" if valid else "invalid",
        "public_stream_connected": public_stream_connected,
        "native_stream_validated": native_stream_validated,
        "symbol_timeframe_filter_verified": symbol_timeframe_filter_verified,
        "freshness_enforced": freshness_enforced,
        "stale_detection_verified": stale_detection_verified,
        "telemetry_persisted": telemetry_persisted,
        "fallback_labeling_verified": fallback_labeling_verified,
        "no_static_presented_as_live": no_static_presented_as_live,
        "public_market_data_only": public_market_data_only,
        "contains_credentials": contains_credentials,
        "warnings": [str(warning) for warning in warnings],
    }


def production_market_stream_alerting_evidence() -> dict[str, Any]:
    artifact_path = _production_alerting_artifact_path()
    if artifact_path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "warnings": ["Production stream alerting/dashboard artifact is not configured"],
        }
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warnings": [f"Production stream alerting/dashboard artifact could not be read: {exc}"],
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warnings": ["Production stream alerting/dashboard artifact must be a JSON object"],
        }
    status_value = str(payload.get("status") or payload.get("production_alerting_status") or "").strip().lower()
    production_alerting_integrated = payload.get("production_alerting_integrated") is True
    dashboard_integrated = payload.get("dashboard_integrated") is True
    stale_alerts_enabled = payload.get("stale_alerts_enabled") is True
    reconnect_alerts_enabled = payload.get("reconnect_alerts_enabled") is True
    lag_monitoring_enabled = payload.get("lag_monitoring_enabled") is True
    missing_source_alerts_enabled = payload.get("missing_source_alerts_enabled") is True
    public_market_data_only = payload.get("public_market_data_only") is True
    contains_credentials = payload.get("contains_credentials") is True
    live_disabled = payload.get("live_trading_enabled") is False
    exchange_disabled = payload.get("exchange_mutation_enabled") is False
    valid = (
        status_value in {"pass", "passed", "ok", "verified"}
        and production_alerting_integrated
        and dashboard_integrated
        and stale_alerts_enabled
        and reconnect_alerts_enabled
        and lag_monitoring_enabled
        and missing_source_alerts_enabled
        and public_market_data_only
        and not contains_credentials
        and live_disabled
        and exchange_disabled
    )
    warnings = list(payload.get("warnings") or []) if isinstance(payload.get("warnings"), list) else []
    if not valid:
        warnings.append(
            "Production stream alerting artifact must prove dashboard integration, stale/reconnect/lag/missing-source alerts, public-only data, no credentials, and disabled live/exchange mutation"
        )
    return {
        "configured": True,
        "valid": valid,
        "status": "verified" if valid else "invalid",
        "production_alerting_integrated": production_alerting_integrated,
        "dashboard_integrated": dashboard_integrated,
        "stale_alerts_enabled": stale_alerts_enabled,
        "reconnect_alerts_enabled": reconnect_alerts_enabled,
        "lag_monitoring_enabled": lag_monitoring_enabled,
        "missing_source_alerts_enabled": missing_source_alerts_enabled,
        "public_market_data_only": public_market_data_only,
        "contains_credentials": contains_credentials,
        "warnings": [str(warning) for warning in warnings],
    }


def market_stream_alert_from_telemetry(telemetry: dict[str, Any]) -> dict[str, Any]:
    stale = bool(telemetry.get("stale"))
    lag_ms = telemetry.get("lag_ms") if isinstance(telemetry.get("lag_ms"), (int, float)) else None
    last_error = str(telemetry.get("last_error") or "").strip()
    if not stale and not last_error:
        return {
            "status": "clear",
            "severity": "info",
            "summary": "Market stream freshness is within the public status threshold.",
            "action": "No public action required.",
            "stale_for_ms": lag_ms,
            "last_error": None,
        }
    return {
        "status": "active",
        "severity": "warning",
        "summary": "Market stream freshness is degraded or unavailable.",
        "action": "Fallback market data remains labeled until stream freshness recovers.",
        "stale_for_ms": lag_ms,
        "last_error": last_error or None,
    }


def _safe_alert_record(symbol: str, telemetry: dict[str, Any], alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "history_kind": MARKET_STREAM_ALERT_HISTORY_KIND,
        "symbol": str(symbol).upper(),
        "source": str(telemetry.get("source") or "unavailable"),
        "last_event": telemetry.get("last_event"),
        "last_frame_at": telemetry.get("last_frame_at"),
        "lag_ms": telemetry.get("lag_ms"),
        "stale": bool(telemetry.get("stale")),
        "alert_status": alert.get("status"),
        "severity": alert.get("severity"),
        "summary": alert.get("summary"),
        "action": alert.get("action"),
        "last_error": alert.get("last_error"),
        "recorded_at": _utc_now(),
        "public_market_data_only": True,
        "contains_credentials": False,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
        "production_alerting_integrated": False,
    }


def append_market_stream_alert_record(symbol: str, telemetry: dict[str, Any]) -> dict[str, Any]:
    alert = market_stream_alert_from_telemetry(telemetry)
    record = _safe_alert_record(symbol, telemetry, alert)
    if alert.get("status") == "active":
        record["notification"] = notify_market_stream_alert(record)
    else:
        record["notification"] = {
            **market_stream_alert_notifier_status(),
            "delivered": False,
            "skipped_reason": "No active market stream alert.",
        }
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    lowered = encoded.lower()
    if any(forbidden in lowered for forbidden in ("api_key", "api_secret", "private_key", "password_hash")):
        raise ValueError("market stream alert history rejects credential-like fields")
    path = _history_path()
    with _ALERT_HISTORY_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
    return record


def read_market_stream_alert_history(symbol: str, *, limit: int = 50) -> list[dict[str, Any]]:
    safe_symbol = str(symbol).upper()
    path = _history_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        if len(rows) >= limit:
            break
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("symbol") != safe_symbol:
            continue
        rows.append(row)
    return rows


def market_stream_alert_history_summary(symbol: str) -> dict[str, Any]:
    rows = read_market_stream_alert_history(symbol, limit=100)
    active_count = sum(1 for row in rows if row.get("alert_status") == "active")
    production_evidence = production_market_stream_alerting_evidence()
    validation_evidence = production_market_stream_validation_evidence()
    return {
        "history_kind": MARKET_STREAM_ALERT_HISTORY_KIND,
        "event_count": len(rows),
        "active_count": active_count,
        "latest": rows[0] if rows else None,
        "path_configured": bool(os.environ.get("ALPHAFORGE_MARKET_STREAM_ALERT_HISTORY_STORE", "").strip()),
        "notifier": market_stream_alert_notifier_status(),
        "production_alerting_integrated": bool(production_evidence["valid"]),
        "production_alerting_status": "artifact_present_pending_current_validation"
        if production_evidence["valid"]
        else "missing",
        "production_alerting_artifact_configured": bool(production_evidence["configured"]),
        "production_alerting_artifact_valid": bool(production_evidence["valid"]),
        "production_alerting_artifact_status": str(production_evidence["status"]),
        "production_validation_integrated": bool(validation_evidence["valid"]),
        "production_validation_status": "artifact_present_pending_current_validation"
        if validation_evidence["valid"]
        else "missing",
        "production_validation_artifact_configured": bool(validation_evidence["configured"]),
        "production_validation_artifact_valid": bool(validation_evidence["valid"]),
        "production_validation_artifact_status": str(validation_evidence["status"]),
        "public_market_data_only": True,
    }
