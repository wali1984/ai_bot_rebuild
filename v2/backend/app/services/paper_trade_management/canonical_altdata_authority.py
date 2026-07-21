"""Canonical alt-data authority boundary for the paper preemptive path.

Optional missing, stale, malformed, or unavailable alt-data is explicitly
masked and never replaced with zeroes.  If alt-data is asserted present, its
admission evidence must come from the canonical in-process reconstruction.
Content hashes are observational identity only, never authentication.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from v2.backend.app.services.altdata.canonical_confluence_consumer import (
    BOUNDARY_SCHEMA_VERSION,
    IDENTITY_ROLE,
    CanonicalConfluenceContractError,
    rebuild_canonical_confluence,
)

_PROVIDERS = ("coinglass", "moralis", "coinank")
_PROVIDER_SET = set(_PROVIDERS)
_IDENTITY_SOURCE = "canonical_confluence_boundary_non_authoritative_content_identity"

CANONICAL_ALTDATA_DECISION_CONTEXT_FIELDS = (
    "altdata_feature_cutoff",
    "altdata_observed_at",
    "altdata_confluence_engine_generated_at",
    "altdata_generated_at",
    "altdata_available_at",
    "altdata_providers_present",
    "provider_features_used",
    "provider_features_missing",
    "coinglass_feature_hash",
    "moralis_feature_hash",
    "coinank_feature_hash",
    "altdata_confluence_hash",
    "altdata_provider_hash_source",
    "altdata_schema_version",
    "altdata_boundary_schema_version",
    "altdata_actual_payload_present",
    "altdata_decision_time_safe",
    "altdata_canonical_reconstruction_attempted",
    "altdata_canonical_reconstruction_valid",
    "altdata_canonical_reconstruction_admitted",
    "altdata_reconstructed_from_canonical_provider_inputs",
    "altdata_cached_confluence_consumed",
    "altdata_raw_provider_fallback_consumed",
    "altdata_boundary_error_masked",
    "altdata_reconstruction_mask_reason",
    "altdata_content_identity",
    "altdata_identity_hash_role",
    "altdata_identity_hash_authenticates_source",
    "altdata_identity_hash_authorizes_consumption",
    "altdata_identity_hash_is_cryptographic_proof",
    "altdata_identity_hash_is_signature",
    "altdata_provider_lineage",
)


def _canonical_utc(value: Any) -> datetime | None:
    if type(value) is not str or "T" not in value or not value.endswith(("Z", "+00:00")):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        return None
    return parsed.astimezone(UTC)


def _identity_rejection_reasons(identity: Any, *, prefix: str) -> list[str]:
    if not isinstance(identity, Mapping):
        return [f"{prefix}_IDENTITY_MISSING"]
    reasons: list[str] = []
    digest = identity.get("digest")
    if type(digest) is not str or len(digest) != 64:
        reasons.append(f"{prefix}_IDENTITY_DIGEST_INVALID")
    else:
        try:
            int(digest, 16)
        except ValueError:
            reasons.append(f"{prefix}_IDENTITY_DIGEST_INVALID")
    if identity.get("algorithm") != "sha256":
        reasons.append(f"{prefix}_IDENTITY_ALGORITHM_INVALID")
    if identity.get("role") != IDENTITY_ROLE:
        reasons.append(f"{prefix}_IDENTITY_ROLE_INVALID")
    if any(
        identity.get(field) is not False
        for field in (
            "authenticates_source",
            "authorizes_consumption",
            "is_cryptographic_proof",
            "is_signature",
        )
    ):
        reasons.append(f"{prefix}_IDENTITY_AUTHORITY_SEMANTICS_INVALID")
    return reasons


def _identity_digest(identity: Any) -> str | None:
    if not isinstance(identity, Mapping):
        return None
    digest = identity.get("digest")
    return digest if type(digest) is str and digest else None


def _provider_identity_digest(
    provider_lineage: Mapping[str, Any],
    provider: str,
) -> str | None:
    row = provider_lineage.get(provider)
    if not isinstance(row, Mapping) or row.get("canonical_loader_present") is not True:
        return None
    return _identity_digest(row.get("content_identity"))


def _normalized_lineage(
    confluence: Mapping[str, Any] | None,
    *,
    reconstruction_error: str | None = None,
) -> dict[str, Any]:
    payload = dict(confluence) if isinstance(confluence, Mapping) else {}
    features = payload.get("features")
    feature_map = features if isinstance(features, Mapping) else {}
    raw_provider_lineage = payload.get("provider_lineage")
    provider_lineage = (
        {
            name: dict(row)
            for name, row in raw_provider_lineage.items()
            if type(name) is str and isinstance(row, Mapping)
        }
        if isinstance(raw_provider_lineage, Mapping)
        else {}
    )
    content_identity = (
        dict(payload["content_identity"])
        if isinstance(payload.get("content_identity"), Mapping)
        else {}
    )
    reconstructed = payload.get("reconstructed_from_canonical_provider_inputs") is True
    cached_consumed = payload.get("cached_confluence_consumed") is True
    actual_payload_present = payload.get("actual_payload_present") is True
    decision_time_safe = payload.get("decision_time_safe") is True
    provider_lineage_contract_valid = bool(
        set(provider_lineage) == _PROVIDER_SET
        and all(
            row.get("provider") == provider
            and not _identity_rejection_reasons(
                row.get("content_identity"),
                prefix=f"ALTDATA_{provider.upper()}",
            )
            for provider, row in provider_lineage.items()
        )
    )
    clock_names = [
        "observed_at",
        "confluence_engine_generated_at",
        "generated_at",
        "available_at",
    ]
    if actual_payload_present:
        clock_names.insert(0, "feature_cutoff")
    clocks = [_canonical_utc(payload.get(name)) for name in clock_names]
    valid_clocks = [value for value in clocks if value is not None]
    clock_contract_valid = bool(
        len(valid_clocks) == len(clocks) and valid_clocks == sorted(valid_clocks)
    )
    boundary_contract_valid = bool(
        payload.get("schema_version") == "altdata_confluence_v1"
        and payload.get("boundary_schema_version") == BOUNDARY_SCHEMA_VERSION
        and reconstructed
        and payload.get("cached_confluence_consumed") is False
        and not cached_consumed
        and provider_lineage_contract_valid
        and clock_contract_valid
        and not _identity_rejection_reasons(
            content_identity,
            prefix="ALTDATA_CONFLUENCE",
        )
    )
    admitted = bool(
        boundary_contract_valid
        and actual_payload_present
        and decision_time_safe
        and reconstruction_error is None
    )
    if reconstruction_error is not None:
        mask_reason = reconstruction_error
    elif not boundary_contract_valid:
        mask_reason = "canonical_reconstruction_contract_invalid"
    elif not actual_payload_present:
        mask_reason = "no_fresh_contributing_provider"
    elif not decision_time_safe:
        mask_reason = "canonical_reconstruction_not_decision_time_safe"
    else:
        mask_reason = None
    return {
        "provider_features_used": sorted(
            name for name, value in feature_map.items() if value is not None
        ),
        "provider_features_missing": sorted(
            name for name, value in feature_map.items() if value is None
        ),
        "coinglass_feature_hash": _provider_identity_digest(
            provider_lineage,
            "coinglass",
        ),
        "moralis_feature_hash": _provider_identity_digest(
            provider_lineage,
            "moralis",
        ),
        "coinank_feature_hash": _provider_identity_digest(
            provider_lineage,
            "coinank",
        ),
        "altdata_confluence_hash": _identity_digest(content_identity),
        "altdata_provider_hash_source": _IDENTITY_SOURCE,
        "altdata_schema_version": payload.get("schema_version"),
        "altdata_boundary_schema_version": payload.get("boundary_schema_version"),
        "altdata_feature_cutoff": payload.get("feature_cutoff"),
        "altdata_observed_at": payload.get("observed_at"),
        "altdata_confluence_engine_generated_at": payload.get("confluence_engine_generated_at"),
        "altdata_generated_at": payload.get("generated_at"),
        "altdata_available_at": payload.get("available_at"),
        "altdata_actual_payload_present": actual_payload_present,
        "altdata_decision_time_safe": decision_time_safe,
        "altdata_canonical_reconstruction_attempted": True,
        "altdata_canonical_reconstruction_valid": boundary_contract_valid,
        "altdata_canonical_reconstruction_admitted": admitted,
        "altdata_reconstructed_from_canonical_provider_inputs": reconstructed,
        "altdata_cached_confluence_consumed": cached_consumed,
        "altdata_raw_provider_fallback_consumed": False,
        "altdata_boundary_error_masked": reconstruction_error is not None,
        "altdata_reconstruction_mask_reason": mask_reason,
        "altdata_content_identity": content_identity or None,
        "altdata_identity_hash_role": content_identity.get("role"),
        "altdata_identity_hash_authenticates_source": content_identity.get("authenticates_source"),
        "altdata_identity_hash_authorizes_consumption": content_identity.get(
            "authorizes_consumption"
        ),
        "altdata_identity_hash_is_cryptographic_proof": content_identity.get(
            "is_cryptographic_proof"
        ),
        "altdata_identity_hash_is_signature": content_identity.get("is_signature"),
        "altdata_provider_lineage": provider_lineage,
    }


def resolve_paper_canonical_altdata(
    redis_client: Any,
    *,
    symbol: str,
    timeframe: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Rebuild paper alt-data once and mask every failure without fallback."""

    try:
        rebuilt = rebuild_canonical_confluence(
            redis_client,
            symbol=symbol,
            timeframe=timeframe,
        )
    except CanonicalConfluenceContractError:
        return None, _normalized_lineage(
            None,
            reconstruction_error="canonical_confluence_contract_error_masked",
        )
    except Exception:
        return None, _normalized_lineage(
            None,
            reconstruction_error="canonical_confluence_boundary_unavailable_masked",
        )

    lineage = _normalized_lineage(rebuilt)
    admitted = lineage.get("altdata_canonical_reconstruction_admitted") is True
    return (rebuilt if admitted else None), lineage


def paper_altdata_admission_rejection_reasons(
    intent: Mapping[str, Any],
) -> list[str]:
    """Validate canonical evidence only when alt-data presence is asserted."""

    present = intent.get("altdata_confluence_present")
    if present is None or present is False:
        return []
    if present is not True:
        return ["ALTDATA_CANONICAL_PRESENCE_TYPE_INVALID"]

    reasons: list[str] = []
    required_true = (
        "altdata_actual_payload_present",
        "altdata_decision_time_safe",
        "altdata_canonical_reconstruction_attempted",
        "altdata_canonical_reconstruction_valid",
        "altdata_canonical_reconstruction_admitted",
        "altdata_reconstructed_from_canonical_provider_inputs",
    )
    for field in required_true:
        if intent.get(field) is not True:
            reasons.append(f"{field.upper()}_NOT_TRUE")
    required_false = (
        "altdata_cached_confluence_consumed",
        "altdata_raw_provider_fallback_consumed",
        "altdata_boundary_error_masked",
        "altdata_identity_hash_authenticates_source",
        "altdata_identity_hash_authorizes_consumption",
        "altdata_identity_hash_is_cryptographic_proof",
        "altdata_identity_hash_is_signature",
    )
    for field in required_false:
        if intent.get(field) is not False:
            reasons.append(f"{field.upper()}_NOT_FALSE")
    if intent.get("altdata_schema_version") != "altdata_confluence_v1":
        reasons.append("ALTDATA_CANONICAL_SCHEMA_INVALID")
    if intent.get("altdata_boundary_schema_version") != BOUNDARY_SCHEMA_VERSION:
        reasons.append("ALTDATA_CANONICAL_BOUNDARY_SCHEMA_INVALID")
    if intent.get("altdata_identity_hash_role") != IDENTITY_ROLE:
        reasons.append("ALTDATA_IDENTITY_ROLE_INVALID")
    if intent.get("altdata_provider_hash_source") != _IDENTITY_SOURCE:
        reasons.append("ALTDATA_IDENTITY_SOURCE_INVALID")
    if intent.get("altdata_reconstruction_mask_reason") not in (None, ""):
        reasons.append("ALTDATA_PRESENT_PAYLOAD_HAS_MASK_REASON")

    identity = intent.get("altdata_content_identity")
    reasons.extend(_identity_rejection_reasons(identity, prefix="ALTDATA_CONFLUENCE"))
    if isinstance(identity, Mapping) and intent.get("altdata_confluence_hash") != identity.get(
        "digest"
    ):
        reasons.append("ALTDATA_CONFLUENCE_IDENTITY_ALIAS_MISMATCH")

    provider_lineage = intent.get("altdata_provider_lineage")
    if not isinstance(provider_lineage, Mapping) or set(provider_lineage) != _PROVIDER_SET:
        reasons.append("ALTDATA_CANONICAL_PROVIDER_LINEAGE_INVALID")
    else:
        for provider in _PROVIDERS:
            row = provider_lineage.get(provider)
            if not isinstance(row, Mapping) or row.get("provider") != provider:
                reasons.append(f"ALTDATA_{provider.upper()}_LINEAGE_INVALID")
                continue
            reasons.extend(
                _identity_rejection_reasons(
                    row.get("content_identity"),
                    prefix=f"ALTDATA_{provider.upper()}",
                )
            )

    clock_fields = (
        "altdata_feature_cutoff",
        "altdata_observed_at",
        "altdata_confluence_engine_generated_at",
        "altdata_generated_at",
        "altdata_available_at",
    )
    clocks = [_canonical_utc(intent.get(field)) for field in clock_fields]
    if any(value is None for value in clocks):
        reasons.append("ALTDATA_CANONICAL_CLOCK_MISSING_OR_INVALID")
    else:
        ordered_clocks = [value for value in clocks if value is not None]
        if ordered_clocks != sorted(ordered_clocks):
            reasons.append("ALTDATA_CANONICAL_CLOCK_ORDER_INVALID")
    return sorted(set(reasons))
