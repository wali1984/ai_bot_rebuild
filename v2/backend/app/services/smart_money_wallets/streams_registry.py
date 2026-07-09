"""Moralis Streams readiness registry.

This module is read-only. It prepares what should be watched, but does not
create Moralis streams or enable webhook traffic by itself.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping

from app.services.smart_money_wallets.token_contract_mapper import read_pollable_tokens
from app.services.smart_money_wallets.wallet_watchlist import read_wallet_watchlist


STREAMS_STATUS_KEY = "v2:provider:moralis:streams_status"


def build_streams_registry(
    redis_client: Any | None,
    *,
    env: Mapping[str, str | None] | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    env = env or os.environ
    wallets = [row for row in read_wallet_watchlist(redis_client) if row.get("tier") == "T0"]
    tokens = read_pollable_tokens(redis_client, symbol=symbol)
    webhook_url = str(env.get("MORALIS_STREAM_WEBHOOK_URL") or "").strip()
    secret_present = bool(str(env.get("MORALIS_STREAM_WEBHOOK_SECRET") or "").strip())
    signature_validated = str(env.get("MORALIS_STREAM_SIGNATURE_VALIDATED") or "").lower() in {"1", "true", "yes"}
    streams_configured = bool(webhook_url and secret_present)
    streams_ready = bool(streams_configured and signature_validated)
    return {
        "schema_version": "moralis_streams_registry_v1",
        "status": "STREAMS_READY" if streams_ready else "STREAMS_NOT_READY",
        "generated_utc": _now(),
        "webhook_url_configured": bool(webhook_url),
        "webhook_secret_present": secret_present,
        "webhook_signature_validation": signature_validated,
        "streams_configured": streams_configured,
        "streams_ready": streams_ready,
        "stream_count": len(wallets) + len(tokens),
        "watched_wallets": wallets[:50],
        "watched_contracts": tokens[:100],
        "last_stream_event": _read_last_stream_event(redis_client),
        "operator_setup_required": not streams_ready,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }


def publish_streams_registry(
    redis_client: Any,
    *,
    env: Mapping[str, str | None] | None = None,
    symbol: str | None = None,
    ttl_seconds: int = 3600,
) -> dict[str, Any]:
    payload = build_streams_registry(redis_client, env=env, symbol=symbol)
    redis_client.set(STREAMS_STATUS_KEY, json.dumps(payload, sort_keys=True, default=str), ex=ttl_seconds)
    payload["keys_written"] = [STREAMS_STATUS_KEY]
    return payload


def _read_last_stream_event(redis_client: Any | None) -> Any:
    if redis_client is None:
        return None
    try:
        raw = redis_client.get("v2:provider:moralis:stream:webhook:latest")
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
