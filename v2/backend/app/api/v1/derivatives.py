"""Typed current derivatives analytics contracts.

These routes are read-only views over V2 public market/runtime payloads. They
do not place orders, call test-order, mutate leverage/margin, or write old
Redis keys.
"""
from __future__ import annotations

import json
import math
from typing import Any

from fastapi import APIRouter

try:  # Uvicorn service runs with PYTHONPATH=v2/backend.
    from app.services.operator_truth.trade_derivatives_runtime import (
        DERIVATIVES_OUT,
        build_derivatives_payload,
        json_load,
    )
except ImportError:  # CLI/tests may import from the repo root package.
    from v2.backend.app.services.operator_truth.trade_derivatives_runtime import (
        DERIVATIVES_OUT,
        build_derivatives_payload,
        json_load,
    )


router = APIRouter(prefix="/derivatives", tags=["derivatives"])


def _payload() -> dict[str, Any]:
    cached = json_load(DERIVATIVES_OUT / "derivatives_payload.json", None)
    if isinstance(cached, dict):
        return cached
    return build_derivatives_payload()


_DERIV_REDIS: Any = None


def _get_redis() -> Any:
    """Return a reused Redis client (pinged for liveness), or None.

    Avoids building a fresh connection pool on every request.
    """
    global _DERIV_REDIS
    try:
        if _DERIV_REDIS is not None:
            _DERIV_REDIS.ping()
            return _DERIV_REDIS
    except Exception:
        _DERIV_REDIS = None
    try:
        import redis as _redis
        client = _redis.Redis(
            host="127.0.0.1", port=6379, db=0, socket_connect_timeout=2, socket_timeout=3
        )
        client.ping()
        _DERIV_REDIS = client
        return client
    except Exception:
        _DERIV_REDIS = None
        return None


def _scan_keys(r: Any, pattern: str, cap: int = 2000) -> list[str]:
    """Bounded cursor SCAN (never blocking KEYS) over the shared key store."""
    keys: list[str] = []
    try:
        cursor = 0
        while True:
            cursor, batch = r.scan(cursor=cursor, match=pattern, count=500)
            keys.extend(k.decode() if isinstance(k, bytes) else k for k in batch)
            if cursor == 0 or len(keys) >= cap:
                break
    except Exception:
        return keys
    return keys


def _module(name: str) -> dict[str, Any]:
    payload = _payload()
    module = (payload.get("modules") or {}).get(name)
    if isinstance(module, dict):
        return {
            "generated_est": payload.get("generated_est"),
            "payload_age_seconds": payload.get("payload_age_seconds"),
            "source_keys": (payload.get("source_keys") or {}).get(name),
            **module,
        }
    return {
        "generated_est": payload.get("generated_est"),
        "payload_age_seconds": payload.get("payload_age_seconds"),
        "source_keys": (payload.get("source_keys") or {}).get(name),
        "data_status": f"NO_CURRENT_{name.upper()}_SOURCE",
        "rows": [],
        "missing_reason_if_any": f"NO_CURRENT_{name.upper()}_SOURCE",
    }


@router.get("/exchanges")
async def exchanges() -> dict[str, Any]:
    payload = _payload()
    exchanges_payload = payload.get("exchanges")
    if isinstance(exchanges_payload, dict):
        return exchanges_payload
    return {
        "generated_est": payload.get("generated_est"),
        "payload_age_seconds": payload.get("payload_age_seconds"),
        "source_keys": "operator_runtime/v2_derivatives/latest/derivatives_payload.json",
        "data_status": "NO_CURRENT_EXCHANGE_SOURCE",
        "rows": [],
        "missing_reason_if_any": "NO_CURRENT_EXCHANGE_SOURCE",
    }


@router.get("/funding")
async def funding() -> dict[str, Any]:
    return _module("funding")


@router.get("/open-interest")
async def open_interest() -> dict[str, Any]:
    return _module("open_interest")


@router.get("/long-short")
async def long_short() -> dict[str, Any]:
    return _module("long_short")


@router.get("/basis")
async def basis() -> dict[str, Any]:
    return _module("basis")


@router.get("/liquidations")
async def liquidations() -> dict[str, Any]:
    return _module("liquidations")


def _to_float(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


@router.get("/symbol-snapshot")
async def symbol_snapshot() -> dict[str, Any]:
    """Per-symbol OI and Long/Short snapshot from live Redis keys.

    Reads v2:market:open_interest:{symbol} and v2:market:long_short:{symbol}
    for all available symbols. Read-only; no exchange mutation or legacy Redis writes.
    """
    r = _get_redis()
    if r is None:
        return {"ok": False, "symbols": {}, "error": "redis_unavailable", "source_keys": []}

    result: dict[str, dict[str, Any]] = {}
    source_keys: list[str] = []

    try:
        oi_keys = _scan_keys(r, "v2:market:open_interest:*")
        for key in oi_keys:
            symbol = key.split(":")[-1]
            raw = r.get(key)
            if raw is None:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            oi = _to_float(data.get("openInterest") or data.get("open_interest"))
            if oi is not None:
                entry = result.setdefault(symbol, {})
                entry["open_interest"] = oi
                entry["oi_ts"] = data.get("time")
                source_keys.append(key)
    except Exception:
        pass

    try:
        ls_keys = _scan_keys(r, "v2:market:long_short:*")
        for key in ls_keys:
            symbol = key.split(":")[-1]
            raw = r.get(key)
            if raw is None:
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            ls_ratio = _to_float(data.get("long_short_ratio") or data.get("longShortRatio"))
            long_pct = _to_float(data.get("long_account_ratio") or data.get("longAccount"))
            short_pct = _to_float(data.get("short_account_ratio") or data.get("shortAccount"))
            if ls_ratio is not None:
                entry = result.setdefault(symbol, {})
                entry["long_short_ratio"] = ls_ratio
                if long_pct is not None:
                    entry["long_pct"] = long_pct * (100 if long_pct <= 1.0 else 1)
                if short_pct is not None:
                    entry["short_pct"] = short_pct * (100 if short_pct <= 1.0 else 1)
                entry["ls_ts"] = data.get("timestamp") or data.get("fetched_utc")
                source_keys.append(key)
    except Exception:
        pass

    return {
        "ok": True,
        "symbols": result,
        "symbol_count": len(result),
        "source_keys_count": len(source_keys),
        "warnings": ["Read-only Redis scan; no exchange mutation or legacy Redis writes"],
    }
