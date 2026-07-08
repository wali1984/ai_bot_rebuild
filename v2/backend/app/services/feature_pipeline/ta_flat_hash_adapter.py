"""TA flat-hash adapter: nested V2 TA JSON -> legacy-compatible flat hashes.

The legacy trainer contract expects flat TA hashes at ``ta:{SYM}:{TF}``.
V2 publishes nested JSON at ``v2:technical_analysis:{SYM}:{TF}`` (216+
indicators under ``indicators``) and ``v2:features:ta:{SYM}:{TF}``. This
adapter flattens every numeric indicator and adds canonical legacy aliases
(RSI, MACD, BB_UPPER, ...) so both legacy-compatible consumers and V2 readers
share one field map. Values are only ever copied from real computed
indicators — nothing is synthesized.
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping

from v2.backend.app.services.feature_pipeline.ta_legacy_field_map import (
    LEGACY_ALIAS_MAP,
    MIN_REQUIRED_FIELDS,
)

FLAT_KEY_LEGACY = "ta:{symbol}:{timeframe}"
FLAT_KEY_V2 = "v2:ta_flat:{symbol}:{timeframe}"
SOURCE_KEYS = (
    "v2:technical_analysis:{symbol}:{timeframe}",
    "v2:features:ta:{symbol}:{timeframe}",
    "v2:features:ta_full:{symbol}:{timeframe}",
)

def _f(value: Any) -> float | None:
    try:
        if value is None or value == "" or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_json(r: Any, key: str) -> dict[str, Any] | None:
    try:
        raw = r.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def flatten_ta(
    payloads: list[Mapping[str, Any]],
) -> tuple[dict[str, float], list[str]]:
    """Flatten every numeric indicator; add canonical legacy aliases."""
    flat: dict[str, float] = {}
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        indicators = payload.get("indicators")
        source = indicators if isinstance(indicators, Mapping) else payload
        for name, value in source.items():
            v = _f(value)
            if v is not None and name not in flat:
                flat[str(name)] = v
            elif isinstance(value, Mapping):
                for sub, subval in value.items():
                    sv = _f(subval)
                    if sv is not None:
                        flat.setdefault(f"{name}_{sub}", sv)
    missing_aliases: list[str] = []
    for legacy, candidates in LEGACY_ALIAS_MAP.items():
        for cand in candidates:
            if cand in flat:
                flat.setdefault(legacy, flat[cand])
                break
        else:
            missing_aliases.append(legacy)
    return flat, missing_aliases


def _source_hash(payloads: list[Mapping[str, Any]]) -> str:
    raw = json.dumps(payloads, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _first_metadata(payloads: list[Mapping[str, Any]], *fields: str) -> str | None:
    for payload in payloads:
        for field in fields:
            value = payload.get(field)
            if value not in (None, ""):
                return str(value)
    return None


def _has_unfinished_candle(payloads: list[Mapping[str, Any]]) -> bool:
    for payload in payloads:
        for field in ("candle_closed_confirmed", "closed_candle", "is_closed"):
            if field in payload and payload.get(field) is False:
                return True
    return False


def publish_flat_ta(
    r: Any,
    *,
    symbol: str,
    timeframe: str,
    ttl_seconds: int = 900,
) -> dict[str, Any]:
    """Read nested TA, publish flat hashes, return a coverage record."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payloads = []
    for tpl in SOURCE_KEYS:
        payload = _read_json(r, tpl.format(symbol=symbol, timeframe=timeframe))
        if payload:
            payloads.append(payload)
    if not payloads:
        return {
            "symbol": symbol, "timeframe": timeframe, "generated_utc": now,
            "field_count": 0, "published": False,
            "missing_reason": "NO_TA_SOURCE_PAYLOAD",
        }
    if _has_unfinished_candle(payloads):
        return {
            "symbol": symbol, "timeframe": timeframe, "generated_utc": now,
            "field_count": 0, "published": False,
            "missing_reason": "UNFINISHED_CANDLE_NOT_FINAL",
            "candle_closed_confirmed": False,
        }
    flat, missing_aliases = flatten_ta(payloads)
    if not flat:
        return {
            "symbol": symbol, "timeframe": timeframe, "generated_utc": now,
            "field_count": 0, "published": False,
            "missing_reason": "TA_PAYLOAD_HAS_NO_NUMERIC_INDICATORS",
        }
    mapping = {name: repr(value) for name, value in flat.items()}
    source_hash = _source_hash(payloads)
    mapping["_generated_utc"] = now
    mapping["_available_at"] = _first_metadata(payloads, "available_at", "generated_at", "generated_utc") or now
    mapping["_feature_cutoff"] = _first_metadata(payloads, "feature_cutoff", "candle_close_time", "event_time") or mapping["_available_at"]
    mapping["_source_hash"] = source_hash
    mapping["_source"] = "v2_ta_flat_hash_adapter_v1"
    mapping["_missing_mask"] = json.dumps({name: 1 for name in missing_aliases}, sort_keys=True)
    mapping["_stale_mask"] = json.dumps({}, sort_keys=True)
    mapping["_candle_closed_confirmed"] = "true"
    for key_tpl in (FLAT_KEY_LEGACY, FLAT_KEY_V2):
        key = key_tpl.format(symbol=symbol, timeframe=timeframe)
        try:
            pipe = r.pipeline()
            pipe.delete(key)
            pipe.hset(key, mapping=mapping)
            pipe.expire(key, ttl_seconds)
            pipe.execute()
        except Exception:
            return {
                "symbol": symbol, "timeframe": timeframe, "generated_utc": now,
                "field_count": len(flat), "published": False,
                "missing_reason": "REDIS_WRITE_FAILED",
            }
    return {
        "symbol": symbol, "timeframe": timeframe, "generated_utc": now,
        "field_count": len(flat), "published": True,
        "source_hash": source_hash,
        "available_at": mapping["_available_at"],
        "feature_cutoff": mapping["_feature_cutoff"],
        "candle_closed_confirmed": True,
        "meets_legacy_minimum": len(flat) >= MIN_REQUIRED_FIELDS,
        "missing_legacy_aliases": missing_aliases,
    }
