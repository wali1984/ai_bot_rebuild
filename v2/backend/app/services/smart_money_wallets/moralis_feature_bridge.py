"""Moralis smart-money feature bridge with receipt-gated authority."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from app.services.smart_money_wallets.normalizer import (
    MORALIS_ABI_FEATURE_NAMES,
    MORALIS_DIAGNOSTIC_NAMES,
)

MORALIS_FEATURE_KEY = "v2:features:moralis:{symbol}:{timeframe}"
MORALIS_PROVIDER_FEATURE_KEY = "v2:features:provider:moralis:{symbol}:{timeframe}"
SMART_MONEY_SIGNAL_KEY = "v2:smart_money:signals:{symbol}"
MORALIS_FEATURE_BRIDGE_STATUS_KEY = "v2:provider:moralis:feature_bridge_status"
MORALIS_SYMBOL_SCORE_KEY = "v2:provider:moralis:symbol_score:{symbol}"
MORALIS_FANOUT_COMPLETION_KEY = "v2:provider:moralis:fanout_completion:{symbol}:{timeframe}"

# Compatibility export used by existing callers.  It now means the exact
# seven OPTIONAL_EVENT_DEPENDENT model slots, not fifteen mandatory fields.
FEATURE_NAMES = MORALIS_ABI_FEATURE_NAMES
OPTIONAL_MORALIS_FEATURES = FEATURE_NAMES
REQUIRED_MORALIS_FEATURES: tuple[str, ...] = ()
DIAGNOSTIC_FEATURE_NAMES = MORALIS_DIAGNOSTIC_NAMES

# Immutable admission state, not an environment switch.  Both remain false
# until exact post-commit source/publication receipts are implemented and every
# consumer proves it verifies them.
MORALIS_TRAINER_CONSUMPTION_BOUND = False
MORALIS_CONSUMER_RECEIPTS_BOUND = False
MORALIS_POSTCOMMIT_RECEIPT_BOUND = False
MAX_UPSTREAM_TEMPORAL_REJECTION_REASONS = 64
MAX_UPSTREAM_TEMPORAL_REJECTION_REASON_BYTES = 256
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL_KEY_SEGMENT_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{0,31}$")
_TIMEFRAME_KEY_SEGMENT_RE = re.compile(r"^[1-9][0-9]{0,5}[smhdwM]$")
_MAX_JSON_DEPTH = 16
_MAX_JSON_LIST_ITEMS = 1000
_MAX_JSON_OBJECT_FIELDS = 512
_MAX_JSON_STRING_BYTES = 16_384
_MAX_JSON_TOTAL_NODES = 20_000
_MAX_JSON_BYTES = 4_194_304

_NON_AUTHORITATIVE_OPTIONAL_FALSE_FIELDS = frozenset(
    {
        "actual_consumption",
        "actual_payload_present",
        "trainer_consumption",
        "provider_tensor_consumption",
        "ppo_consumption",
        "masa_consumption",
        "risk_consumption",
        "orchestrator_consumption",
        "allocator_consumption",
        "paper_consumption",
        "live_dryrun_consumption",
        "feedback_attribution",
        "trainer_consumption_prerequisites_bound",
        "consumer_receipts_bound",
        "publication_atomic",
        "publication_committed",
        "consumer_eligible",
        "trainer_consumable",
        "trainer_admission_granted",
        "admitted_ready",
        "feature_bridge_ready",
        "provider_ready",
        "source_ready",
        "source_feature_bridge_ready",
        "source_payload_temporally_valid",
        "source_temporal_contract_valid",
        "temporal_contract_valid",
        "trainer_temporal_contract_valid",
        "decision_time_safe",
        "trainer_decision_time_safe",
        "moralis_can_approve_trade_alone",
        "single_provider_can_approve",
        "provider_data_can_approve_trade_alone",
        "can_boost_confidence_modestly",
        "can_block_reduce_size_or_require_hedge",
        "live_execution_authorized",
        "exchange_action_taken",
        "places_real_order",
        "writes_exchange_orders",
        "valid_for_trainer",
        "valid_for_prediction",
        "valid_for_risk",
        "valid_for_orchestrator",
        "valid_for_allocator",
        "valid_for_paper",
        "valid_for_live",
    }
)
_EXPECTED_MISSING_MASK = {name: True for name in FEATURE_NAMES}


def _optional_authority_claims_false(value: Mapping[str, Any]) -> bool:
    return all(
        name not in value or value.get(name) is False
        for name in _NON_AUTHORITATIVE_OPTIONAL_FALSE_FIELDS
    )


def _optional_strict_zero(value: Mapping[str, Any], name: str) -> bool:
    return name not in value or (type(value.get(name)) is int and value.get(name) == 0)


def build_moralis_feature_payload(
    *,
    symbol: str,
    timeframe: str = "1m",
    features: Mapping[str, Any] | None = None,
    diagnostic_features: Mapping[str, Any] | None = None,
    feature_evidence: Mapping[str, Any] | None = None,
    diagnostic_evidence: Mapping[str, Any] | None = None,
    feature_rejection_reasons: Mapping[str, Any] | None = None,
    feature_origins: Mapping[str, Any] | None = None,
    diagnostic_origins: Mapping[str, Any] | None = None,
    feature_conflicts: Mapping[str, Any] | None = None,
    source_state_reasons: Mapping[str, Any] | None = None,
    token_map_count: int = 0,
    wallet_watchlist_count: int = 0,
    actual_payload_present: bool = False,
    event_time: str | None = None,
    feature_cutoff: str | None = None,
    ingested_at: str | None = None,
    available_at: str | None = None,
    ttl_seconds: int = 3600,
    stale_after: int | None = None,
    compute_unit_status: Mapping[str, Any] | None = None,
    upstream_temporal_rejection_reasons: Sequence[str] | None = None,
    generated_at_override: str | None = None,
    expires_at_override: str | None = None,
    fanout_generation_id: str | None = None,
    aggregate_artifact_sha256: str | None = None,
    source_provenance_expires_at: str | None = None,
    raw_transport_record_count: int = 0,
    source_feature_claim_count: int | None = None,
    source_diagnostic_claim_count: int | None = None,
) -> dict[str, Any]:
    ttl = max(1, int(ttl_seconds))
    stale = max(1, int(stale_after or ttl))
    generated_at = generated_at_override or _now()
    if _parse_utc(generated_at) is None:
        generated_at = _now()
    source_numeric = _numeric_subset(features or {}, FEATURE_NAMES)
    diagnostics = _numeric_subset(
        diagnostic_features or {},
        DIAGNOSTIC_FEATURE_NAMES,
    )
    conflicts = _bounded_feature_conflicts(feature_conflicts)
    source_states = _bounded_source_states(source_state_reasons)
    for name in conflicts:
        source_numeric.pop(name, None)

    source_evidence = _bounded_named_mappings(feature_evidence, FEATURE_NAMES)
    source_origins = _bounded_named_mappings(feature_origins, FEATURE_NAMES)
    diagnostics_evidence = _bounded_named_mappings(
        diagnostic_evidence,
        DIAGNOSTIC_FEATURE_NAMES,
    )
    diagnostics_origins = _bounded_named_mappings(
        diagnostic_origins,
        DIAGNOSTIC_FEATURE_NAMES,
    )
    rejection_map = _bounded_feature_rejection_reasons(feature_rejection_reasons)
    upstream_rejections = _bounded_upstream_temporal_rejections(upstream_temporal_rejection_reasons)
    temporal = _validate_source_clock_contract(
        event_time=event_time,
        feature_cutoff=feature_cutoff,
        ingested_at=ingested_at,
        generated_at=generated_at,
        supplied_available_at=available_at,
        require_source_clocks=bool(actual_payload_present),
    )
    temporal_rejections = sorted(set(temporal["rejection_reasons"]) | set(upstream_rejections))
    source_clock_order_valid = not [
        reason
        for reason in temporal_rejections
        if reason
        not in {
            "POSTCOMMIT_RECEIPT_UNBOUND",
            "SUPPLIED_AVAILABLE_AT_IGNORED_NO_POSTCOMMIT_RECEIPT",
        }
    ]
    slot_readiness = _slot_readiness(
        source_numeric=source_numeric,
        feature_evidence=source_evidence,
        feature_origins=source_origins,
        feature_conflicts=conflicts,
        feature_rejection_reasons=rejection_map,
        source_clock_order_valid=source_clock_order_valid,
    )
    source_missing = [name for name in FEATURE_NAMES if name not in source_numeric]
    # Consumer/admitted values are deliberately empty until receipts bind.
    # Therefore every ABI slot is missing from the admitted tensor even when a
    # source-side observation exists for audit.
    admitted_missing = list(FEATURE_NAMES)
    lineage_ready = [
        name
        for name, row in slot_readiness.items()
        if row["semantic_value_present"] is True
        and row["semantic_evidence_present"] is True
        and row["source_origin_bound"] is True
        and row["source_clock_order_valid"] is True
    ]
    has_lists = token_map_count > 0 and wallet_watchlist_count > 0
    transport_actual = bool(actual_payload_present)
    semantic_observation_present = bool(source_numeric or diagnostics)
    source_has_actual = bool(transport_actual and semantic_observation_present)
    source_status = _source_status(
        has_lists=has_lists,
        source_has_actual=source_has_actual,
        source_clock_order_valid=source_clock_order_valid,
        clock_rejection_present=bool(
            (actual_payload_present or upstream_rejections) and not source_clock_order_valid
        ),
        source_state_reasons=source_states,
        conflicts=conflicts,
        token_map_count=token_map_count,
        wallet_watchlist_count=wallet_watchlist_count,
    )
    isolation_active = _isolation_active()
    # No consumer-facing value exists until the exact source bytes, the exact
    # committed Redis bytes, and a durable post-commit receipt are bound.
    admitted_numeric: dict[str, float] = {}
    observed_feature_claim_count = max(
        len(source_numeric),
        max(0, int(source_feature_claim_count or 0)),
    )
    observed_diagnostic_claim_count = max(
        len(diagnostics),
        max(0, int(source_diagnostic_claim_count or 0)),
    )
    trainer_status = "ISOLATED_BY_POLICY" if isolation_active else "RECEIPT_CONTRACT_UNBOUND"
    computed_expires_at = (
        ((_parse_utc(generated_at) or datetime.now(UTC)) + timedelta(seconds=ttl))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    expires_at = (
        expires_at_override if _parse_utc(expires_at_override) is not None else computed_expires_at
    )
    expires_clock = _parse_utc(expires_at)
    provenance_clock = _parse_utc(source_provenance_expires_at)
    if (
        expires_clock is not None
        and provenance_clock is not None
        and expires_clock > provenance_clock
    ):
        expires_at = _iso_utc(provenance_clock)
    return {
        "schema_version": "moralis_feature_bridge_v2",
        "provider": "moralis",
        "symbol": str(symbol).upper(),
        "timeframe": timeframe,
        "generated_at": temporal["generated_at"],
        "event_time": temporal["event_time"] if source_clock_order_valid else None,
        "feature_cutoff": temporal["feature_cutoff"] if source_clock_order_valid else None,
        "ingested_at": temporal["ingested_at"] if source_clock_order_valid else None,
        # An attempted or acknowledged SET is not a post-commit receipt.
        "available_at": None,
        "source_clock_order_valid": source_clock_order_valid,
        "source_temporal_contract_valid": False,
        "temporal_contract_version": "moralis_feature_temporal_contract_v3",
        "temporal_contract_valid": False,
        "trainer_temporal_contract_valid": False,
        "decision_time_safe": False,
        "trainer_decision_time_safe": False,
        "temporal_rejection_reasons": temporal_rejections,
        "source_temporal_rejection_reasons": temporal_rejections,
        "source_clock_inputs": {
            "event_time_input": event_time,
            "feature_cutoff_input": feature_cutoff,
            "ingested_at_input": ingested_at,
            "available_at_input": available_at,
        },
        "ttl_seconds": ttl,
        "stale_after": stale,
        "expires_at": expires_at,
        "source_provenance_expires_at": source_provenance_expires_at,
        "fanout_generation_id": fanout_generation_id,
        "aggregate_artifact_sha256": aggregate_artifact_sha256,
        "features": admitted_numeric,
        "source_features": source_numeric,
        "diagnostic_features": diagnostics,
        "feature_names": list(FEATURE_NAMES),
        "abi_feature_names": list(FEATURE_NAMES),
        "diagnostic_feature_names": list(DIAGNOSTIC_FEATURE_NAMES),
        "required_feature_count": 0,
        "optional_feature_count": len(FEATURE_NAMES),
        "feature_count": 0,
        "source_feature_count": len(source_numeric),
        "diagnostic_feature_count": len(diagnostics),
        "raw_transport_record_count": max(0, int(raw_transport_record_count)),
        "source_feature_claim_count": observed_feature_claim_count,
        "source_diagnostic_claim_count": observed_diagnostic_claim_count,
        "source_semantic_claim_count": (
            observed_feature_claim_count + observed_diagnostic_claim_count
        ),
        "admitted_feature_count": 0,
        "source_lineage_ready_feature_count": len(lineage_ready),
        "missing_feature_flags": admitted_missing,
        "optional_missing_feature_flags": admitted_missing,
        "stale_feature_flags": [],
        "missing_mask": {name: True for name in FEATURE_NAMES},
        "missing_mask_true": True,
        "stale_mask": {name: False for name in FEATURE_NAMES},
        "stale_mask_true": False,
        "slot_readiness": slot_readiness,
        "feature_evidence": source_evidence,
        "feature_origins": source_origins,
        "diagnostic_evidence": diagnostics_evidence,
        "diagnostic_origins": diagnostics_origins,
        "feature_conflicts": conflicts,
        "quarantined_feature_names": sorted(conflicts),
        "feature_rejection_reasons": rejection_map,
        "source_state_reasons": source_states,
        "token_map_count": int(token_map_count),
        "wallet_watchlist_count": int(wallet_watchlist_count),
        "trainer_isolation_active": isolation_active,
        "integration_configured": has_lists,
        "integration_capable": True,
        "source_ready": False,
        "admitted_ready": False,
        "actual_consumption": False,
        "trainer_consumption_prerequisites_bound": _trainer_admission_bound(),
        "consumer_receipts_bound": MORALIS_CONSUMER_RECEIPTS_BOUND,
        "postcommit_receipt_bound": MORALIS_POSTCOMMIT_RECEIPT_BOUND,
        "publication_authority": False,
        "publication_atomic": False,
        "publication_status": "NON_AUTHORITATIVE_POSTCOMMIT_RECEIPT_UNBOUND",
        "trainer_isolation_release_authority": "reviewed_code_and_exact_receipt_contract_only",
        "source_actual_payload_present": source_has_actual,
        "source_payload_temporally_valid": False,
        "source_semantic_observation_present": semantic_observation_present,
        "source_feature_observation_present": bool(source_numeric),
        "source_missing_feature_flags": source_missing,
        "source_missing_mask": {name: name in source_missing for name in FEATURE_NAMES},
        "source_missing_mask_true": bool(source_missing),
        "source_feature_bridge_ready": False,
        "source_status": source_status,
        "source_dashboard_color": "YELLOW" if source_has_actual else "GRAY",
        "trainer_admission_status": trainer_status,
        "actual_payload_present": False,
        "heartbeat_only": True,
        "provider_ready": False,
        "feature_bridge_ready": False,
        "dashboard_color": "GRAY",
        "status": trainer_status,
        "compute_unit_status": dict(compute_unit_status or {}),
        "daily_cu_used": _dig(compute_unit_status or {}, "compute_budget", "used_today"),
        "monthly_cu_used": _dig(compute_unit_status or {}, "compute_budget", "used_month"),
        "moralis_can_approve_trade_alone": False,
        "can_boost_confidence_modestly": False,
        "can_block_reduce_size_or_require_hedge": False,
        "trainer_authority": False,
        "prediction_authority": False,
        "risk_authority": False,
        "orchestrator_authority": False,
        "allocator_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "do_not_zero_fill_missing_smart_money": True,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }


def publish_moralis_feature_payload(
    redis_client: Any,
    *,
    symbol: str,
    timeframe: str = "1m",
    features: Mapping[str, Any] | None = None,
    diagnostic_features: Mapping[str, Any] | None = None,
    feature_evidence: Mapping[str, Any] | None = None,
    diagnostic_evidence: Mapping[str, Any] | None = None,
    feature_rejection_reasons: Mapping[str, Any] | None = None,
    feature_origins: Mapping[str, Any] | None = None,
    diagnostic_origins: Mapping[str, Any] | None = None,
    feature_conflicts: Mapping[str, Any] | None = None,
    source_state_reasons: Mapping[str, Any] | None = None,
    token_map_count: int = 0,
    wallet_watchlist_count: int = 0,
    actual_payload_present: bool = False,
    event_time: str | None = None,
    feature_cutoff: str | None = None,
    ingested_at: str | None = None,
    available_at: str | None = None,
    ttl_seconds: int = 3600,
    stale_after: int | None = None,
    compute_unit_status: Mapping[str, Any] | None = None,
    upstream_temporal_rejection_reasons: Sequence[str] | None = None,
    generated_at_override: str | None = None,
    expires_at_override: str | None = None,
    fanout_generation_id: str | None = None,
    aggregate_artifact_sha256: str | None = None,
    source_provenance_expires_at: str | None = None,
    raw_transport_record_count: int = 0,
    source_feature_claim_count: int | None = None,
    source_diagnostic_claim_count: int | None = None,
) -> dict[str, Any]:
    payload = build_moralis_feature_payload(
        symbol=symbol,
        timeframe=timeframe,
        features=features,
        diagnostic_features=diagnostic_features,
        feature_evidence=feature_evidence,
        diagnostic_evidence=diagnostic_evidence,
        feature_rejection_reasons=feature_rejection_reasons,
        feature_origins=feature_origins,
        diagnostic_origins=diagnostic_origins,
        feature_conflicts=feature_conflicts,
        source_state_reasons=source_state_reasons,
        token_map_count=token_map_count,
        wallet_watchlist_count=wallet_watchlist_count,
        actual_payload_present=actual_payload_present,
        event_time=event_time,
        feature_cutoff=feature_cutoff,
        ingested_at=ingested_at,
        available_at=available_at,
        ttl_seconds=ttl_seconds,
        stale_after=stale_after,
        compute_unit_status=compute_unit_status,
        upstream_temporal_rejection_reasons=upstream_temporal_rejection_reasons,
        generated_at_override=generated_at_override,
        expires_at_override=expires_at_override,
        fanout_generation_id=fanout_generation_id,
        aggregate_artifact_sha256=aggregate_artifact_sha256,
        source_provenance_expires_at=source_provenance_expires_at,
        raw_transport_record_count=raw_transport_record_count,
        source_feature_claim_count=source_feature_claim_count,
        source_diagnostic_claim_count=source_diagnostic_claim_count,
    )
    symbol_upper = str(symbol).upper()
    if not _SYMBOL_KEY_SEGMENT_RE.fullmatch(
        symbol_upper
    ) or not _TIMEFRAME_KEY_SEGMENT_RE.fullmatch(str(timeframe)):
        payload.update(
            {
                "keys_written": [],
                "planned_keys": [],
                "failed_keys": ["REDIS_KEY_SEGMENT_VALIDATION"],
                "unattempted_keys": [],
                "publication_acknowledged": False,
                "publication_attempt_status": "REDIS_KEY_SEGMENT_INVALID_NON_AUTHORITATIVE",
                "publication_artifact_sha256": {},
                "serialization_rejection_reasons": ["REDIS_KEY_SEGMENT_INVALID"],
            }
        )
        return payload
    feature_key = MORALIS_FEATURE_KEY.format(symbol=symbol_upper, timeframe=timeframe)
    provider_feature_key = MORALIS_PROVIDER_FEATURE_KEY.format(
        symbol=symbol_upper, timeframe=timeframe
    )
    signal_key = SMART_MONEY_SIGNAL_KEY.format(symbol=symbol_upper)
    score_key = MORALIS_SYMBOL_SCORE_KEY.format(symbol=symbol_upper)
    completion_key = MORALIS_FANOUT_COMPLETION_KEY.format(
        symbol=symbol_upper,
        timeframe=timeframe,
    )
    writes = (
        (feature_key, payload, ttl_seconds),
        (provider_feature_key, payload, ttl_seconds),
        (signal_key, payload, max(1, min(int(ttl_seconds), 21600))),
        (
            MORALIS_FEATURE_BRIDGE_STATUS_KEY,
            _feature_bridge_status(payload),
            max(1, min(int(ttl_seconds), 3600)),
        ),
        (score_key, _symbol_score_payload(payload), ttl_seconds),
    )
    generation_id = (
        fanout_generation_id
        if isinstance(fanout_generation_id, str) and _SHA256_RE.fullmatch(fanout_generation_id)
        else _sha256_bytes(
            _json_bytes(
                {
                    "aggregate_artifact_sha256": aggregate_artifact_sha256,
                    "expires_at": payload.get("expires_at"),
                    "symbol": symbol_upper,
                    "timeframe": timeframe,
                }
            )
        )
    )
    acknowledged: list[str] = []
    failed: list[str] = []
    unattempted: list[str] = []
    artifact_sha256: dict[str, str] = {}
    serialization_rejections: list[str] = []
    encoded_writes: list[tuple[str, bytes, int]] = []
    for index, (key, value, ttl) in enumerate(writes):
        try:
            encoded = _json_bytes(value)
        except (TypeError, ValueError) as exc:
            failed.append(key)
            unattempted.extend(item[0] for item in writes[index + 1 :])
            serialization_rejections.append(
                f"{key}:STRICT_JSON_SERIALIZATION_REJECTED:{type(exc).__name__}"
            )
            break
        encoded_writes.append((key, encoded, max(1, int(ttl))))
    if not failed:
        for index, (key, encoded, ttl) in enumerate(encoded_writes):
            if not _set_json_verified(redis_client, key, encoded, ex=ttl):
                failed.append(key)
                unattempted.extend(item[0] for item in encoded_writes[index + 1 :])
                unattempted.append(completion_key)
                break
            acknowledged.append(key)
            artifact_sha256[key] = _sha256_bytes(encoded)
    if not failed:
        # The bridge-status key is intentionally a cross-symbol observability
        # projection.  It must succeed for this publication, but a later
        # symbol is expected to replace it and therefore it cannot be part of
        # a symbol-scoped durable completion receipt.
        durable_artifact_sha256 = {
            key: digest
            for key, digest in artifact_sha256.items()
            if key != MORALIS_FEATURE_BRIDGE_STATUS_KEY
        }
        completion = {
            "schema_version": "moralis_feature_fanout_completion_v1",
            "provider": "moralis",
            "symbol": symbol_upper,
            "timeframe": timeframe,
            "fanout_generation_id": generation_id,
            "aggregate_artifact_sha256": aggregate_artifact_sha256,
            "artifact_sha256": durable_artifact_sha256,
            "planned_artifact_keys": [
                item[0] for item in writes if item[0] != MORALIS_FEATURE_BRIDGE_STATUS_KEY
            ],
            "auxiliary_observability_keys": [MORALIS_FEATURE_BRIDGE_STATUS_KEY],
            "auxiliary_observability_authority": False,
            "generated_at": payload.get("generated_at"),
            "expires_at": payload.get("expires_at"),
            "source_provenance_expires_at": source_provenance_expires_at,
            "available_at": None,
            "raw_transport_record_count": payload.get("raw_transport_record_count", 0),
            "source_feature_count": payload.get("source_feature_count", 0),
            "source_feature_claim_count": payload.get("source_feature_claim_count", 0),
            "source_diagnostic_claim_count": payload.get("source_diagnostic_claim_count", 0),
            "source_semantic_claim_count": payload.get("source_semantic_claim_count", 0),
            "admitted_feature_count": 0,
            "features": {},
            "postcommit_receipt_bound": False,
            "publication_authority": False,
            "trainer_authority": False,
            "prediction_authority": False,
            "risk_authority": False,
            "orchestrator_authority": False,
            "allocator_authority": False,
            "paper_authority": False,
            "live_authority": False,
        }
        try:
            completion_encoded = _json_bytes(completion)
        except (TypeError, ValueError) as exc:
            failed.append(completion_key)
            serialization_rejections.append(
                f"{completion_key}:STRICT_JSON_SERIALIZATION_REJECTED:{type(exc).__name__}"
            )
        else:
            if _set_json_verified(
                redis_client,
                completion_key,
                completion_encoded,
                ex=max(1, int(ttl_seconds)),
            ):
                acknowledged.append(completion_key)
                artifact_sha256[completion_key] = _sha256_bytes(completion_encoded)
            else:
                failed.append(completion_key)
    payload["keys_written"] = acknowledged
    payload["planned_keys"] = [item[0] for item in writes] + [completion_key]
    payload["failed_keys"] = failed
    payload["unattempted_keys"] = unattempted
    payload["publication_acknowledged"] = not failed and len(acknowledged) == len(writes) + 1
    payload["fanout_completion_key"] = completion_key
    payload["fanout_generation_id"] = generation_id
    payload["fanout_completion_durable"] = payload["publication_acknowledged"]
    payload["publication_attempt_status"] = (
        "COMPLETE_NON_AUTHORITATIVE"
        if payload["publication_acknowledged"]
        else "PARTIAL_WRITE_FAILED_NON_AUTHORITATIVE"
    )
    payload["publication_artifact_sha256"] = artifact_sha256
    payload["serialization_rejection_reasons"] = serialization_rejections
    return payload


def moralis_feature_fanout_keys(*, symbol: str, timeframe: str) -> tuple[str, ...]:
    symbol_upper = str(symbol).upper()
    if not _SYMBOL_KEY_SEGMENT_RE.fullmatch(symbol_upper):
        raise ValueError("invalid Moralis symbol Redis key segment")
    if not _TIMEFRAME_KEY_SEGMENT_RE.fullmatch(str(timeframe)):
        raise ValueError("invalid Moralis timeframe Redis key segment")
    return (
        MORALIS_FEATURE_KEY.format(symbol=symbol_upper, timeframe=timeframe),
        MORALIS_PROVIDER_FEATURE_KEY.format(symbol=symbol_upper, timeframe=timeframe),
        SMART_MONEY_SIGNAL_KEY.format(symbol=symbol_upper),
        MORALIS_FEATURE_BRIDGE_STATUS_KEY,
        MORALIS_SYMBOL_SCORE_KEY.format(symbol=symbol_upper),
        MORALIS_FANOUT_COMPLETION_KEY.format(symbol=symbol_upper, timeframe=timeframe),
    )


def verify_moralis_feature_fanout_completion(
    redis_client: Any,
    *,
    symbol: str,
    timeframe: str,
    aggregate_artifact_sha256: str,
    expires_at: str | None,
    observed_at: str | None = None,
) -> bool:
    """Verify a durable completion receipt and every exact fanout artifact."""

    try:
        keys = moralis_feature_fanout_keys(symbol=symbol, timeframe=timeframe)
        completion_key = keys[-1]
        raw = redis_client.get(completion_key)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="strict")
        if not isinstance(raw, str):
            return False
        if len(raw.encode("utf-8", errors="strict")) > _MAX_JSON_BYTES:
            return False
        parsed = json.loads(raw)
        if not isinstance(parsed, Mapping) or _json_bytes(parsed).decode("utf-8") != raw:
            return False
        observed_clock = _parse_utc(observed_at) if observed_at is not None else datetime.now(UTC)
        expires_clock = _parse_utc(expires_at)
        provenance_clock = _parse_utc(parsed.get("source_provenance_expires_at"))
        if (
            observed_clock is None
            or expires_clock is None
            or expires_clock <= observed_clock
            or provenance_clock is None
            or expires_clock > provenance_clock
        ):
            return False
        required_ttl = max(1, int((expires_clock - observed_clock).total_seconds()))
        artifacts = parsed.get("artifact_sha256")
        durable_keys = tuple(key for key in keys[:-1] if key != MORALIS_FEATURE_BRIDGE_STATUS_KEY)
        authority_fields = (
            "publication_authority",
            "trainer_authority",
            "prediction_authority",
            "risk_authority",
            "orchestrator_authority",
            "allocator_authority",
            "paper_authority",
            "live_authority",
        )
        if (
            parsed.get("schema_version") != "moralis_feature_fanout_completion_v1"
            or parsed.get("provider") != "moralis"
            or parsed.get("symbol") != str(symbol).upper()
            or parsed.get("timeframe") != timeframe
            or parsed.get("aggregate_artifact_sha256") != aggregate_artifact_sha256
            or parsed.get("fanout_generation_id") != aggregate_artifact_sha256
            or parsed.get("expires_at") != expires_at
            or parsed.get("features") != {}
            or parsed.get("postcommit_receipt_bound") is not False
            or type(parsed.get("admitted_feature_count")) is not int
            or parsed.get("admitted_feature_count") != 0
            or not _optional_strict_zero(parsed, "feature_count")
            or parsed.get("available_at") is not None
            or any(parsed.get(field) is not False for field in authority_fields)
            or not _optional_authority_claims_false(parsed)
            or parsed.get("planned_artifact_keys") != list(durable_keys)
            or parsed.get("auxiliary_observability_keys") != [MORALIS_FEATURE_BRIDGE_STATUS_KEY]
            or parsed.get("auxiliary_observability_authority") is not False
            or not isinstance(artifacts, Mapping)
            or set(artifacts) != set(durable_keys)
        ):
            return False
        completion_ttl = redis_client.ttl(completion_key)
        if (
            not isinstance(completion_ttl, int)
            or isinstance(completion_ttl, bool)
            or completion_ttl < required_ttl
        ):
            return False
        for key in durable_keys:
            artifact = redis_client.get(key)
            if isinstance(artifact, bytes):
                artifact = artifact.decode("utf-8", errors="strict")
            digest = artifacts.get(key)
            if (
                not isinstance(artifact, str)
                or not isinstance(digest, str)
                or not _SHA256_RE.fullmatch(digest)
                or _sha256_bytes(artifact.encode("utf-8")) != digest
            ):
                return False
            artifact_payload = json.loads(artifact)
            if (
                not isinstance(artifact_payload, Mapping)
                or _json_bytes(artifact_payload).decode("utf-8") != artifact
                or artifact_payload.get("provider") != "moralis"
                or artifact_payload.get("symbol") != str(symbol).upper()
                or artifact_payload.get("timeframe") != timeframe
                or artifact_payload.get("postcommit_receipt_bound") is not False
                or type(artifact_payload.get("admitted_feature_count")) is not int
                or artifact_payload.get("admitted_feature_count") != 0
                or artifact_payload.get("available_at") is not None
                or any(artifact_payload.get(field) is not False for field in authority_fields)
                or not _optional_authority_claims_false(artifact_payload)
                or artifact_payload.get("feature_bridge_ready") is not False
                or artifact_payload.get("provider_ready") is not False
            ):
                return False
            if key == MORALIS_SYMBOL_SCORE_KEY.format(symbol=str(symbol).upper()):
                if (
                    artifact_payload.get("schema_version") != "moralis_symbol_score_v2"
                    or artifact_payload.get("score") is not None
                ):
                    return False
            elif (
                artifact_payload.get("schema_version") != "moralis_feature_bridge_v2"
                or artifact_payload.get("features") != {}
                or type(artifact_payload.get("feature_count")) is not int
                or artifact_payload.get("feature_count") != 0
                or artifact_payload.get("actual_payload_present") is not False
                or artifact_payload.get("admitted_ready") is not False
                or artifact_payload.get("actual_consumption") is not False
                or artifact_payload.get("trainer_isolation_active") is not True
                or artifact_payload.get("heartbeat_only") is not True
                or artifact_payload.get("feature_names") != list(FEATURE_NAMES)
                or artifact_payload.get("abi_feature_names") != list(FEATURE_NAMES)
                or artifact_payload.get("missing_feature_flags") != list(FEATURE_NAMES)
                or artifact_payload.get("missing_mask") != _EXPECTED_MISSING_MASK
            ):
                return False
            artifact_ttl = redis_client.ttl(key)
            if (
                not isinstance(artifact_ttl, int)
                or isinstance(artifact_ttl, bool)
                or artifact_ttl < required_ttl
            ):
                return False
        return True
    except Exception:
        return False


def _numeric_subset(values: Mapping[str, Any], allowed_names: Sequence[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name in allowed_names:
        value = values.get(name)
        if isinstance(value, bool) or value in (None, ""):
            continue
        try:
            parsed = float(cast(str | int | float, value))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(parsed):
            out[name] = parsed
    return out


def _slot_readiness(
    *,
    source_numeric: Mapping[str, float],
    feature_evidence: Mapping[str, Mapping[str, Any]],
    feature_origins: Mapping[str, Mapping[str, Any]],
    feature_conflicts: Mapping[str, Any],
    feature_rejection_reasons: Mapping[str, list[str]],
    source_clock_order_valid: bool,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in FEATURE_NAMES:
        present = name in source_numeric
        evidence_ready = _semantic_evidence_valid(feature_evidence.get(name))
        origin_ready = _origin_valid(
            feature_origins.get(name),
            evidence=feature_evidence.get(name),
        )
        reasons: list[str] = []
        if name in feature_conflicts:
            reasons.append("FEATURE_CONFLICT_QUARANTINED")
        if not present:
            reasons.extend(feature_rejection_reasons.get(name) or ["OPTIONAL_VALUE_MISSING"])
        if present and not evidence_ready:
            reasons.append("SEMANTIC_EVIDENCE_MISSING_OR_INVALID")
        if present and not origin_ready:
            reasons.append("EXACT_SOURCE_ORIGIN_MISSING_OR_INVALID")
        if present and not source_clock_order_valid:
            reasons.append("SOURCE_CLOCK_CONTRACT_INVALID")
        reasons.extend(("POSTCOMMIT_RECEIPT_UNBOUND", "TRAINER_ISOLATION_ACTIVE"))
        out[name] = {
            "requirement_class": "OPTIONAL_EVENT_DEPENDENT",
            "semantic_value_present": present,
            "semantic_evidence_present": evidence_ready,
            "source_origin_bound": origin_ready,
            "source_clock_order_valid": bool(source_clock_order_valid),
            "postcommit_receipt_bound": False,
            "admissible": False,
            "reasons": sorted(set(reasons)),
        }
    return out


def _source_status(
    *,
    has_lists: bool,
    source_has_actual: bool,
    source_clock_order_valid: bool,
    clock_rejection_present: bool,
    source_state_reasons: Mapping[str, str],
    conflicts: Mapping[str, Any],
    token_map_count: int,
    wallet_watchlist_count: int,
) -> str:
    if wallet_watchlist_count <= 0:
        return "CONFIGURED_NO_WATCHLIST"
    if token_map_count <= 0:
        return "CONFIGURED_NO_TOKEN_MAP"
    if not has_lists:
        return "CONFIGURED_INCOMPLETE_BOOTSTRAP"
    if clock_rejection_present:
        return "SOURCE_CLOCK_CONTRACT_REJECTED"
    if conflicts:
        return "FEATURE_CONFLICT_QUARANTINED"
    if source_has_actual and not source_clock_order_valid:
        return "SOURCE_CLOCK_CONTRACT_REJECTED"
    if source_has_actual:
        return "NON_AUTHORITATIVE_POSTCOMMIT_RECEIPT_UNBOUND"
    if source_state_reasons:
        return _dominant_source_state(source_state_reasons.values())
    return "OPTIONAL_PAYLOADS_PENDING"


def _feature_bridge_status(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "moralis_feature_bridge_status_v2",
        "provider": "moralis",
        "generated_utc": payload.get("generated_at"),
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "event_time": payload.get("event_time"),
        "feature_cutoff": payload.get("feature_cutoff"),
        "ingested_at": payload.get("ingested_at"),
        "available_at": None,
        "source_clock_order_valid": payload.get("source_clock_order_valid"),
        "source_temporal_contract_valid": False,
        "temporal_contract_version": payload.get("temporal_contract_version"),
        "temporal_contract_valid": False,
        "trainer_temporal_contract_valid": False,
        "decision_time_safe": False,
        "trainer_decision_time_safe": False,
        "temporal_rejection_reasons": payload.get("temporal_rejection_reasons"),
        "source_temporal_rejection_reasons": payload.get("source_temporal_rejection_reasons"),
        "postcommit_receipt_bound": False,
        "consumer_receipts_bound": False,
        "publication_authority": False,
        "publication_atomic": False,
        "publication_status": payload.get("publication_status"),
        "ttl_seconds": payload.get("ttl_seconds"),
        "stale_after": payload.get("stale_after"),
        "status": payload.get("status"),
        "trainer_admission_status": payload.get("trainer_admission_status"),
        "source_status": payload.get("source_status"),
        "source_dashboard_color": payload.get("source_dashboard_color"),
        "dashboard_color": "GRAY",
        "feature_bridge_ready": False,
        "provider_ready": False,
        "feature_count": 0,
        "admitted_feature_count": 0,
        "source_feature_count": payload.get("source_feature_count"),
        "diagnostic_feature_count": payload.get("diagnostic_feature_count"),
        "source_feature_claim_count": payload.get("source_feature_claim_count"),
        "source_diagnostic_claim_count": payload.get("source_diagnostic_claim_count"),
        "source_semantic_claim_count": payload.get("source_semantic_claim_count"),
        "raw_transport_record_count": payload.get("raw_transport_record_count"),
        "required_feature_count": 0,
        "optional_feature_count": len(FEATURE_NAMES),
        "missing_feature_flags": payload.get("missing_feature_flags"),
        "stale_feature_flags": payload.get("stale_feature_flags"),
        "missing_mask": payload.get("missing_mask"),
        "missing_mask_true": payload.get("missing_mask_true"),
        "source_missing_feature_flags": payload.get("source_missing_feature_flags"),
        "source_missing_mask": payload.get("source_missing_mask"),
        "source_missing_mask_true": payload.get("source_missing_mask_true"),
        "stale_mask": payload.get("stale_mask"),
        "stale_mask_true": payload.get("stale_mask_true"),
        "slot_readiness": payload.get("slot_readiness"),
        "feature_conflicts": payload.get("feature_conflicts"),
        "source_state_reasons": payload.get("source_state_reasons"),
        "quarantined_feature_names": payload.get("quarantined_feature_names"),
        "token_map_count": payload.get("token_map_count"),
        "wallet_watchlist_count": payload.get("wallet_watchlist_count"),
        "actual_payload_present": False,
        "source_actual_payload_present": payload.get("source_actual_payload_present"),
        "source_payload_temporally_valid": False,
        "heartbeat_only": True,
        "heartbeat_only_green_allowed": False,
        "trainer_isolation_active": True,
        "trainer_consumption": False,
        "provider_tensor_consumption": False,
        "ppo_consumption": False,
        "masa_consumption": False,
        "risk_consumption": False,
        "orchestrator_consumption": False,
        "allocator_consumption": False,
        "paper_consumption": False,
        "live_dryrun_consumption": False,
        "feedback_attribution": False,
        "integration_configured": bool(
            payload.get("token_map_count") and payload.get("wallet_watchlist_count")
        ),
        "integration_capable": True,
        "source_ready": False,
        "admitted_ready": False,
        "actual_consumption": False,
        "trainer_authority": False,
        "prediction_authority": False,
        "risk_authority": False,
        "orchestrator_authority": False,
        "allocator_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "single_provider_can_approve": False,
        "provider_data_can_approve_trade_alone": False,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def _symbol_score_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "moralis_symbol_score_v2",
        "provider": "moralis",
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "generated_utc": payload.get("generated_at"),
        "available_at": None,
        "score": None,
        "score_status": "UNAVAILABLE_NON_AUTHORITATIVE",
        "raw_transport_record_count": payload.get("raw_transport_record_count"),
        "source_feature_claim_count": payload.get("source_feature_claim_count"),
        "source_diagnostic_claim_count": payload.get("source_diagnostic_claim_count"),
        "source_semantic_claim_count": payload.get("source_semantic_claim_count"),
        "admitted_feature_count": 0,
        "feature_bridge_ready": False,
        "provider_ready": False,
        "postcommit_receipt_bound": False,
        "publication_authority": False,
        "trainer_authority": False,
        "prediction_authority": False,
        "risk_authority": False,
        "orchestrator_authority": False,
        "allocator_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "status": payload.get("status"),
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }


def _bounded_upstream_temporal_rejections(
    values: Sequence[str] | None,
) -> tuple[str, ...]:
    invalid = ("UPSTREAM_TEMPORAL_REJECTION_EVIDENCE_INVALID",)
    if values is None:
        return ()
    if isinstance(values, str | bytes) or len(values) > MAX_UPSTREAM_TEMPORAL_REJECTION_REASONS:
        return invalid
    validated: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or value != value.strip():
            return invalid
        try:
            encoded = value.encode("ascii")
        except UnicodeEncodeError:
            return invalid
        if len(encoded) > MAX_UPSTREAM_TEMPORAL_REJECTION_REASON_BYTES or not value.isprintable():
            return invalid
        validated.append(value)
    return tuple(sorted(set(validated)))


def _bounded_feature_rejection_reasons(
    values: Mapping[str, Any] | None,
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if not isinstance(values, Mapping):
        return out
    for name in FEATURE_NAMES:
        raw = values.get(name)
        if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
            continue
        bounded = _bounded_upstream_temporal_rejections(raw)
        if bounded:
            out[name] = list(bounded)
    return out


def _bounded_named_mappings(
    values: Mapping[str, Any] | None,
    allowed_names: Sequence[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(values, Mapping):
        return {}
    return {
        name: dict(values[name]) for name in allowed_names if isinstance(values.get(name), Mapping)
    }


def _bounded_feature_conflicts(values: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(values, Mapping):
        return {}
    return {name: values[name] for name in FEATURE_NAMES if name in values}


def _bounded_source_states(values: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(values, Mapping) or len(values) > 64:
        return {}
    out: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not key or not isinstance(value, str) or not value:
            continue
        if len(key.encode("utf-8")) > 128 or len(value.encode("utf-8")) > 128:
            continue
        out[key] = value
    return out


def _dominant_source_state(values: Any) -> str:
    states = {str(value) for value in values}
    for candidate in (
        "CONFIGURED_BUT_UNSUBSCRIBED_OR_FORBIDDEN",
        "RATE_LIMITED",
        "CADENCE_DEFERRED",
        "DEGRADED",
        "SOURCE_ROWS_MISSING",
    ):
        if candidate in states:
            return candidate
    return sorted(states)[0] if states else "OPTIONAL_PAYLOADS_PENDING"


def _semantic_evidence_valid(value: Mapping[str, Any] | None) -> bool:
    if not isinstance(value, Mapping):
        return False
    unit = value.get("unit")
    direction = value.get("direction")
    scope = value.get("measurement_scope")
    rows = value.get("contributing_row_count")
    contributor_rows = value.get("contributing_rows")
    contributor_digest = value.get("contributing_rows_sha256")
    event_time = value.get("event_time")
    feature_cutoff = value.get("feature_cutoff")
    source_window = value.get("source_window_seconds")
    row_receipts_valid = _contributing_row_receipts_valid(
        contributor_rows,
        expected_count=rows,
        expected_digest=contributor_digest,
        expected_event_time=event_time,
    )
    return bool(
        isinstance(unit, str)
        and unit
        and isinstance(direction, str)
        and direction
        and isinstance(scope, str)
        and scope
        and isinstance(rows, int)
        and not isinstance(rows, bool)
        and rows > 0
        and row_receipts_valid
        and _parse_utc(event_time) is not None
        and feature_cutoff == event_time
        and isinstance(source_window, int)
        and not isinstance(source_window, bool)
        and source_window > 0
        and value.get("freshness_status") == "FRESH_WITHIN_SOURCE_WINDOW"
    )


def _contributing_row_receipts_valid(
    value: Any,
    *,
    expected_count: Any,
    expected_digest: Any,
    expected_event_time: Any,
) -> bool:
    if (
        not isinstance(value, list)
        or not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or len(value) != expected_count
        or not isinstance(expected_digest, str)
        or not _SHA256_RE.fullmatch(expected_digest)
    ):
        return False
    clocks: list[datetime] = []
    for receipt in value:
        if not isinstance(receipt, Mapping):
            return False
        canonical = receipt.get("row_canonical_json")
        digest = receipt.get("row_sha256")
        event_time = _parse_utc(receipt.get("event_time"))
        if (
            not isinstance(receipt.get("row_index"), int)
            or isinstance(receipt.get("row_index"), bool)
            or int(receipt["row_index"]) < 0
            or not isinstance(canonical, str)
            or not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
            or _sha256_bytes(canonical.encode("utf-8")) != digest
            or event_time is None
        ):
            return False
        try:
            parsed = json.loads(canonical)
            canonical_roundtrip = _json_bytes(parsed).decode("utf-8")
        except (TypeError, ValueError):
            return False
        if not isinstance(parsed, Mapping) or canonical_roundtrip != canonical:
            return False
        clocks.append(event_time)
    try:
        rows_digest = _sha256_bytes(_json_bytes(value))
    except (TypeError, ValueError):
        return False
    latest = _iso_utc(max(clocks)) if clocks else None
    return rows_digest == expected_digest and latest == expected_event_time


def _origin_valid(
    value: Mapping[str, Any] | None,
    *,
    evidence: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    return bool(
        value.get("provider") == "moralis"
        and isinstance(value.get("source_key"), str)
        and value.get("source_key")
        and isinstance(value.get("source_schema_version"), str)
        and value.get("source_schema_version")
        and isinstance(value.get("endpoint_id"), str)
        and value.get("endpoint_id")
        and isinstance(value.get("source_payload_sha256"), str)
        and _SHA256_RE.fullmatch(str(value.get("source_payload_sha256")))
        and isinstance(value.get("source_binding_sha256"), str)
        and _SHA256_RE.fullmatch(str(value.get("source_binding_sha256")))
        and isinstance(evidence, Mapping)
        and value.get("unit") == evidence.get("unit")
        and value.get("direction") == evidence.get("direction")
        and value.get("measurement_scope") == evidence.get("measurement_scope")
        and value.get("contributing_rows_sha256") == evidence.get("contributing_rows_sha256")
        and value.get("event_time") == evidence.get("event_time")
        and value.get("feature_cutoff") == evidence.get("feature_cutoff")
    )


def _validate_source_clock_contract(
    *,
    event_time: str | None,
    feature_cutoff: str | None,
    ingested_at: str | None,
    generated_at: str,
    supplied_available_at: str | None,
    require_source_clocks: bool,
) -> dict[str, Any]:
    inputs = {
        "event_time": event_time,
        "feature_cutoff": feature_cutoff,
        "ingested_at": ingested_at,
        "generated_at": generated_at,
    }
    parsed: dict[str, datetime] = {}
    reasons: list[str] = []
    for name, value in inputs.items():
        if value in (None, ""):
            if name == "generated_at" or require_source_clocks:
                reasons.append(f"{name.upper()}_MISSING")
            continue
        clock = _parse_utc(value)
        if clock is None:
            reasons.append(f"{name.upper()}_NOT_STRICT_UTC")
            continue
        parsed[name] = clock
    for earlier, later, reason in (
        ("event_time", "feature_cutoff", "EVENT_TIME_AFTER_FEATURE_CUTOFF"),
        ("feature_cutoff", "ingested_at", "FEATURE_CUTOFF_AFTER_INGESTED_AT"),
        ("event_time", "ingested_at", "EVENT_TIME_AFTER_INGESTED_AT"),
        ("ingested_at", "generated_at", "INGESTED_AT_AFTER_GENERATED_AT"),
        ("feature_cutoff", "generated_at", "FEATURE_CUTOFF_AFTER_GENERATED_AT"),
    ):
        if earlier in parsed and later in parsed and parsed[earlier] > parsed[later]:
            reasons.append(reason)
    if supplied_available_at not in (None, ""):
        reasons.append("SUPPLIED_AVAILABLE_AT_IGNORED_NO_POSTCOMMIT_RECEIPT")
    reasons.append("POSTCOMMIT_RECEIPT_UNBOUND")
    return {
        "event_time": _iso_utc(parsed.get("event_time")),
        "feature_cutoff": _iso_utc(parsed.get("feature_cutoff")),
        "ingested_at": _iso_utc(parsed.get("ingested_at")),
        "generated_at": _iso_utc(parsed.get("generated_at")),
        "available_at": None,
        "rejection_reasons": sorted(set(reasons)),
    }


def _set_json_verified(redis_client: Any, key: str, encoded: bytes, *, ex: int) -> bool:
    if redis_client is None:
        return False
    try:
        text = encoded.decode("utf-8")
        if redis_client.set(key, text, ex=ex) is not True:
            return False
        actual = redis_client.get(key)
        if isinstance(actual, bytes):
            actual = actual.decode("utf-8", errors="strict")
        return bool(actual == text)
    except Exception:
        return False


def _json_bytes(value: Any) -> bytes:
    _validate_closed_json(value)
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > _MAX_JSON_BYTES:
        raise ValueError("JSON byte limit exceeded")
    return encoded


def _validate_closed_json(
    value: Any,
    *,
    path: str = "$",
    depth: int = 0,
    node_budget: list[int] | None = None,
) -> None:
    if node_budget is None:
        node_budget = [_MAX_JSON_TOTAL_NODES]
    node_budget[0] -= 1
    if node_budget[0] < 0:
        raise ValueError(f"{path}: JSON node limit exceeded")
    if depth > _MAX_JSON_DEPTH:
        raise ValueError(f"{path}: JSON depth limit exceeded")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if len(value.encode("utf-8", errors="strict")) > _MAX_JSON_STRING_BYTES:
            raise ValueError(f"{path}: JSON string byte limit exceeded")
        if unicodedata.normalize("NFC", value) != value or any(
            unicodedata.category(char).startswith("C") for char in value
        ):
            raise ValueError(f"{path}: unsafe Unicode string")
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path}: non-finite number")
        return
    if isinstance(value, list):
        if len(value) > _MAX_JSON_LIST_ITEMS:
            raise ValueError(f"{path}: JSON list cardinality exceeded")
        for index, item in enumerate(value):
            _validate_closed_json(
                item,
                path=f"{path}[{index}]",
                depth=depth + 1,
                node_budget=node_budget,
            )
        return
    if isinstance(value, dict):
        if len(value) > _MAX_JSON_OBJECT_FIELDS:
            raise ValueError(f"{path}: JSON object cardinality exceeded")
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path}: non-string object key")
            if not key or len(key.encode("utf-8", errors="strict")) > _MAX_JSON_STRING_BYTES:
                raise ValueError(f"{path}: invalid JSON object key")
            if unicodedata.normalize("NFC", key) != key or any(
                unicodedata.category(char).startswith("C") for char in key
            ):
                raise ValueError(f"{path}: unsafe Unicode object key")
            _validate_closed_json(
                item,
                path=f"{path}.{key}",
                depth=depth + 1,
                node_budget=node_budget,
            )
        return
    raise TypeError(f"{path}: unsupported JSON type {type(value).__name__}")


def _sha256_bytes(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0:
        return None
    return parsed.astimezone(UTC)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _dig(mapping: Mapping[str, Any], *path: str) -> Any:
    cur: Any = mapping
    for item in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(item)
    return cur


def _isolation_active() -> bool:
    return not _trainer_admission_bound()


def _trainer_admission_bound() -> bool:
    return bool(
        MORALIS_TRAINER_CONSUMPTION_BOUND
        and MORALIS_CONSUMER_RECEIPTS_BOUND
        and MORALIS_POSTCOMMIT_RECEIPT_BOUND
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
