"""Read provider Redis payloads and normalize them into ProviderInput rows.

Read-only against Redis. Missing keys become present=False (masked), never
zero-filled. Staleness is judged per provider freshness class.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from app.services.altdata.altdata_confluence_engine import (
    FRESHNESS_SECONDS_BY_PROVIDER,
    ProviderInput,
)


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_json(redis_client: Any, key: str) -> dict[str, Any] | None:
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _staleness(payload: Mapping[str, Any], provider: str, now: datetime) -> bool:
    freshness = FRESHNESS_SECONDS_BY_PROVIDER.get(provider, 3_600)
    marker = payload.get("available_at") or payload.get("generated_utc")
    stamp = _parse_utc(marker)
    if stamp is None:
        return True
    return (now - stamp).total_seconds() > freshness


def _float_features(source: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, value in source.items():
        try:
            out[str(name)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def load_coinglass_input(redis_client: Any, symbol: str, timeframe: str) -> ProviderInput:
    payload = _load_json(redis_client, f"v2:features:coinglass:{symbol}:{timeframe}")
    if not payload or not payload.get("actual_payload_present"):
        return ProviderInput(provider="coinglass", present=False)
    now = datetime.now(timezone.utc)
    return ProviderInput(
        provider="coinglass",
        present=True,
        stale=_staleness(payload, "coinglass", now),
        features=_float_features(payload.get("features") or {}),
        feature_cutoff=payload.get("feature_cutoff"),
        missing_feature_flags=tuple(payload.get("missing_feature_flags") or ()),
        stale_feature_flags=tuple(payload.get("stale_feature_flags") or ()),
    )


def load_coinank_input(redis_client: Any, symbol: str, timeframe: str) -> ProviderInput:
    """Bridged CoinAnk derivatives/liquidation features (v2_coinank_intel_bridge).

    Reads ``v2:features:coinank:{symbol}:{timeframe}``. Falls back to any
    timeframe under the consolidated ``v2:coinank:symbol:{symbol}`` key so a
    confluence pair still gets CoinAnk context when that exact timeframe was
    not bridged.
    """
    payload = _load_json(redis_client, f"v2:features:coinank:{symbol}:{timeframe}")
    if not payload or not payload.get("actual_payload_present"):
        payload = _load_json(redis_client, f"v2:coinank:symbol:{symbol}")
    if not payload or not payload.get("actual_payload_present"):
        return ProviderInput(provider="coinank", present=False)
    now = datetime.now(timezone.utc)
    return ProviderInput(
        provider="coinank",
        present=True,
        stale=_staleness(payload, "coinank", now),
        features=_float_features(payload.get("features") or {}),
        feature_cutoff=payload.get("feature_cutoff") or payload.get("generated_utc"),
    )


def load_moralis_input(redis_client: Any, symbol: str, timeframe: str) -> ProviderInput:
    payload = _load_json(redis_client, f"v2:features:moralis:{symbol}:{timeframe}")
    signals = _load_json(redis_client, f"v2:smart_money:signals:{symbol}") or {}
    features: dict[str, float] = {}
    cutoff = None
    stale = True
    if payload and payload.get("actual_payload_present"):
        features.update(_float_features(payload.get("features") or {}))
        cutoff = payload.get("feature_cutoff")
        stale = _staleness(payload, "moralis", datetime.now(timezone.utc))
    signal_features = signals.get("features") if isinstance(signals.get("features"), Mapping) else {}
    features.update(_float_features(signal_features))
    if not features:
        return ProviderInput(provider="moralis", present=False)
    return ProviderInput(
        provider="moralis",
        present=True,
        stale=stale,
        features=features,
        feature_cutoff=cutoff or signals.get("feature_cutoff"),
        missing_feature_flags=tuple(payload.get("missing_feature_flags") or ()) if payload else (),
    )
