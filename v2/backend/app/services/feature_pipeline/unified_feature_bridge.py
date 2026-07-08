"""Unified feature bridge for TA flat hashes plus optional providers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from v2.backend.app.services.feature_pipeline.ta_flat_hash_adapter import FLAT_KEY_V2
from v2.backend.app.services.provider_features import build_provider_consumer_context

UNIFIED_FEATURE_KEY = "v2:features:unified:{symbol}:{timeframe}"


def build_unified_feature_payload(
    redis_client: Any | None,
    *,
    symbol: str,
    timeframe: str = "1m",
    decision_time: str | int | float | datetime | None = None,
    publish: bool = False,
    ttl_seconds: int = 300,
) -> dict[str, Any]:
    normalized_symbol = str(symbol).upper()
    ta = _read_ta_flat(redis_client, symbol=normalized_symbol, timeframe=timeframe)
    provider_context = build_provider_consumer_context(
        redis_client,
        role="trainer",
        symbol=normalized_symbol,
        timeframe=timeframe,
        decision_time=decision_time,
    )
    provider_features = provider_context.get("provider_features")
    provider_features = provider_features if isinstance(provider_features, Mapping) else {}
    features: dict[str, float] = {}
    features.update(_numeric_subset(ta.get("features") if isinstance(ta, Mapping) else {}))
    features.update(_numeric_subset(provider_features))
    payload = {
        "schema_version": "unified_feature_bridge_v1",
        "symbol": normalized_symbol,
        "timeframe": timeframe,
        "generated_at": _now(),
        "decision_time": _iso_or_none(decision_time),
        "features": features,
        "feature_count": len(features),
        "ta_flat": ta,
        "provider_feature_context": provider_context,
        "point_in_time_safe": not provider_context.get("point_in_time_violations"),
        "optional_provider_failures_core_blocking": False,
        "heartbeat_only_green_allowed": False,
        "raw_key_exposed": False,
    }
    if publish and redis_client is not None:
        key = UNIFIED_FEATURE_KEY.format(symbol=normalized_symbol, timeframe=timeframe)
        redis_client.set(key, json.dumps(payload, sort_keys=True, default=str), ex=ttl_seconds)
        payload["published_key"] = key
    return payload


def _read_ta_flat(redis_client: Any | None, *, symbol: str, timeframe: str) -> dict[str, Any]:
    key = FLAT_KEY_V2.format(symbol=symbol, timeframe=timeframe)
    if redis_client is None or not hasattr(redis_client, "hgetall"):
        return {"source_key": key, "available": False, "features": {}}
    try:
        raw = redis_client.hgetall(key)
    except Exception:
        return {"source_key": key, "available": False, "features": {}}
    if not isinstance(raw, Mapping) or not raw:
        return {"source_key": key, "available": False, "features": {}}
    decoded = {
        _decode(k): _decode(v)
        for k, v in raw.items()
    }
    return {
        "source_key": key,
        "available": True,
        "source_hash": decoded.get("_source_hash"),
        "available_at": decoded.get("_available_at"),
        "feature_cutoff": decoded.get("_feature_cutoff"),
        "candle_closed_confirmed": decoded.get("_candle_closed_confirmed") == "true",
        "missing_mask": _json_field(decoded.get("_missing_mask")),
        "stale_mask": _json_field(decoded.get("_stale_mask")),
        "features": {
            name: value
            for name, value in decoded.items()
            if not str(name).startswith("_")
        },
    }


def _numeric_subset(values: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, value in values.items():
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed == parsed and abs(parsed) != float("inf"):
            out[str(name)] = parsed
    return out


def _decode(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _json_field(value: Any) -> Any:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, (dict, list)) else {}


def _iso_or_none(value: str | int | float | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000.0
        try:
            parsed = datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
