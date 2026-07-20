"""Read provider Redis payloads and normalize them into ProviderInput rows.

Read-only against Redis. Missing keys become present=False (masked), never
zero-filled. Staleness is judged per provider freshness class.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.services.altdata.altdata_confluence_engine import (
    FRESHNESS_SECONDS_BY_PROVIDER,
    ProviderInput,
)

_STRICT_UTC_RFC3339 = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}" r"(?:\.[0-9]{1,6})?(?:Z|\+00:00)$",
    re.ASCII,
)


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not _STRICT_UTC_RFC3339.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        return None
    return parsed.astimezone(UTC)


def _load_json(redis_client: Any, key: str) -> dict[str, Any] | None:
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except (RecursionError, TypeError, ValueError):
        return None
    return payload if type(payload) is dict else None


def _staleness(*, available_at: datetime, provider: str, now: datetime) -> bool:
    freshness = FRESHNESS_SECONDS_BY_PROVIDER.get(provider, 3_600)
    age_seconds = (now - available_at).total_seconds()
    return age_seconds < 0.0 or age_seconds > freshness


def _float_features(source: Any) -> dict[str, float] | None:
    if type(source) is not dict or not source:
        return None
    out: dict[str, float] = {}
    for name, value in source.items():
        if type(name) is not str or not name or type(value) not in (int, float):
            return None
        try:
            parsed = float(value)
        except (OverflowError, TypeError, ValueError):
            return None
        if not math.isfinite(parsed):
            return None
        out[name] = parsed
    return out


def _string_flags(value: Any) -> tuple[str, ...] | None:
    if type(value) is not list or any(type(item) is not str or not item for item in value):
        return None
    if len(set(value)) != len(value):
        return None
    return tuple(value)


def _identity_matches(
    payload: Mapping[str, Any],
    *,
    schemas: frozenset[str],
    provider: str,
    symbol: str,
    timeframe: str,
) -> bool:
    schema_version = payload.get("schema_version")
    return bool(
        type(schema_version) is str
        and schema_version in schemas
        and type(payload.get("provider")) is str
        and payload.get("provider") == provider
        and type(payload.get("symbol")) is str
        and payload.get("symbol") == symbol
        and type(payload.get("timeframe")) is str
        and payload.get("timeframe") == timeframe
    )


def _validated_clocks(
    payload: Mapping[str, Any],
    *,
    now: datetime,
) -> tuple[str, str, str, datetime] | None:
    raw_cutoff = payload.get("feature_cutoff")
    raw_available_at = payload.get("available_at")
    raw_generated_at = payload.get("generated_at")
    cutoff = _parse_utc(raw_cutoff)
    available_at = _parse_utc(raw_available_at)
    generated_at = _parse_utc(raw_generated_at)
    if (
        not isinstance(raw_cutoff, str)
        or not isinstance(raw_available_at, str)
        or not isinstance(raw_generated_at, str)
        or cutoff is None
        or available_at is None
        or generated_at is None
        or cutoff > available_at
        or cutoff > generated_at
        or available_at > generated_at
        or available_at > now
        or generated_at > now
    ):
        return None
    return raw_cutoff, raw_available_at, raw_generated_at, available_at


def _feature_contract_parts(
    payload: Mapping[str, Any],
) -> tuple[dict[str, float], tuple[str, ...], tuple[str, ...]] | None:
    features = _float_features(payload.get("features"))
    missing_flags = _string_flags(payload.get("missing_feature_flags"))
    stale_flags = _string_flags(payload.get("stale_feature_flags"))
    if features is None or missing_flags is None or stale_flags is None:
        return None
    if set(features).intersection(missing_flags):
        return None
    if set(features).intersection(stale_flags):
        return None
    return features, missing_flags, stale_flags


def load_coinglass_input(redis_client: Any, symbol: str, timeframe: str) -> ProviderInput:
    payload = _load_json(redis_client, f"v2:features:coinglass:{symbol}:{timeframe}")
    now = datetime.now(UTC)
    if (
        not payload
        or not _identity_matches(
            payload,
            schemas=frozenset({"coinglass_aggregated_feature_payload_v2"}),
            provider="coinglass",
            symbol=symbol,
            timeframe=timeframe,
        )
        or payload.get("actual_payload_present") is not True
        or payload.get("provider_ready") is not True
        or payload.get("decision_time_safe") is not True
        or payload.get("temporal_contract_valid") is not True
    ):
        return ProviderInput(provider="coinglass", present=False)
    clocks = _validated_clocks(payload, now=now)
    feature_parts = _feature_contract_parts(payload)
    if clocks is None or feature_parts is None:
        return ProviderInput(provider="coinglass", present=False)
    feature_cutoff, raw_available_at, raw_generated_at, available_at = clocks
    features, missing_flags, stale_flags = feature_parts
    return ProviderInput(
        provider="coinglass",
        present=True,
        stale=_staleness(available_at=available_at, provider="coinglass", now=now),
        features=features,
        feature_cutoff=feature_cutoff,
        available_at=raw_available_at,
        generated_at=raw_generated_at,
        missing_feature_flags=missing_flags,
        stale_feature_flags=stale_flags,
    )


def load_coinank_input(redis_client: Any, symbol: str, timeframe: str) -> ProviderInput:
    """Bridged CoinAnk derivatives/liquidation features (v2_coinank_intel_bridge).

    Reads ``v2:features:coinank:{symbol}:{timeframe}``. A consolidated fallback
    is accepted only when it proves the same timeframe and PIT contract.
    """
    payload = _load_json(redis_client, f"v2:features:coinank:{symbol}:{timeframe}")
    fallback = payload is None
    if fallback:
        payload = _load_json(redis_client, f"v2:coinank:symbol:{symbol}")
    expected_schema = "v2_coinank_symbol_intel_v1" if fallback else "v2_coinank_symbol_feature_v1"
    if (
        not payload
        or not _identity_matches(
            payload,
            schemas=frozenset({expected_schema}),
            provider="coinank",
            symbol=symbol,
            timeframe=timeframe,
        )
        or payload.get("actual_payload_present") is not True
        or payload.get("feature_eligible") is not True
        or payload.get("temporal_contract_valid") is not True
        or payload.get("trainer_consumable") is not True
        or payload.get("valid_for_prediction") is not True
        or payload.get("valid_for_paper") is not True
        or (
            fallback
            and (
                payload.get("consolidated_timeframe_context_only") is not True
                or payload.get("cross_timeframe_fallback_allowed") is not False
            )
        )
    ):
        return ProviderInput(provider="coinank", present=False)
    now = datetime.now(UTC)
    clocks = _validated_clocks(payload, now=now)
    feature_parts = _feature_contract_parts(payload)
    if clocks is None or feature_parts is None:
        return ProviderInput(provider="coinank", present=False)
    feature_cutoff, raw_available_at, raw_generated_at, available_at = clocks
    features, missing_flags, stale_flags = feature_parts
    return ProviderInput(
        provider="coinank",
        present=True,
        stale=_staleness(available_at=available_at, provider="coinank", now=now),
        features=features,
        feature_cutoff=feature_cutoff,
        available_at=raw_available_at,
        generated_at=raw_generated_at,
        missing_feature_flags=missing_flags,
        stale_feature_flags=stale_flags,
    )


def load_moralis_input(redis_client: Any, symbol: str, timeframe: str) -> ProviderInput:
    payload = _load_json(redis_client, f"v2:features:moralis:{symbol}:{timeframe}")
    # The symbol signal is an independently expiring copy.  It is only a
    # fallback when the canonical key is absent; snapshots are never merged.
    if payload is None:
        payload = _load_json(redis_client, f"v2:smart_money:signals:{symbol}")
    now = datetime.now(UTC)
    if (
        not payload
        or not _identity_matches(
            payload,
            schemas=frozenset({"moralis_feature_bridge_v1"}),
            provider="moralis",
            symbol=symbol,
            timeframe=timeframe,
        )
        or payload.get("actual_payload_present") is not True
        or payload.get("provider_ready") is not True
        or payload.get("feature_bridge_ready") is not True
        or payload.get("decision_time_safe") is not True
        or payload.get("temporal_contract_valid") is not True
        or payload.get("source_temporal_contract_valid") is not True
        or payload.get("trainer_isolation_active") is not False
        or payload.get("trainer_consumption_prerequisites_bound") is not True
        or payload.get("consumer_receipts_bound") is not True
    ):
        return ProviderInput(provider="moralis", present=False)
    clocks = _validated_clocks(payload, now=now)
    feature_parts = _feature_contract_parts(payload)
    if clocks is None or feature_parts is None:
        return ProviderInput(provider="moralis", present=False)

    # ``*_bound`` fields above are producer declarations, not authenticated
    # consumer receipts.  This bridge has no retained-key resolver or receipt
    # verifier, so it must not translate declarations into consumption
    # authority.  Moralis stays source-visible in its own payload and remains
    # non-consumable here until a real verifier is wired at this boundary.
    return ProviderInput(provider="moralis", present=False)
