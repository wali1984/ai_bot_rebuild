"""Canonical, point-in-time-safe alt-data confluence reconstruction boundary.

This consumer deliberately does not read a cached confluence envelope.  It
loads CoinGlass, Moralis, and CoinAnk only through ``provider_feature_bridge``
and rebuilds confluence in-process.  Provider and composite content hashes are
deterministic identity aids only: they are not signatures, authentication, or
consumption authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from typing import Any

from . import altdata_confluence_engine, provider_feature_bridge
from .altdata_confluence_engine import FRESHNESS_SECONDS_BY_PROVIDER, ProviderInput

BOUNDARY_SCHEMA_VERSION = "canonical_altdata_confluence_boundary_v1"
IDENTITY_ROLE = "non_authoritative_content_identity_only"

_PROVIDERS = ("coinglass", "moralis", "coinank")
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._-]*$", re.ASCII)
_TIMEFRAME = re.compile(r"^[1-9][0-9]*(?:s|m|h|d|w)$", re.ASCII)
_STRICT_UTC_RFC3339 = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|\+00:00)$",
    re.ASCII,
)

_CONFLUENCE_FEATURES = frozenset(
    {
        "altdata_confluence_long_score",
        "altdata_confluence_short_score",
        "altdata_derivatives_pressure_score",
        "altdata_exchange_flow_pressure_usd",
        "altdata_hedge_required_score",
        "altdata_institutional_flow_score",
        "altdata_liquidation_sweep_risk_score",
        "altdata_market_regime_score",
        "altdata_options_pin_risk_score",
        "altdata_reduce_size_score",
        "altdata_social_attention_score",
        "altdata_social_euphoria_risk_score",
        "altdata_trade_block_score",
        "altdata_wallet_accumulation_score",
        "altdata_wallet_distribution_score",
    }
)

_ENGINE_FIELDS = frozenset(
    {
        "actual_payload_present",
        "allowed_actions",
        "core_system_blocked",
        "cycle_started_at",
        "decision_time_safe",
        "directional_long_agreeing_provider_count",
        "directional_short_agreeing_provider_count",
        "envelope_rejection_reasons",
        "feature_cutoff",
        "features",
        "forbidden_actions",
        "generated_at",
        "generated_utc",
        "heartbeat_only",
        "missing_feature_flags",
        "provider_direction_votes",
        "provider_feature_cutoffs",
        "provider_input_rejection_reasons",
        "providers_invalid",
        "providers_loaded_fresh",
        "providers_missing",
        "providers_noncontributing",
        "providers_present",
        "providers_stale",
        "raw_key_exposed",
        "santiment_removed",
        "schema_version",
        "single_provider_can_approve",
        "stale_feature_flags",
        "symbol",
        "timeframe",
    }
)


class CanonicalConfluenceContractError(ValueError):
    """Raised when the local reconstruction violates its trusted code contract."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: object) -> datetime | None:
    if type(value) is not str or not _STRICT_UTC_RFC3339.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        return None
    return parsed.astimezone(UTC)


def _contract_error(reason: str) -> CanonicalConfluenceContractError:
    return CanonicalConfluenceContractError(reason)


def _identity_record(material: dict[str, Any]) -> dict[str, Any]:
    serialized = json.dumps(
        material,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "algorithm": "sha256",
        "digest": hashlib.sha256(serialized).hexdigest(),
        "role": IDENTITY_ROLE,
        "authenticates_source": False,
        "authorizes_consumption": False,
        "is_cryptographic_proof": False,
        "is_signature": False,
    }


def _validate_identity_argument(*, name: str, value: object, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or not value or pattern.fullmatch(value) is None:
        raise _contract_error(f"{name}_invalid")
    return value


def _normalize_provider_input(
    expected_provider: str,
    value: object,
    *,
    observed_at: datetime,
) -> tuple[ProviderInput, str | None]:
    """Revalidate a bridge result and mask any invalid result as absent."""

    absent = ProviderInput(provider=expected_provider, present=False)
    if type(value) is not ProviderInput:
        return absent, "provider_input_type_invalid"
    if type(value.provider) is not str or value.provider != expected_provider:
        return absent, "provider_identity_invalid"
    if type(value.present) is not bool or type(value.stale) is not bool:
        return absent, "provider_presence_type_invalid"
    if type(value.features) is not dict:
        return absent, "provider_features_type_invalid"
    if (
        type(value.missing_feature_flags) is not tuple
        or type(value.stale_feature_flags) is not tuple
    ):
        return absent, "provider_feature_flags_type_invalid"
    missing_flags = value.missing_feature_flags
    stale_flags = value.stale_feature_flags
    if any(type(flag) is not str or not flag for flag in missing_flags + stale_flags):
        return absent, "provider_feature_flag_invalid"
    if len(set(missing_flags)) != len(missing_flags) or len(set(stale_flags)) != len(stale_flags):
        return absent, "provider_feature_flags_duplicate"

    if value.present is False:
        if (
            value.stale is not False
            or value.features
            or value.feature_cutoff is not None
            or value.available_at is not None
            or value.generated_at is not None
            or missing_flags
            or stale_flags
        ):
            return absent, "absent_provider_payload_invalid"
        return absent, None

    if not value.features:
        return absent, "provider_features_empty"
    normalized_features: dict[str, float] = {}
    for name, raw in value.features.items():
        if type(name) is not str or not name or type(raw) not in (int, float):
            return absent, "provider_feature_field_invalid"
        try:
            parsed = float(raw)
        except (OverflowError, TypeError, ValueError):
            return absent, "provider_feature_value_invalid"
        if not math.isfinite(parsed):
            return absent, "provider_feature_value_invalid"
        normalized_features[name] = parsed
    if set(normalized_features).intersection(missing_flags):
        return absent, "provider_feature_missing_mask_overlap"
    if set(normalized_features).intersection(stale_flags):
        return absent, "provider_feature_stale_mask_overlap"

    feature_cutoff = _parse_utc(value.feature_cutoff)
    available_at = _parse_utc(value.available_at)
    generated_at = _parse_utc(value.generated_at)
    if feature_cutoff is None or available_at is None or generated_at is None:
        return absent, "provider_clock_invalid"
    if not feature_cutoff <= available_at <= generated_at <= observed_at:
        return absent, "provider_causal_clock_order_invalid"

    freshness_seconds = FRESHNESS_SECONDS_BY_PROVIDER[expected_provider]
    stale = bool(
        value.stale or (observed_at - available_at).total_seconds() > freshness_seconds
    )
    return (
        ProviderInput(
            provider=expected_provider,
            present=True,
            stale=stale,
            features=normalized_features,
            feature_cutoff=value.feature_cutoff,
            available_at=value.available_at,
            generated_at=value.generated_at,
            missing_feature_flags=missing_flags,
            stale_feature_flags=stale_flags,
        ),
        None,
    )


def _provider_identity_material(
    provider: ProviderInput,
    *,
    validation_rejection: str | None,
) -> dict[str, Any]:
    return {
        "provider": provider.provider,
        "present": provider.present,
        "stale": provider.stale,
        "features": dict(sorted(provider.features.items())),
        "feature_cutoff": provider.feature_cutoff,
        "available_at": provider.available_at,
        "generated_at": provider.generated_at,
        "missing_feature_flags": list(provider.missing_feature_flags),
        "stale_feature_flags": list(provider.stale_feature_flags),
        "boundary_validation_rejection": validation_rejection,
    }


def _strict_string_list(payload: dict[str, Any], name: str) -> list[str]:
    value = payload.get(name)
    if (
        type(value) is not list
        or any(type(item) is not str or not item for item in value)
        or len(set(value)) != len(value)
        or value != sorted(value)
    ):
        raise _contract_error(f"confluence_{name}_invalid")
    return value


def _mask_empty_composite(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove the engine's legacy hedge zero when no provider contributed."""

    if payload.get("actual_payload_present") is not False:
        return payload
    features = payload.get("features")
    if type(features) is not dict:
        return payload
    normalized = dict(payload)
    normalized["features"] = {name: None for name in features}
    normalized["missing_feature_flags"] = sorted(features)
    return normalized


def _validate_engine_payload(
    payload: object,
    *,
    symbol: str,
    timeframe: str,
    cycle_started_at: datetime,
    observed_at: datetime,
) -> tuple[dict[str, Any], datetime]:
    if type(payload) is not dict or set(payload) != _ENGINE_FIELDS:
        raise _contract_error("confluence_envelope_schema_invalid")
    if payload.get("schema_version") != altdata_confluence_engine.SCHEMA_VERSION:
        raise _contract_error("confluence_schema_version_invalid")
    if type(payload.get("symbol")) is not str or payload.get("symbol") != symbol:
        raise _contract_error("confluence_symbol_invalid")
    if type(payload.get("timeframe")) is not str or payload.get("timeframe") != timeframe:
        raise _contract_error("confluence_timeframe_invalid")

    raw_cycle_started_at = payload.get("cycle_started_at")
    raw_generated_at = payload.get("generated_at")
    parsed_cycle_started_at = _parse_utc(raw_cycle_started_at)
    generated_at = _parse_utc(raw_generated_at)
    if (
        parsed_cycle_started_at is None
        or generated_at is None
        or raw_cycle_started_at != _utc_text(cycle_started_at)
        or payload.get("generated_utc") != raw_generated_at
        or not cycle_started_at <= observed_at <= generated_at
    ):
        raise _contract_error("confluence_clock_order_invalid")

    for name in (
        "actual_payload_present",
        "core_system_blocked",
        "decision_time_safe",
        "heartbeat_only",
        "raw_key_exposed",
        "santiment_removed",
        "single_provider_can_approve",
    ):
        if type(payload.get(name)) is not bool:
            raise _contract_error(f"confluence_{name}_type_invalid")
    if payload["core_system_blocked"] is not False or payload["raw_key_exposed"] is not False:
        raise _contract_error("confluence_static_safety_contract_invalid")
    if (
        payload["santiment_removed"] is not True
        or payload["single_provider_can_approve"] is not False
    ):
        raise _contract_error("confluence_static_provider_contract_invalid")

    features = payload.get("features")
    if type(features) is not dict or set(features) != _CONFLUENCE_FEATURES:
        raise _contract_error("confluence_feature_schema_invalid")
    for name, raw in features.items():
        if type(name) is not str or type(raw) not in (int, float, type(None)):
            raise _contract_error("confluence_feature_type_invalid")
        if raw is not None:
            try:
                finite = math.isfinite(float(raw))
            except (OverflowError, TypeError, ValueError):
                finite = False
            if not finite:
                raise _contract_error("confluence_feature_value_invalid")
    missing_flags = _strict_string_list(payload, "missing_feature_flags")
    if set(missing_flags) != {name for name, value in features.items() if value is None}:
        raise _contract_error("confluence_feature_mask_invalid")
    _strict_string_list(payload, "stale_feature_flags")

    provider_lists = {
        name: _strict_string_list(payload, name)
        for name in (
            "providers_invalid",
            "providers_loaded_fresh",
            "providers_missing",
            "providers_noncontributing",
            "providers_present",
            "providers_stale",
        )
    }
    provider_set = set(_PROVIDERS)
    if any(set(values).difference(provider_set) for values in provider_lists.values()):
        raise _contract_error("confluence_provider_identity_invalid")
    loaded = set(provider_lists["providers_loaded_fresh"])
    missing = set(provider_lists["providers_missing"])
    stale = set(provider_lists["providers_stale"])
    contributing = set(provider_lists["providers_present"])
    noncontributing = set(provider_lists["providers_noncontributing"])
    if (
        loaded.intersection(missing | stale)
        or missing.intersection(stale)
        or loaded | missing | stale != provider_set
        or not contributing.issubset(loaded)
        or noncontributing != loaded.difference(contributing)
    ):
        raise _contract_error("confluence_provider_partition_invalid")

    rejection_reasons = payload.get("provider_input_rejection_reasons")
    if type(rejection_reasons) is not dict or any(
        type(name) is not str or type(reason) is not str or not reason
        for name, reason in rejection_reasons.items()
    ):
        raise _contract_error("confluence_provider_rejections_invalid")
    if set(rejection_reasons) != set(provider_lists["providers_invalid"]):
        raise _contract_error("confluence_provider_rejection_identity_invalid")
    if _strict_string_list(payload, "envelope_rejection_reasons"):
        raise _contract_error("confluence_envelope_rejected")

    provider_cutoffs = payload.get("provider_feature_cutoffs")
    if type(provider_cutoffs) is not dict or set(provider_cutoffs) != provider_set:
        raise _contract_error("confluence_provider_cutoff_schema_invalid")
    parsed_cutoffs: dict[str, datetime | None] = {}
    for provider, raw_cutoff in provider_cutoffs.items():
        cutoff = None if raw_cutoff is None else _parse_utc(raw_cutoff)
        if (raw_cutoff is not None and cutoff is None) or (
            cutoff is not None and cutoff > observed_at
        ):
            raise _contract_error("confluence_provider_cutoff_invalid")
        parsed_cutoffs[provider] = cutoff

    raw_feature_cutoff = payload.get("feature_cutoff")
    feature_cutoff = None if raw_feature_cutoff is None else _parse_utc(raw_feature_cutoff)
    if (raw_feature_cutoff is not None and feature_cutoff is None) or (
        feature_cutoff is not None and feature_cutoff > observed_at
    ):
        raise _contract_error("confluence_feature_cutoff_invalid")
    contributing_cutoffs = [parsed_cutoffs[name] for name in contributing]
    if contributing and (
        any(value is None for value in contributing_cutoffs) or feature_cutoff is None
    ):
        raise _contract_error("confluence_contributing_cutoff_missing")
    if contributing_cutoffs and feature_cutoff != max(
        value for value in contributing_cutoffs if value
    ):
        raise _contract_error("confluence_feature_cutoff_lineage_invalid")
    if not contributing and feature_cutoff is not None:
        raise _contract_error("confluence_empty_feature_cutoff_invalid")

    actual_payload_present = payload["actual_payload_present"]
    if actual_payload_present is not bool(contributing):
        raise _contract_error("confluence_actual_payload_contract_invalid")
    if payload["heartbeat_only"] is not (not actual_payload_present):
        raise _contract_error("confluence_heartbeat_contract_invalid")
    if not actual_payload_present and any(value is not None for value in features.values()):
        raise _contract_error("confluence_empty_payload_zero_fill_invalid")
    if payload["decision_time_safe"] is True and (
        not actual_payload_present
        or feature_cutoff is None
        or provider_lists["providers_invalid"]
    ):
        raise _contract_error("confluence_decision_time_safety_invalid")

    for name in (
        "directional_long_agreeing_provider_count",
        "directional_short_agreeing_provider_count",
    ):
        if type(payload.get(name)) is not int or payload[name] < 0:
            raise _contract_error(f"confluence_{name}_invalid")
    votes = payload.get("provider_direction_votes")
    if type(votes) is not dict or any(name not in provider_set for name in votes):
        raise _contract_error("confluence_direction_votes_invalid")
    long_count = 0
    short_count = 0
    for provider, vote in votes.items():
        if (
            type(provider) is not str
            or type(vote) is not dict
            or set(vote) != {"direction", "strength"}
            or type(vote.get("direction")) is not str
            or vote["direction"] not in {"LONG", "SHORT"}
            or type(vote.get("strength")) not in (int, float)
            or not math.isfinite(float(vote["strength"]))
        ):
            raise _contract_error("confluence_direction_vote_value_invalid")
        long_count += vote["direction"] == "LONG"
        short_count += vote["direction"] == "SHORT"
    if (
        payload["directional_long_agreeing_provider_count"] != long_count
        or payload["directional_short_agreeing_provider_count"] != short_count
    ):
        raise _contract_error("confluence_direction_vote_count_invalid")

    if payload.get("allowed_actions") != list(altdata_confluence_engine.ALLOWED_ACTIONS):
        raise _contract_error("confluence_allowed_actions_invalid")
    if payload.get("forbidden_actions") != list(altdata_confluence_engine.FORBIDDEN_ACTIONS):
        raise _contract_error("confluence_forbidden_actions_invalid")
    return payload, generated_at


def rebuild_canonical_confluence(
    redis_client: Any,
    *,
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    """Read canonical provider bridges and return a validated reconstruction.

    ``observed_at`` is captured after all provider reads. ``generated_at`` is
    captured after reconstruction, validation, and lineage assembly.
    ``available_at`` is captured only after the final identity record exists.
    Invalid, unavailable, and stale providers remain masked; they are never
    converted to numeric zeroes.
    """

    symbol = _validate_identity_argument(name="symbol", value=symbol, pattern=_SYMBOL)
    timeframe = _validate_identity_argument(
        name="timeframe",
        value=timeframe,
        pattern=_TIMEFRAME,
    )
    cycle_started_at = _utc_now()

    raw_inputs: dict[str, object] = {
        "coinglass": provider_feature_bridge.load_coinglass_input(
            redis_client,
            symbol,
            timeframe,
        ),
        "moralis": provider_feature_bridge.load_moralis_input(
            redis_client,
            symbol,
            timeframe,
        ),
        "coinank": provider_feature_bridge.load_coinank_input(
            redis_client,
            symbol,
            timeframe,
        ),
    }
    observed_at = _utc_now()
    if observed_at < cycle_started_at:
        raise _contract_error("consumer_observation_clock_order_invalid")

    normalized_inputs: dict[str, ProviderInput] = {}
    provider_rejections: dict[str, str | None] = {}
    for provider in _PROVIDERS:
        normalized, rejection = _normalize_provider_input(
            provider,
            raw_inputs[provider],
            observed_at=observed_at,
        )
        normalized_inputs[provider] = normalized
        provider_rejections[provider] = rejection

    rebuilt = altdata_confluence_engine.build_confluence(
        symbol=symbol,
        timeframe=timeframe,
        coinglass=normalized_inputs["coinglass"],
        moralis=normalized_inputs["moralis"],
        coinank=normalized_inputs["coinank"],
        generated_utc=_utc_text(cycle_started_at),
    )
    rebuilt = _mask_empty_composite(rebuilt) if type(rebuilt) is dict else rebuilt
    validated, engine_generated_at = _validate_engine_payload(
        rebuilt,
        symbol=symbol,
        timeframe=timeframe,
        cycle_started_at=cycle_started_at,
        observed_at=observed_at,
    )

    loaded_fresh = set(validated["providers_loaded_fresh"])
    contributing = set(validated["providers_present"])
    provider_lineage: dict[str, dict[str, Any]] = {}
    provider_identity_digests: dict[str, str] = {}
    for provider in _PROVIDERS:
        normalized = normalized_inputs[provider]
        rejection = provider_rejections[provider]
        identity = _identity_record(
            _provider_identity_material(
                normalized,
                validation_rejection=rejection,
            )
        )
        provider_identity_digests[provider] = identity["digest"]
        if rejection is not None:
            mask_reason = rejection
        elif not normalized.present:
            mask_reason = "canonical_loader_absent_or_source_payload_rejected"
        elif normalized.stale:
            mask_reason = "stale_at_consumer_observation"
        else:
            mask_reason = None
        provider_lineage[provider] = {
            "provider": provider,
            "canonical_loader_present": normalized.present,
            "canonical_loader_stale": normalized.stale,
            "boundary_contract_valid": rejection is None,
            "admitted_as_fresh_input": provider in loaded_fresh,
            "contributed_to_confluence": provider in contributing,
            "masked": provider not in loaded_fresh,
            "mask_reason": mask_reason,
            "feature_cutoff": normalized.feature_cutoff,
            "available_at": normalized.available_at,
            "generated_at": normalized.generated_at,
            "feature_names": sorted(normalized.features),
            "feature_count": len(normalized.features),
            "missing_feature_flags": list(normalized.missing_feature_flags),
            "stale_feature_flags": list(normalized.stale_feature_flags),
            "content_identity": identity,
        }

    boundary_generated_at = _utc_now()
    if boundary_generated_at < engine_generated_at:
        raise _contract_error("boundary_generation_clock_order_invalid")

    result = dict(validated)
    result.update(
        {
            "boundary_schema_version": BOUNDARY_SCHEMA_VERSION,
            "observed_at": _utc_text(observed_at),
            "confluence_engine_generated_at": _utc_text(engine_generated_at),
            "generated_at": _utc_text(boundary_generated_at),
            "generated_utc": _utc_text(boundary_generated_at),
            "provider_lineage": provider_lineage,
            "reconstructed_from_canonical_provider_inputs": True,
            "cached_confluence_consumed": False,
            "timestamp_semantics": {
                "cycle_started_at": "consumer_rebuild_started_before_provider_reads",
                "observed_at": "consumer_completed_canonical_provider_reads",
                "generated_at": "validated_in_process_reconstruction_and_lineage_completed",
                "available_at": "completed_boundary_envelope_became_available_to_caller",
                "feature_cutoff": "latest_event_cutoff_of_contributing_provider_inputs",
            },
        }
    )
    composite_identity_material = {
        "schema_version": result["schema_version"],
        "boundary_schema_version": BOUNDARY_SCHEMA_VERSION,
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_cutoff": result["feature_cutoff"],
        "features": result["features"],
        "missing_feature_flags": result["missing_feature_flags"],
        "stale_feature_flags": result["stale_feature_flags"],
        "providers_present": result["providers_present"],
        "providers_loaded_fresh": result["providers_loaded_fresh"],
        "providers_missing": result["providers_missing"],
        "providers_stale": result["providers_stale"],
        "provider_identity_digests": provider_identity_digests,
    }
    result["content_identity"] = _identity_record(composite_identity_material)

    available_at = _utc_now()
    if available_at < boundary_generated_at:
        raise _contract_error("boundary_availability_clock_order_invalid")
    result["available_at"] = _utc_text(available_at)
    return result
