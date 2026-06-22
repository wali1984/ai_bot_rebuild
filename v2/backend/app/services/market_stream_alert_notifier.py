"""Disabled-by-default market stream alert notifier.

This module supports a public-market-data webhook notification seam for stream
freshness alerts. It never reads account data, never signs requests, never calls
exchange APIs, and never enables live trading. The webhook URL may contain a
secret token, so safe API status surfaces only booleans and sanitized delivery
state, never the configured URL.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any


_NOTIFIER_LOCK = threading.Lock()
_NOTIFIER_STATE: dict[str, Any] = {
    "last_delivery_at": None,
    "last_status_code": None,
    "last_error": None,
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _webhook_url() -> str:
    return os.environ.get("ALPHAFORGE_MARKET_STREAM_ALERT_WEBHOOK_URL", "").strip()


def _webhook_enabled() -> bool:
    return _truthy(os.environ.get("ALPHAFORGE_MARKET_STREAM_ALERT_WEBHOOK_ENABLED"))


def _allow_insecure_webhook() -> bool:
    return _truthy(os.environ.get("ALPHAFORGE_MARKET_STREAM_ALERT_ALLOW_INSECURE_WEBHOOK"))


def _timeout_seconds() -> float:
    raw = os.environ.get("ALPHAFORGE_MARKET_STREAM_ALERT_WEBHOOK_TIMEOUT_MS", "1500").strip()
    try:
        timeout_ms = int(raw)
    except ValueError:
        timeout_ms = 1500
    timeout_ms = max(100, min(timeout_ms, 5000))
    return timeout_ms / 1000.0


def _url_allowed(url: str) -> tuple[bool, str | None]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        return True, None
    if parsed.scheme == "http" and _allow_insecure_webhook():
        return True, None
    return False, "Webhook must use HTTPS unless explicitly allowed for local testing."


def _public_alert_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "alphaforge.market_stream_alert",
        "history_kind": str(record.get("history_kind") or "local_market_stream_alert_history"),
        "symbol": str(record.get("symbol") or ""),
        "source": str(record.get("source") or "unavailable"),
        "last_event": record.get("last_event"),
        "last_frame_at": record.get("last_frame_at"),
        "lag_ms": record.get("lag_ms"),
        "stale": bool(record.get("stale")),
        "alert_status": record.get("alert_status"),
        "severity": record.get("severity"),
        "summary": record.get("summary"),
        "action": record.get("action"),
        "recorded_at": record.get("recorded_at"),
        "public_market_data_only": True,
        "contains_credentials": False,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
        "mode": "read_only",
    }


def _safe_status(
    *,
    configured: bool,
    enabled: bool,
    delivered: bool,
    reason: str | None = None,
    status_code: int | None = None,
) -> dict[str, Any]:
    with _NOTIFIER_LOCK:
        if delivered:
            _NOTIFIER_STATE["last_delivery_at"] = _utc_now()
            _NOTIFIER_STATE["last_status_code"] = status_code
            _NOTIFIER_STATE["last_error"] = None
        elif reason and configured and enabled:
            _NOTIFIER_STATE["last_error"] = reason
    return market_stream_alert_notifier_status(
        configured=configured,
        enabled=enabled,
        delivered=delivered,
        reason=reason,
        status_code=status_code,
    )


def market_stream_alert_notifier_status(
    *,
    configured: bool | None = None,
    enabled: bool | None = None,
    delivered: bool = False,
    reason: str | None = None,
    status_code: int | None = None,
) -> dict[str, Any]:
    url = _webhook_url()
    is_configured = bool(url) if configured is None else configured
    is_enabled = _webhook_enabled() if enabled is None else enabled
    safe_reason = reason
    if is_configured:
        allowed, blocked_reason = _url_allowed(url)
        if not allowed:
            safe_reason = blocked_reason
    with _NOTIFIER_LOCK:
        last_delivery_at = _NOTIFIER_STATE.get("last_delivery_at")
        last_status_code = _NOTIFIER_STATE.get("last_status_code")
        last_error = _NOTIFIER_STATE.get("last_error")
    return {
        "provider": "webhook" if is_configured else "unavailable",
        "configured": is_configured,
        "enabled": is_enabled,
        "delivery_supported": bool(is_configured and is_enabled and not safe_reason),
        "delivered": delivered,
        "last_delivery_at": last_delivery_at,
        "last_status_code": status_code if status_code is not None else last_status_code,
        "last_error": safe_reason or last_error,
        "public_market_data_only": True,
        "contains_credentials": False,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
        "production_alerting_integrated": False,
    }


def notify_market_stream_alert(record: dict[str, Any]) -> dict[str, Any]:
    """Send a public stream alert webhook if explicitly configured and enabled."""

    url = _webhook_url()
    configured = bool(url)
    enabled = _webhook_enabled()
    if not configured:
        return _safe_status(configured=False, enabled=enabled, delivered=False, reason="Webhook not configured.")
    if not enabled:
        return _safe_status(configured=True, enabled=False, delivered=False, reason="Webhook disabled.")
    allowed, blocked_reason = _url_allowed(url)
    if not allowed:
        return _safe_status(configured=True, enabled=True, delivered=False, reason=blocked_reason)

    payload = _public_alert_payload(record)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    lowered = encoded.lower()
    if any(forbidden in lowered for forbidden in ("api_key", "api_secret", "private_key", "password_hash")):
        return _safe_status(
            configured=True,
            enabled=True,
            delivered=False,
            reason="Webhook payload rejected because it contained credential-like fields.",
        )

    request = urllib.request.Request(
        url,
        data=encoded.encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "AlphaForge-MarketStreamAlert/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
            status_code = int(getattr(response, "status", 0) or 0)
    except (urllib.error.URLError, TimeoutError, OSError):
        return _safe_status(
            configured=True,
            enabled=True,
            delivered=False,
            reason="Webhook delivery failed.",
        )

    delivered = 200 <= status_code < 300
    reason = None if delivered else "Webhook endpoint returned a non-success status."
    return _safe_status(
        configured=True,
        enabled=True,
        delivered=delivered,
        reason=reason,
        status_code=status_code,
    )
