"""Non-authoritative Moralis Redis publisher and evidence aggregator."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.smart_money_wallets.canonical_cache import read_canonical_records
from app.services.smart_money_wallets.endpoint_registry import (
    MORALIS_EVM_CHAIN_ALIASES,
    MoralisEndpointSpec,
)
from app.services.smart_money_wallets.health import build_moralis_health
from app.services.smart_money_wallets.models import (
    MAX_MORALIS_RAW_RESPONSE_BYTES,
    MORALIS_RAW_RESPONSE_BYTES_SCOPE,
)
from app.services.smart_money_wallets.moralis_feature_bridge import (
    DIAGNOSTIC_FEATURE_NAMES,
    FEATURE_NAMES,
    build_moralis_feature_payload,
    moralis_feature_fanout_keys,
    publish_moralis_feature_payload,
    verify_moralis_feature_fanout_completion,
)
from app.services.smart_money_wallets.normalizer import (
    classifier_evidence_reverification_reasons,
    normalize_moralis_payload,
)
from app.services.smart_money_wallets.rate_limit import classify_status

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NORMALIZED_SCHEMA = "moralis_normalized_payload_v2"
_AGGREGATE_CAS_SCRIPT = """
-- MORALIS_AGGREGATE_CAS_V1
local current = redis.call('GET', KEYS[1])
if ARGV[1] == '0' then
  if current then return 0 end
else
  if (not current) or current ~= ARGV[2] then return 0 end
end
redis.call('SET', KEYS[1], ARGV[3], 'EX', tonumber(ARGV[4]))
return 1
"""
_MAX_CAS_ATTEMPTS = 8
_RAW_PROVENANCE_TTL_MULTIPLIER = 2
_MAX_JSON_DEPTH = 16
_MAX_JSON_LIST_ITEMS = 1000
_MAX_JSON_OBJECT_FIELDS = 512
_MAX_JSON_STRING_BYTES = 16_384
_MAX_JSON_TOTAL_NODES = 20_000
_MAX_JSON_BYTES = 4_194_304
_SAFE_KEY_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SYMBOL_KEY_SEGMENT_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.-]{0,31}$")
_TIMEFRAME_KEY_SEGMENT_RE = re.compile(r"^[1-9][0-9]{0,5}[smhdwM]$")
_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-f]{40}$")
_TOKEN_METADATA_INDEX_TEMPLATE = "v2:moralis:index:v2:token_metadata:{chain}:{token}"  # noqa: S105 - Redis key template
_TOKEN_METADATA_MANIFEST_PREFIX = "v2:moralis:manifest:v2:token_metadata"  # noqa: S105 - Redis key prefix


def publish_moralis_result(
    redis_client: Any,
    *,
    env: Mapping[str, str | None],
    spec: MoralisEndpointSpec,
    chain: str,
    symbol: str | None = None,
    wallet: str | None = None,
    token: str | None = None,
    http_status: int | None,
    payload: Any,
    budget_status: Mapping[str, Any],
    error_class: str | None = None,
    timeframe: str = "1m",
    token_map_count: int = 0,
    wallet_watchlist_count: int = 0,
    authenticated_classifier_receipts: Mapping[str, Any] | None = None,
    classifier_authentication_key: bytes | None = None,
    classifier_authentication_key_id: str | None = None,
    raw_response_bytes: bytes | None = None,
    raw_response_sha256: str | None = None,
    raw_response_byte_count: int | None = None,
    raw_response_bytes_scope: str | None = None,
    transport_started_at: str | None = None,
    observed_at: str | None = None,
    ingested_at: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    publication_clock = generated_at or observed_at or _now()
    raw_response_evidence = _raw_response_evidence(
        raw_response_bytes=raw_response_bytes,
        claimed_sha256=raw_response_sha256,
        claimed_byte_count=raw_response_byte_count,
        claimed_bytes_scope=raw_response_bytes_scope,
        transport_started_at=transport_started_at,
        observed_at=observed_at,
        ingested_at=ingested_at,
        generated_at=publication_clock,
        parsed_payload=payload,
    )
    normalized_chain = _chain(chain)
    normalized = normalize_moralis_payload(
        spec=spec,
        symbol=symbol,
        chain=normalized_chain,
        wallet=wallet,
        token=token,
        payload=payload,
        authenticated_classifier_receipts=authenticated_classifier_receipts,
        classifier_authentication_key=classifier_authentication_key,
        classifier_authentication_key_id=classifier_authentication_key_id,
        observed_at=observed_at or publication_clock,
    )
    # Normalization observation time and publisher generation time are
    # intentionally distinct.  The latter is when this derived envelope was
    # formed, never when the HTTP body first became observable.
    normalized["generated_at"] = publication_clock
    status = _status_from_response(http_status=http_status, error_class=error_class)
    key_rejections = _publication_key_rejection_reasons(
        spec=spec,
        chain=normalized_chain,
        symbol=symbol,
        wallet=wallet,
        token=token,
        timeframe=timeframe,
    )
    if key_rejections:
        return _serialization_failure_result(
            spec=spec,
            symbol=symbol,
            status=status,
            reason="REDIS_KEY_SEGMENT_INVALID:" + ",".join(key_rejections),
            planned_keys=[],
        )
    transport_actual = normalized["actual_payload_present"] is True and status == "READY"
    semantic_actual = normalized["semantic_payload_present"] is True and status == "READY"
    raw_response_evidence_bound = raw_response_evidence["raw_response_evidence_bound"] is True
    raw_transport_receipt_present = status == "READY" and raw_response_evidence_bound
    source_artifact_present = transport_actual or raw_transport_receipt_present
    aggregate_key = f"v2:moralis:feature_aggregate:{symbol}:{timeframe}" if symbol else None
    bridge_keys = (
        list(moralis_feature_fanout_keys(symbol=str(symbol), timeframe=timeframe))
        if symbol and semantic_actual
        else []
    )
    control_keys = [
        "v2:provider:moralis:usage",
        "v2:provider:moralis:endpoint_status",
        "v2:provider:moralis:health",
    ]
    try:
        source_payload = _source_observation_payload(
            normalized,
            raw_response_evidence=raw_response_evidence,
        )
        source_payload_bytes = _json_bytes(source_payload)
    except (TypeError, ValueError) as exc:
        unresolved_source = ["UNRESOLVABLE_SOURCE_ARTIFACT"] if source_artifact_present else []
        planned_keys = [
            *unresolved_source,
            *([aggregate_key] if aggregate_key and semantic_actual else []),
            *bridge_keys,
            *control_keys,
        ]
        return _serialization_failure_result(
            spec=spec,
            symbol=symbol,
            status=status,
            reason=f"STRICT_JSON_SERIALIZATION_REJECTED:{type(exc).__name__}",
            planned_keys=planned_keys,
        )
    source_payload_sha256 = hashlib.sha256(source_payload_bytes).hexdigest()
    source_identity_material = _source_identity_material(
        spec,
        chain=normalized_chain,
        wallet=wallet,
        token=token,
        symbol=symbol,
    )
    source_identity_material_bytes = _json_bytes(source_identity_material)
    source_identity = _source_identity_from_material(source_identity_material)
    source_keys = (
        _raw_keys(
            spec,
            chain=normalized_chain,
            wallet=wallet,
            token=token,
            symbol=symbol,
            source_payload_sha256=source_payload_sha256,
        )
        if source_artifact_present
        else []
    )
    source_key = source_keys[0] if source_keys else None
    raw_provenance_ttl = max(
        1,
        int(spec.ttl_seconds) * _RAW_PROVENANCE_TTL_MULTIPLIER,
    )
    generated_at = normalized.get("generated_at")
    source_artifact_expires_at = _expires_at(generated_at, raw_provenance_ttl)
    metadata_keys = (
        _token_metadata_keys(
            chain=normalized_chain,
            token=token,
            source_payload_sha256=source_payload_sha256,
        )
        if transport_actual and spec.endpoint_id == "token_metadata"
        else []
    )
    planned_keys = [
        *source_keys,
        *metadata_keys,
        *([aggregate_key] if aggregate_key and semantic_actual else []),
        *bridge_keys,
        *control_keys,
    ]
    try:
        budget_status_bytes = _json_bytes(dict(budget_status))
    except (TypeError, ValueError) as exc:
        return _serialization_failure_result(
            spec=spec,
            symbol=symbol,
            status=status,
            reason=f"STRICT_JSON_SERIALIZATION_REJECTED:{type(exc).__name__}",
            planned_keys=planned_keys,
        )
    binding_bytes = _source_binding_bytes(
        endpoint_id=spec.endpoint_id,
        source_identity=source_identity,
        source_key=source_key or "",
        source_schema_version=str(normalized.get("schema_version") or ""),
        source_payload_sha256=source_payload_sha256,
    )
    binding_sha256 = hashlib.sha256(binding_bytes).hexdigest()
    event_time = normalized.get("event_time")
    feature_origins = _feature_origins(
        normalized,
        source_identity=source_identity,
        source_key=source_key or "",
        source_payload_sha256=source_payload_sha256,
        source_binding_sha256=binding_sha256,
    )
    diagnostic_origins = _diagnostic_origins(
        normalized,
        source_identity=source_identity,
        source_key=source_key or "",
        source_payload_sha256=source_payload_sha256,
        source_binding_sha256=binding_sha256,
    )
    source_clock_rejections = _raw_source_clock_rejections(
        event_time=event_time,
        transport_started_at=transport_started_at,
        observed_at=observed_at,
        ingested_at=ingested_at,
        generated_at=generated_at,
    )
    transport_clock_order_valid = not any(
        reason
        for reason in source_clock_rejections
        if reason not in {"AVAILABLE_AT_UNBOUND", "POSTCOMMIT_RECEIPT_UNBOUND"}
    )
    envelope = {
        **source_payload,
        "timeframe": timeframe,
        "feature_cutoff": event_time,
        "transport_started_at": transport_started_at,
        "observed_at": observed_at,
        "ingested_at": ingested_at,
        "available_at": None,
        "generated_at": generated_at,
        "source_clock_rejection_reasons": source_clock_rejections,
        "source_clock_order_valid": False,
        "transport_clock_order_valid": transport_clock_order_valid,
        "raw_response_evidence_schema_version": raw_response_evidence.get(
            "raw_response_evidence_schema_version"
        ),
        "raw_response_evidence_bound": raw_response_evidence_bound,
        "raw_response_evidence_persisted": False,
        "raw_response_evidence_rejection_reasons": raw_response_evidence.get(
            "raw_response_evidence_rejection_reasons"
        ),
        "raw_response_sha256": raw_response_evidence.get("raw_response_sha256"),
        "raw_response_byte_count": raw_response_evidence.get("raw_response_byte_count"),
        "raw_response_bytes_scope": raw_response_evidence.get("raw_response_bytes_scope"),
        "source_payload_canonical_json": source_payload_bytes.decode("utf-8"),
        "source_payload_sha256": source_payload_sha256,
        "source_payload_digest_algorithm": "sha256",
        "source_binding_canonical_json": binding_bytes.decode("utf-8"),
        "source_binding_sha256": binding_sha256,
        "source_key": source_key,
        "source_identity": source_identity,
        "source_identity_material_canonical_json": source_identity_material_bytes.decode("utf-8"),
        "source_identity_material_sha256": hashlib.sha256(
            source_identity_material_bytes
        ).hexdigest(),
        "source_schema_version": normalized.get("schema_version"),
        "source_artifact_expires_at": source_artifact_expires_at,
        "raw_provenance_ttl_seconds": raw_provenance_ttl,
        "expires_at": _expires_at(generated_at, spec.ttl_seconds),
        "classifier_authentication_key_id": classifier_authentication_key_id,
        "classifier_request_target_kind": normalized.get("classifier_request_target_kind"),
        "classifier_request_target": normalized.get("classifier_request_target"),
        "feature_origins": feature_origins,
        "diagnostic_origins": diagnostic_origins,
        "ttl_seconds": spec.ttl_seconds,
        "stale_after": spec.ttl_seconds,
        "provider_ready": False,
        "publication_authority": False,
        "publication_atomic": False,
        "postcommit_receipt_bound": False,
        "publication_status": "NON_AUTHORITATIVE_POSTCOMMIT_RECEIPT_UNBOUND",
        "subscription_status": status,
        "auth_status": status,
        "compute_budget_status": dict(budget_status),
        "last_http_status": http_status,
        "last_error_class": error_class,
        "dashboard_color": "GRAY",
        "trainer_authority": False,
        "prediction_authority": False,
        "risk_authority": False,
        "orchestrator_authority": False,
        "allocator_authority": False,
        "paper_authority": False,
        "live_authority": False,
    }

    keys_written: list[str] = []
    duplicate_keys: list[str] = []
    skipped_keys: list[str] = []
    skip_reasons: dict[str, str] = {}
    failed_keys: list[str] = []
    unattempted_keys: list[str] = []
    artifact_sha256: dict[str, str] = {}
    aggregate_payload: dict[str, Any] = {}
    bridge_payload: dict[str, Any] = {}
    update_status = "NO_SEMANTIC_SOURCE_OBSERVATION"
    feature_ttl = max(1, int(spec.ttl_seconds))
    if redis_client is None:
        if planned_keys:
            failed_keys.append(planned_keys[0])
            unattempted_keys.extend(planned_keys[1:])
    else:
        if source_key is not None:
            source_write = _set_content_addressed_json(
                redis_client,
                source_key,
                source_payload_bytes,
                ex=raw_provenance_ttl,
            )
            if source_write == "WRITTEN":
                keys_written.append(source_key)
                artifact_sha256[source_key] = source_payload_sha256
                envelope["raw_response_evidence_persisted"] = raw_response_evidence_bound
            elif source_write == "EXACT_DUPLICATE_NO_REFRESH":
                duplicate_keys.append(source_key)
                artifact_sha256[source_key] = source_payload_sha256
                envelope["raw_response_evidence_persisted"] = raw_response_evidence_bound
            else:
                failed_keys.append(source_key)
                unattempted_keys.extend(key for key in planned_keys if key != source_key)

        if not failed_keys and metadata_keys:
            metadata_result = _publish_token_metadata_v2(
                redis_client,
                chain=normalized_chain,
                token=str(token or ""),
                source_key=str(source_key or ""),
                source_payload=source_payload,
                source_payload_sha256=source_payload_sha256,
                source_artifact_expires_at=source_artifact_expires_at,
                generated_at=str(generated_at or publication_clock),
                ttl_seconds=max(1, int(spec.ttl_seconds)),
                raw_provenance_ttl_seconds=raw_provenance_ttl,
            )
            keys_written.extend(metadata_result["keys_written"])
            duplicate_keys.extend(metadata_result["duplicate_keys"])
            skipped_keys.extend(metadata_result["skipped_keys"])
            skip_reasons.update(metadata_result["skip_reasons"])
            failed_keys.extend(metadata_result["failed_keys"])
            unattempted_keys.extend(metadata_result["unattempted_keys"])
            artifact_sha256.update(metadata_result["publication_artifact_sha256"])
            if failed_keys:
                unattempted_keys.extend(
                    key
                    for key in [
                        *([aggregate_key] if aggregate_key and semantic_actual else []),
                        *bridge_keys,
                        *control_keys,
                    ]
                    if key not in unattempted_keys
                )

        if not failed_keys and aggregate_key and semantic_actual:
            merge_result = _cas_merge_feature_payload(
                redis_client,
                aggregate_key,
                envelope=envelope,
                spec=spec,
                status=status,
                observed_at=publication_clock,
                token_map_count=token_map_count,
                wallet_watchlist_count=wallet_watchlist_count,
                budget_status=budget_status,
                classifier_authentication_key=classifier_authentication_key,
                classifier_authentication_key_id=classifier_authentication_key_id,
            )
            update_status = str(merge_result["update_status"])
            aggregate_payload = dict(merge_result.get("aggregate_payload") or {})
            feature_ttl = int(merge_result.get("ttl_seconds") or feature_ttl)
            if update_status in {"APPLIED_NEWER_ATOMIC_CAS", "EXACT_DUPLICATE_NO_REFRESH"}:
                if update_status == "APPLIED_NEWER_ATOMIC_CAS":
                    keys_written.append(aggregate_key)
                    aggregate_artifact_sha256 = str(merge_result["artifact_sha256"])
                    artifact_sha256[aggregate_key] = aggregate_artifact_sha256
                else:
                    skipped_keys.append(aggregate_key)
                    skip_reasons[aggregate_key] = update_status
                    try:
                        aggregate_artifact_sha256 = hashlib.sha256(
                            _json_bytes(aggregate_payload)
                        ).hexdigest()
                    except (TypeError, ValueError):
                        aggregate_artifact_sha256 = ""
                feature_ttl = _remaining_ttl_seconds(
                    aggregate_payload.get("expires_at"),
                    observed_at=publication_clock,
                )
                if feature_ttl <= 0 or not _SHA256_RE.fullmatch(aggregate_artifact_sha256):
                    failed_keys.append(aggregate_key)
                    unattempted_keys.extend(
                        key for key in [*bridge_keys, *control_keys] if key not in unattempted_keys
                    )
                else:
                    fanout_already_complete = bool(
                        update_status == "EXACT_DUPLICATE_NO_REFRESH"
                        and verify_moralis_feature_fanout_completion(
                            redis_client,
                            symbol=str(symbol),
                            timeframe=timeframe,
                            aggregate_artifact_sha256=aggregate_artifact_sha256,
                            expires_at=aggregate_payload.get("expires_at"),
                            observed_at=publication_clock,
                        )
                    )
                    if fanout_already_complete:
                        for key in bridge_keys:
                            skipped_keys.append(key)
                            skip_reasons[key] = "FANOUT_ALREADY_COMPLETE_NO_REFRESH"
                        bridge_payload = {
                            "publication_acknowledged": True,
                            "fanout_completion_durable": True,
                            "keys_written": [],
                            "failed_keys": [],
                            "unattempted_keys": [],
                            "publication_artifact_sha256": {},
                        }
                    else:
                        bridge_payload = publish_moralis_feature_payload(
                            redis_client,
                            symbol=str(symbol),
                            timeframe=timeframe,
                            features=aggregate_payload.get("source_features") or {},
                            diagnostic_features=(
                                aggregate_payload.get("diagnostic_features") or {}
                            ),
                            feature_evidence=aggregate_payload.get("feature_evidence") or {},
                            diagnostic_evidence=(
                                aggregate_payload.get("diagnostic_evidence") or {}
                            ),
                            feature_rejection_reasons=aggregate_payload.get(
                                "feature_rejection_reasons"
                            ),
                            feature_origins=aggregate_payload.get("feature_origins") or {},
                            diagnostic_origins=(aggregate_payload.get("diagnostic_origins") or {}),
                            feature_conflicts=aggregate_payload.get("feature_conflicts") or {},
                            source_state_reasons=aggregate_payload.get("source_state_reasons"),
                            token_map_count=token_map_count,
                            wallet_watchlist_count=wallet_watchlist_count,
                            actual_payload_present=bool(
                                aggregate_payload.get("source_features")
                                or aggregate_payload.get("diagnostic_features")
                            ),
                            event_time=aggregate_payload.get("event_time"),
                            feature_cutoff=aggregate_payload.get("feature_cutoff"),
                            ingested_at=aggregate_payload.get("ingested_at"),
                            available_at=None,
                            ttl_seconds=feature_ttl,
                            stale_after=feature_ttl,
                            compute_unit_status=budget_status,
                            upstream_temporal_rejection_reasons=aggregate_payload.get(
                                "endpoint_temporal_rejection_reasons"
                            ),
                            generated_at_override=aggregate_payload.get("generated_at"),
                            expires_at_override=aggregate_payload.get("expires_at"),
                            fanout_generation_id=aggregate_artifact_sha256,
                            aggregate_artifact_sha256=aggregate_artifact_sha256,
                            source_provenance_expires_at=aggregate_payload.get(
                                "source_provenance_expires_at"
                            ),
                            raw_transport_record_count=int(
                                aggregate_payload.get("raw_transport_record_count") or 0
                            ),
                            source_feature_claim_count=int(
                                aggregate_payload.get("source_feature_claim_count") or 0
                            ),
                            source_diagnostic_claim_count=int(
                                aggregate_payload.get("source_diagnostic_claim_count") or 0
                            ),
                        )
                    keys_written.extend(bridge_payload.get("keys_written") or [])
                    failed_keys.extend(bridge_payload.get("failed_keys") or [])
                    unattempted_keys.extend(bridge_payload.get("unattempted_keys") or [])
                    artifact_sha256.update(bridge_payload.get("publication_artifact_sha256") or {})
                    if failed_keys:
                        unattempted_keys.extend(
                            key for key in control_keys if key not in unattempted_keys
                        )
            elif update_status in {
                "OLDER_SOURCE_EVENT_REJECTED",
                "SAME_CLOCK_DIVERGENT_DIGEST_QUARANTINED",
            }:
                for key in [aggregate_key, *bridge_keys]:
                    skipped_keys.append(key)
                    skip_reasons[key] = update_status
            else:
                failed_keys.append(aggregate_key)
                unattempted_keys.extend(
                    key for key in [*bridge_keys, *control_keys] if key not in unattempted_keys
                )

        retained_aggregate = aggregate_payload or (
            _read_mapping(redis_client, aggregate_key) if aggregate_key else {}
        )
        retained_state = _retained_state(
            retained_aggregate,
            observed_at=publication_clock,
        )
        raw_response_evidence_persisted = bool(
            raw_response_evidence_bound
            and source_key is not None
            and (source_key in keys_written or source_key in duplicate_keys)
        )
        endpoint_row = {
            "schema_version": "moralis_endpoint_status_v2",
            "provider": "moralis",
            "endpoint_id": spec.endpoint_id,
            "status": _source_observability_status(
                transport_status=status,
                transport_actual=transport_actual,
                semantic_actual=semantic_actual,
            ),
            "source_observation_present": bool(semantic_actual),
            "actual_payload_present": False,
            "raw_transport_actual_payload_present": bool(transport_actual),
            "raw_transport_record_count": int(normalized.get("raw_transport_record_count") or 0),
            "source_semantic_claim_count": int(normalized.get("source_semantic_claim_count") or 0),
            "admitted_feature_count": 0,
            "heartbeat_only": True,
            "provider_ready": False,
            "publication_authority": False,
            "postcommit_receipt_bound": False,
            "publication_status": "NON_AUTHORITATIVE_POSTCOMMIT_RECEIPT_UNBOUND",
            "source_key": source_key,
            "source_schema_version": normalized.get("schema_version"),
            "source_payload_sha256": source_payload_sha256,
            "source_binding_sha256": binding_sha256,
            "source_identity": source_identity,
            "raw_response_evidence_schema_version": raw_response_evidence.get(
                "raw_response_evidence_schema_version"
            ),
            "raw_response_evidence_bound": raw_response_evidence_bound,
            "raw_response_evidence_persisted": raw_response_evidence_persisted,
            "raw_response_evidence_rejection_reasons": raw_response_evidence.get(
                "raw_response_evidence_rejection_reasons"
            ),
            "raw_response_sha256": raw_response_evidence.get("raw_response_sha256"),
            "raw_response_byte_count": raw_response_evidence.get("raw_response_byte_count"),
            "raw_response_bytes_scope": raw_response_evidence.get("raw_response_bytes_scope"),
            "transport_status": status,
            "aggregate_update_status": update_status,
            "retained_state": retained_state,
            "transport_started_at": transport_started_at,
            "observed_at": observed_at,
            "ingested_at": ingested_at,
            "generated_at": generated_at,
            "generated_utc": generated_at,
            "available_at": None,
            "expires_at": _expires_at(generated_at, spec.ttl_seconds),
            "dashboard_color": "GRAY",
            "trainer_authority": False,
            "prediction_authority": False,
            "risk_authority": False,
            "orchestrator_authority": False,
            "allocator_authority": False,
            "paper_authority": False,
            "live_authority": False,
            "core_system_blocked": False,
            "raw_key_exposed": False,
        }
        endpoint_status = _merge_endpoint_status(
            redis_client,
            "v2:provider:moralis:endpoint_status",
            endpoint_id=spec.endpoint_id,
            row=endpoint_row,
            provider="moralis",
            generated_utc=str(generated_at or publication_clock),
        )
        bridge_status_payload = _read_mapping(
            redis_client,
            "v2:provider:moralis:feature_bridge_status",
        )
        health = build_moralis_health(env, last_http_status=http_status, last_error=error_class)
        health.update(
            {
                "status": "ISOLATED_BY_POLICY",
                "enabled": str(env.get("MORALIS_ENABLED", "1")).lower() not in {"0", "false", "no"},
                "subscription_status": status,
                "auth_status": status,
                "source_health_status": bridge_status_payload.get("source_status", status),
                "current_transport_status": status,
                "aggregate_update_status": update_status,
                "retained_state": retained_state,
                "trainer_consumption_status": "ISOLATED_BY_POLICY",
                "source_status": bridge_status_payload.get("source_status"),
                "source_dashboard_color": bridge_status_payload.get(
                    "source_dashboard_color", "GRAY"
                ),
                "trainer_isolation_active": True,
                "daily_cu_used": _dig(budget_status, "compute_budget", "used_today"),
                "monthly_cu_used": _dig(budget_status, "compute_budget", "used_month"),
                "actual_payload_count_5m": 0,
                "actual_payload_count_1h": 0,
                "trusted_source_actual_endpoint_count": 0,
                "raw_transport_actual_endpoint_count": endpoint_status.get(
                    "raw_transport_actual_endpoint_count", 0
                ),
                "raw_transport_record_count": endpoint_status.get("raw_transport_record_count", 0),
                "raw_response_evidence_bound": raw_response_evidence_bound,
                "raw_response_evidence_persisted": raw_response_evidence_persisted,
                "raw_response_evidence_rejection_reasons": raw_response_evidence.get(
                    "raw_response_evidence_rejection_reasons"
                ),
                "transport_started_at": transport_started_at,
                "observed_at": observed_at,
                "ingested_at": ingested_at,
                "available_at": None,
                "source_observation_endpoint_count": retained_aggregate.get(
                    "source_observation_endpoint_count", 0
                ),
                "source_semantic_claim_count": retained_aggregate.get(
                    "source_semantic_claim_count", 0
                ),
                "admitted_feature_count": 0,
                "last_success_at": None,
                "last_source_observation_at": generated_at if semantic_actual else None,
                "last_error_at": generated_at
                if not semantic_actual and http_status is not None
                else None,
                "dashboard_color": "GRAY",
                "feature_bridge_ready": False,
                "provider_ready": False,
                "feature_count": 0,
                "source_feature_count": bridge_status_payload.get("source_feature_count"),
                "required_feature_count": 0,
                "optional_feature_count": len(FEATURE_NAMES),
                "missing_feature_flags": bridge_status_payload.get("missing_feature_flags"),
                "missing_mask": bridge_status_payload.get("missing_mask"),
                "missing_mask_true": bridge_status_payload.get("missing_mask_true"),
                "stale_feature_flags": bridge_status_payload.get("stale_feature_flags"),
                "stale_mask": bridge_status_payload.get("stale_mask"),
                "stale_mask_true": bridge_status_payload.get("stale_mask_true"),
                "slot_readiness": bridge_status_payload.get("slot_readiness"),
                "feature_conflicts": bridge_status_payload.get("feature_conflicts"),
                "source_state_reasons": bridge_status_payload.get("source_state_reasons"),
                "token_map_count": token_map_count,
                "wallet_watchlist_count": wallet_watchlist_count,
                "actual_payload_present": False,
                "source_actual_payload_present": bridge_status_payload.get(
                    "source_actual_payload_present", bool(semantic_actual)
                ),
                "source_temporal_contract_valid": False,
                "source_temporal_rejection_reasons": bridge_status_payload.get(
                    "source_temporal_rejection_reasons", source_clock_rejections
                ),
                "trainer_decision_time_safe": False,
                "consumer_receipts_bound": False,
                "postcommit_receipt_bound": False,
                "publication_authority": False,
                "heartbeat_only": True,
                "heartbeat_only_green_allowed": False,
                "decision_time_safe": False,
                "trainer_authority": False,
                "prediction_authority": False,
                "risk_authority": False,
                "orchestrator_authority": False,
                "allocator_authority": False,
                "paper_authority": False,
                "live_authority": False,
                "core_system_blocked": False,
            }
        )
        if not failed_keys:
            for control_index, (key, value, ttl) in enumerate(
                (
                    ("v2:provider:moralis:usage", json.loads(budget_status_bytes), 3600),
                    ("v2:provider:moralis:endpoint_status", endpoint_status, 3600),
                    ("v2:provider:moralis:health", health, 3600),
                )
            ):
                try:
                    encoded = _json_bytes(value)
                except (TypeError, ValueError):
                    failed_keys.append(key)
                    unattempted_keys.extend(control_keys[control_index + 1 :])
                    break
                if _set_json_ack(redis_client, key, encoded, ex=ttl):
                    if key not in keys_written:
                        keys_written.append(key)
                    artifact_sha256[key] = hashlib.sha256(encoded).hexdigest()
                elif key not in failed_keys:
                    failed_keys.append(key)
                    unattempted_keys.extend(control_keys[control_index + 1 :])
                    break

    publication_complete = not failed_keys and not unattempted_keys
    raw_response_evidence_persisted = bool(
        raw_response_evidence_bound
        and source_key is not None
        and (source_key in keys_written or source_key in duplicate_keys)
    )
    return {
        "schema_version": "moralis_publish_result_v2",
        "provider": "moralis",
        "endpoint_id": spec.endpoint_id,
        "symbol": symbol,
        "status": status,
        "source_status": _source_observability_status(
            transport_status=status,
            transport_actual=transport_actual,
            semantic_actual=semantic_actual,
        ),
        "source_observation_present": bool(semantic_actual),
        "actual_payload_present": False,
        "raw_transport_actual_payload_present": bool(transport_actual),
        "raw_transport_record_count": int(normalized.get("raw_transport_record_count") or 0),
        "raw_response_evidence_schema_version": raw_response_evidence.get(
            "raw_response_evidence_schema_version"
        ),
        "raw_response_evidence_bound": raw_response_evidence_bound,
        "raw_response_evidence_persisted": raw_response_evidence_persisted,
        "raw_response_evidence_rejection_reasons": raw_response_evidence.get(
            "raw_response_evidence_rejection_reasons"
        ),
        "raw_response_sha256": raw_response_evidence.get("raw_response_sha256"),
        "raw_response_byte_count": raw_response_evidence.get("raw_response_byte_count"),
        "raw_response_bytes_scope": raw_response_evidence.get("raw_response_bytes_scope"),
        "transport_started_at": transport_started_at,
        "observed_at": observed_at,
        "ingested_at": ingested_at,
        "generated_at": generated_at,
        "source_semantic_claim_count": int(normalized.get("source_semantic_claim_count") or 0),
        "admitted_feature_count": 0,
        "heartbeat_only": True,
        "provider_ready": False,
        "available_at": None,
        "postcommit_receipt_bound": False,
        "publication_authority": False,
        "publication_atomic": False,
        "publication_acknowledged": publication_complete,
        "publication_attempt_status": (
            f"COMPLETE_NON_AUTHORITATIVE:{update_status}"
            if publication_complete
            else "PARTIAL_WRITE_FAILED_NON_AUTHORITATIVE"
        ),
        "aggregate_update_status": update_status,
        "planned_keys": planned_keys,
        "keys_written": keys_written,
        "duplicate_keys": duplicate_keys,
        "skipped_keys": skipped_keys,
        "skip_reasons": skip_reasons,
        "failed_keys": failed_keys,
        "unattempted_keys": unattempted_keys,
        "publication_artifact_sha256": artifact_sha256,
        "trainer_authority": False,
        "prediction_authority": False,
        "risk_authority": False,
        "orchestrator_authority": False,
        "allocator_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def _raw_keys(
    spec: MoralisEndpointSpec,
    *,
    chain: str,
    wallet: str | None,
    token: str | None,
    symbol: str | None,
    source_payload_sha256: str,
) -> list[str]:
    identity = _source_identity(
        spec,
        chain=chain,
        wallet=wallet,
        token=token,
        symbol=symbol,
    )
    return [f"v2:moralis:raw:v2:{identity}:{source_payload_sha256}"]


def _token_metadata_keys(
    *,
    chain: str,
    token: str | None,
    source_payload_sha256: str,
) -> list[str]:
    normalized_chain = _chain(chain)
    normalized_token = str(token or "").strip().lower()
    return [
        f"{_TOKEN_METADATA_MANIFEST_PREFIX}:{source_payload_sha256}",
        _TOKEN_METADATA_INDEX_TEMPLATE.format(
            chain=normalized_chain,
            token=normalized_token,
        ),
    ]


def _publish_token_metadata_v2(
    redis_client: Any,
    *,
    chain: str,
    token: str,
    source_key: str,
    source_payload: Mapping[str, Any],
    source_payload_sha256: str,
    source_artifact_expires_at: str,
    generated_at: str,
    ttl_seconds: int,
    raw_provenance_ttl_seconds: int,
) -> dict[str, Any]:
    manifest_key, index_key = _token_metadata_keys(
        chain=chain,
        token=token,
        source_payload_sha256=source_payload_sha256,
    )
    result: dict[str, Any] = {
        "keys_written": [],
        "duplicate_keys": [],
        "skipped_keys": [],
        "skip_reasons": {},
        "failed_keys": [],
        "unattempted_keys": [],
        "publication_artifact_sha256": {},
    }
    source_bytes = _json_bytes(source_payload)
    try:
        raw_readback = redis_client.get(source_key)
        if isinstance(raw_readback, bytes):
            raw_readback = raw_readback.decode("utf-8", errors="strict")
    except Exception:
        raw_readback = None
    if raw_readback != source_bytes.decode("utf-8"):
        result["failed_keys"].append(manifest_key)
        result["unattempted_keys"].append(index_key)
        return result
    records = source_payload.get("canonical_records")
    if not isinstance(records, list) or not records:
        result["failed_keys"].append(manifest_key)
        result["unattempted_keys"].append(index_key)
        return result
    records_bytes = _json_bytes(records)
    manifest = {
        "schema_version": "moralis_token_metadata_manifest_v2",
        "provider": "moralis",
        "endpoint_id": "token_metadata",
        "chain": _chain(chain),
        "token": str(token).strip().lower(),
        "source_key": source_key,
        "source_payload_sha256": source_payload_sha256,
        "source_schema_version": source_payload.get("schema_version"),
        "canonical_records": records,
        "canonical_record_count": len(records),
        "canonical_records_sha256": hashlib.sha256(records_bytes).hexdigest(),
        "raw_transport_record_count": int(
            source_payload.get("raw_transport_record_count") or len(records)
        ),
        "source_semantic_claim_count": 0,
        "admitted_feature_count": 0,
        "available_at": None,
        "receipt_scope": "NON_AUTHORITATIVE_METADATA_CACHE_ONLY",
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
    manifest_bytes = _json_bytes(manifest)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_status = _set_immutable_json(
        redis_client,
        manifest_key,
        manifest_bytes,
        ex=raw_provenance_ttl_seconds,
    )
    if manifest_status == "WRITTEN":
        result["keys_written"].append(manifest_key)
    elif manifest_status == "EXACT_DUPLICATE_NO_REFRESH":
        result["duplicate_keys"].append(manifest_key)
    else:
        result["failed_keys"].append(manifest_key)
        result["unattempted_keys"].append(index_key)
        return result
    result["publication_artifact_sha256"][manifest_key] = manifest_sha256
    try:
        source_remaining_ttl = redis_client.ttl(source_key)
        manifest_remaining_ttl = redis_client.ttl(manifest_key)
    except Exception:
        result["failed_keys"].append(index_key)
        return result
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in (source_remaining_ttl, manifest_remaining_ttl)
    ):
        result["failed_keys"].append(index_key)
        return result
    effective_source_expires_at = _earliest_utc(
        source_artifact_expires_at,
        _expires_at(generated_at, source_remaining_ttl),
    )
    index_expires_at = _earliest_utc(
        _expires_at(
            generated_at,
            min(ttl_seconds, source_remaining_ttl, manifest_remaining_ttl),
        ),
        effective_source_expires_at,
    )
    generated_clock = _parse_utc(generated_at)
    index_expires_clock = _parse_utc(index_expires_at)
    if (
        generated_clock is None
        or index_expires_clock is None
        or index_expires_clock <= generated_clock
    ):
        result["failed_keys"].append(index_key)
        return result
    index_ttl_seconds = min(
        source_remaining_ttl,
        manifest_remaining_ttl,
        max(
            1,
            math.ceil((index_expires_clock - generated_clock).total_seconds()) + 1,
        ),
    )
    index_payload = {
        "schema_version": "moralis_token_metadata_index_v2",
        "provider": "moralis",
        "endpoint_id": "token_metadata",
        "chain": _chain(chain),
        "token": str(token).strip().lower(),
        "generated_at": generated_at,
        "expires_at": index_expires_at,
        "source_artifact_expires_at": effective_source_expires_at,
        "manifest_key": manifest_key,
        "manifest_sha256": manifest_sha256,
        "source_key": source_key,
        "source_payload_sha256": source_payload_sha256,
        "cache_receipt": {
            "schema_version": "moralis_metadata_cache_receipt_v1",
            "scope": "NON_AUTHORITATIVE_METADATA_CACHE_ONLY",
            "source_exact_readback_verified": True,
            "manifest_exact_readback_verified": True,
            "source_key": source_key,
            "source_payload_sha256": source_payload_sha256,
            "manifest_key": manifest_key,
            "manifest_sha256": manifest_sha256,
            "receipt_observed_at": generated_at,
            "available_at": None,
            "publication_authority": False,
            "trainer_authority": False,
            "prediction_authority": False,
            "risk_authority": False,
            "orchestrator_authority": False,
            "allocator_authority": False,
            "paper_authority": False,
            "live_authority": False,
        },
        "raw_transport_record_count": int(
            source_payload.get("raw_transport_record_count") or len(records)
        ),
        "source_semantic_claim_count": 0,
        "admitted_feature_count": 0,
        "available_at": None,
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
    index_bytes = _json_bytes(index_payload)
    raw, prior, read_status = _read_exact_mapping(redis_client, index_key)
    if read_status != "OK":
        result["failed_keys"].append(index_key)
        return result
    prior_clock = _parse_utc(prior.get("generated_at"))
    new_clock = _parse_utc(generated_at)
    same_source = bool(
        prior
        and prior.get("source_key") == source_key
        and prior.get("source_payload_sha256") == source_payload_sha256
    )
    prior_cache_ready = False
    if prior:
        prior_cache = read_canonical_records(
            redis_client,
            endpoint_id="token_metadata",
            chain=_chain(chain),
            token=str(token).strip().lower(),
            observed_at=new_clock,
        )
        prior_cache_ready = prior_cache.ready
    if prior_cache_ready and same_source:
        result["duplicate_keys"].append(index_key)
        if isinstance(raw, str):
            result["publication_artifact_sha256"][index_key] = hashlib.sha256(
                raw.encode("utf-8")
            ).hexdigest()
        return result
    if prior_cache_ready and (new_clock is None or prior_clock is None):
        result["failed_keys"].append(index_key)
        return result
    if (
        prior_cache_ready
        and not same_source
        and prior_clock is not None
        and new_clock is not None
        and prior_clock > new_clock
    ):
        result["skipped_keys"].append(index_key)
        result["skip_reasons"][index_key] = "OLDER_METADATA_INDEX_REJECTED"
        return result
    if (
        prior_cache_ready
        and not same_source
        and prior_clock is not None
        and new_clock is not None
        and prior_clock == new_clock
    ):
        result["skipped_keys"].append(index_key)
        result["skip_reasons"][index_key] = "SAME_CLOCK_DIVERGENT_METADATA_INDEX_QUARANTINED"
        return result
    cas_status = _cas_set_json_ack(
        redis_client,
        index_key,
        expected_raw=raw,
        encoded=index_bytes,
        ex=index_ttl_seconds,
    )
    if cas_status != "APPLIED":
        result["failed_keys"].append(index_key)
        return result
    try:
        index_readback = redis_client.get(index_key)
        if isinstance(index_readback, bytes):
            index_readback = index_readback.decode("utf-8", errors="strict")
    except Exception:
        index_readback = None
    if index_readback != index_bytes.decode("utf-8"):
        result["failed_keys"].append(index_key)
        return result
    validated_cache = read_canonical_records(
        redis_client,
        endpoint_id="token_metadata",
        chain=_chain(chain),
        token=str(token).strip().lower(),
        observed_at=new_clock,
    )
    if not validated_cache.ready:
        result["failed_keys"].append(index_key)
        return result
    result["keys_written"].append(index_key)
    result["publication_artifact_sha256"][index_key] = hashlib.sha256(index_bytes).hexdigest()
    return result


def _source_identity(
    spec: MoralisEndpointSpec,
    *,
    chain: str,
    wallet: str | None,
    token: str | None,
    symbol: str | None,
) -> str:
    return _source_identity_from_material(
        _source_identity_material(
            spec,
            chain=chain,
            wallet=wallet,
            token=token,
            symbol=symbol,
        )
    )


def _source_identity_material(
    spec: MoralisEndpointSpec,
    *,
    chain: str,
    wallet: str | None,
    token: str | None,
    symbol: str | None,
) -> dict[str, str]:
    if spec.requires_wallet:
        identity_kind, identity_value = "wallet", wallet
    elif spec.requires_token:
        identity_kind, identity_value = "token", token
    elif spec.stream_based or spec.group == "streams":
        identity_kind, identity_value = "stream", "global"
    else:
        identity_kind, identity_value = "symbol", symbol
    return {
        "schema_version": "moralis_source_identity_material_v2",
        "endpoint_id": spec.endpoint_id,
        "group": spec.group,
        "chain": _chain(chain),
        "identity_kind": identity_kind,
        "identity_value": str(identity_value or "").strip().lower(),
        "symbol": str(symbol or "").strip().upper(),
    }


def _source_identity_from_material(material: Mapping[str, Any]) -> str:
    endpoint_id = str(material.get("endpoint_id") or "")
    digest = hashlib.sha256(_json_bytes(material)).hexdigest()
    return f"{endpoint_id}:{digest}"


def _rederived_source_identity_material(row: Mapping[str, Any]) -> dict[str, str]:
    wallet = str(row.get("wallet") or "").strip().lower()
    token = str(row.get("token") or "").strip().lower()
    symbol = str(row.get("symbol") or "").strip().upper()
    group = str(row.get("feature_family") or "")
    if wallet:
        identity_kind, identity_value = "wallet", wallet
    elif token:
        identity_kind, identity_value = "token", token
    elif group == "streams":
        identity_kind, identity_value = "stream", "global"
    else:
        identity_kind, identity_value = "symbol", symbol.lower()
    return {
        "schema_version": "moralis_source_identity_material_v2",
        "endpoint_id": str(row.get("endpoint_id") or ""),
        "group": group,
        "chain": _chain(row.get("chain")),
        "identity_kind": identity_kind,
        "identity_value": identity_value,
        "symbol": symbol,
    }


def _raw_response_evidence(
    *,
    raw_response_bytes: bytes | None,
    claimed_sha256: str | None,
    claimed_byte_count: int | None,
    claimed_bytes_scope: str | None,
    transport_started_at: str | None,
    observed_at: str | None,
    ingested_at: str | None,
    generated_at: str,
    parsed_payload: Any,
) -> dict[str, Any]:
    """Build a bounded receipt for the exact bytes parsed by the HTTP client.

    The client requests and enforces identity content encoding, then reads with
    ``httpx.Response.iter_raw``.  HTTP transfer framing has already been removed,
    but no content decoder has transformed these exact application-body bytes.
    The scope label keeps that boundary explicit.
    """

    reasons: list[str] = []
    exact_bytes_base64: str | None = None
    actual_sha256: str | None = None
    actual_byte_count: int | None = None
    if type(raw_response_bytes) is not bytes:
        reasons.append("RAW_RESPONSE_BYTES_MISSING")
    else:
        actual_byte_count = len(raw_response_bytes)
        if actual_byte_count > MAX_MORALIS_RAW_RESPONSE_BYTES:
            reasons.append("RAW_RESPONSE_BYTE_LIMIT_EXCEEDED")
        else:
            actual_sha256 = hashlib.sha256(raw_response_bytes).hexdigest()
            exact_bytes_base64 = base64.b64encode(raw_response_bytes).decode("ascii")
            try:
                parsed_exact = json.loads(
                    raw_response_bytes,
                    object_pairs_hook=_reject_duplicate_json_object_keys,
                    parse_constant=_reject_nonfinite_json_constant,
                )
                _validate_closed_json(parsed_exact)
                exact_canonical = _json_bytes(parsed_exact)
                supplied_canonical = _json_bytes(parsed_payload)
            except (RecursionError, TypeError, UnicodeError, ValueError):
                reasons.append("RAW_RESPONSE_JSON_INVALID")
            else:
                if exact_canonical != supplied_canonical:
                    reasons.append("RAW_RESPONSE_PARSED_PAYLOAD_MISMATCH")
    if (
        not isinstance(claimed_byte_count, int)
        or isinstance(claimed_byte_count, bool)
        or actual_byte_count is None
        or claimed_byte_count != actual_byte_count
    ):
        reasons.append("RAW_RESPONSE_BYTE_COUNT_MISMATCH")
    if (
        not isinstance(claimed_sha256, str)
        or _SHA256_RE.fullmatch(claimed_sha256) is None
        or actual_sha256 is None
        or claimed_sha256 != actual_sha256
    ):
        reasons.append("RAW_RESPONSE_SHA256_MISMATCH")
    if claimed_bytes_scope != MORALIS_RAW_RESPONSE_BYTES_SCOPE:
        reasons.append("RAW_RESPONSE_BYTES_SCOPE_INVALID")

    clocks: dict[str, datetime] = {}
    for name, value in (
        ("transport_started_at", transport_started_at),
        ("observed_at", observed_at),
        ("ingested_at", ingested_at),
        ("generated_at", generated_at),
    ):
        parsed = _parse_utc(value)
        if parsed is None:
            reasons.append(f"{name.upper()}_MISSING_OR_INVALID")
        else:
            clocks[name] = parsed
    for earlier, later, reason in (
        ("transport_started_at", "observed_at", "TRANSPORT_STARTED_AT_AFTER_OBSERVED_AT"),
        ("observed_at", "ingested_at", "OBSERVED_AT_AFTER_INGESTED_AT"),
        ("ingested_at", "generated_at", "INGESTED_AT_AFTER_GENERATED_AT"),
    ):
        if earlier in clocks and later in clocks and clocks[earlier] > clocks[later]:
            reasons.append(reason)
    unique_reasons = sorted(set(reasons))
    return {
        "raw_response_evidence_schema_version": "moralis_raw_response_evidence_v1",
        "raw_response_bytes_scope": MORALIS_RAW_RESPONSE_BYTES_SCOPE,
        "raw_response_body_base64": exact_bytes_base64,
        "raw_response_byte_count": actual_byte_count,
        "raw_response_sha256": actual_sha256,
        "raw_response_digest_algorithm": "sha256" if actual_sha256 is not None else None,
        "raw_response_evidence_bound": not unique_reasons,
        "raw_response_evidence_rejection_reasons": unique_reasons,
        "transport_started_at": transport_started_at,
        "observed_at": observed_at,
        "ingested_at": ingested_at,
        "generated_at": generated_at,
        "available_at": None,
    }


def _reject_duplicate_json_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _source_observation_payload(
    normalized: Mapping[str, Any],
    *,
    raw_response_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    fields = (
        "schema_version",
        "provider",
        "endpoint_id",
        "feature_family",
        "symbol",
        "chain",
        "wallet",
        "token",
        "event_time",
        "source_window_seconds",
        "features",
        "abi_feature_names",
        "feature_evidence",
        "feature_rejection_reasons",
        "diagnostic_features",
        "diagnostic_feature_names",
        "diagnostic_evidence",
        "normalization_rejection_reasons",
        "canonical_records",
        "canonical_record_count",
        "raw_transport_record_count",
        "source_feature_claim_count",
        "source_diagnostic_claim_count",
        "source_semantic_claim_count",
        "admitted_feature_count",
        "classifier_authentication_key_id",
        "classifier_request_target_kind",
        "classifier_request_target",
        "actual_payload_present",
        "semantic_payload_present",
        "feature_payload_present",
        "diagnostic_payload_present",
        "heartbeat_only",
    )
    payload = {field: normalized.get(field) for field in fields}
    if raw_response_evidence.get("raw_response_evidence_bound") is True:
        payload.update(dict(raw_response_evidence))
    payload.update(
        {
            "available_at": None,
            "publication_authority": False,
            "postcommit_receipt_bound": False,
            "trainer_authority": False,
            "prediction_authority": False,
            "risk_authority": False,
            "orchestrator_authority": False,
            "allocator_authority": False,
            "paper_authority": False,
            "live_authority": False,
        }
    )
    return payload


def _serialization_failure_result(
    *,
    spec: MoralisEndpointSpec,
    symbol: str | None,
    status: str,
    reason: str,
    planned_keys: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "moralis_publish_result_v2",
        "provider": "moralis",
        "endpoint_id": spec.endpoint_id,
        "symbol": symbol,
        "status": status,
        "source_observation_present": False,
        "actual_payload_present": False,
        "raw_transport_actual_payload_present": False,
        "raw_transport_record_count": 0,
        "source_semantic_claim_count": 0,
        "admitted_feature_count": 0,
        "heartbeat_only": True,
        "provider_ready": False,
        "available_at": None,
        "postcommit_receipt_bound": False,
        "publication_authority": False,
        "publication_atomic": False,
        "publication_acknowledged": False,
        "publication_attempt_status": "STRICT_JSON_SERIALIZATION_REJECTED",
        "aggregate_update_status": "NOT_ATTEMPTED_SERIALIZATION_REJECTED",
        "planned_keys": planned_keys,
        "keys_written": [],
        "duplicate_keys": [],
        "skipped_keys": [],
        "skip_reasons": {},
        "failed_keys": ["STRICT_JSON_PREFLIGHT"],
        "unattempted_keys": planned_keys,
        "publication_artifact_sha256": {},
        "serialization_rejection_reasons": [reason],
        "trainer_authority": False,
        "prediction_authority": False,
        "risk_authority": False,
        "orchestrator_authority": False,
        "allocator_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def _cas_merge_feature_payload(
    redis_client: Any,
    key: str,
    *,
    envelope: Mapping[str, Any],
    spec: MoralisEndpointSpec,
    status: str,
    observed_at: str,
    token_map_count: int,
    wallet_watchlist_count: int,
    budget_status: Mapping[str, Any],
    classifier_authentication_key: bytes | None,
    classifier_authentication_key_id: str | None,
) -> dict[str, Any]:
    current_resolution = _source_artifact_resolution_reasons(
        redis_client,
        envelope,
        classifier_authentication_key=classifier_authentication_key,
        classifier_authentication_key_id=classifier_authentication_key_id,
        observed_at=observed_at,
    )
    if current_resolution:
        return {
            "update_status": "CURRENT_SOURCE_ARTIFACT_UNRESOLVED",
            "aggregate_payload": {},
            "ttl_seconds": spec.ttl_seconds,
            "rejection_reasons": current_resolution,
        }
    for _attempt in range(_MAX_CAS_ATTEMPTS):
        raw, prior, read_status = _read_exact_mapping(redis_client, key)
        if read_status != "OK":
            return {
                "update_status": "PRIOR_AGGREGATE_INVALID",
                "aggregate_payload": {},
                "ttl_seconds": spec.ttl_seconds,
                "rejection_reasons": [read_status],
            }
        filtered_prior = dict(prior)
        resolution_rejections: list[str] = []
        prior_endpoints = prior.get("endpoint_payloads")
        filtered_endpoints: dict[str, Any] = {}
        if isinstance(prior_endpoints, Mapping):
            for endpoint_key, endpoint_row in prior_endpoints.items():
                if not isinstance(endpoint_row, Mapping):
                    resolution_rejections.append(f"{endpoint_key}:PRIOR_ENDPOINT_ROW_INVALID")
                    continue
                reasons = _source_artifact_resolution_reasons(
                    redis_client,
                    endpoint_row,
                    classifier_authentication_key=classifier_authentication_key,
                    classifier_authentication_key_id=classifier_authentication_key_id,
                    observed_at=observed_at,
                )
                if reasons:
                    resolution_rejections.extend(f"{endpoint_key}:{reason}" for reason in reasons)
                    continue
                filtered_endpoints[str(endpoint_key)] = dict(endpoint_row)
        filtered_prior["endpoint_payloads"] = filtered_endpoints
        filtered_prior["source_resolution_rejection_reasons"] = resolution_rejections
        merge_result = _merge_feature_payload(
            prior=filtered_prior,
            envelope=envelope,
            spec=spec,
            status=status,
            observed_at=observed_at,
            token_map_count=token_map_count,
            wallet_watchlist_count=wallet_watchlist_count,
            budget_status=budget_status,
            classifier_authentication_key=classifier_authentication_key,
            classifier_authentication_key_id=classifier_authentication_key_id,
        )
        if merge_result["update_status"] != "DETERMINISTIC_NEWER_SOURCE_ACCEPTED":
            if merge_result["update_status"] == "EXACT_DUPLICATE_NO_REFRESH":
                return {
                    **merge_result,
                    "aggregate_payload": dict(prior),
                    "artifact_sha256": (
                        hashlib.sha256(raw.encode("utf-8")).hexdigest()
                        if isinstance(raw, str)
                        else None
                    ),
                }
            return merge_result
        try:
            encoded = _json_bytes(merge_result["aggregate_payload"])
        except (TypeError, ValueError) as exc:
            return {
                **merge_result,
                "update_status": "AGGREGATE_STRICT_JSON_SERIALIZATION_REJECTED",
                "rejection_reasons": [type(exc).__name__],
            }
        cas_status = _cas_set_json_ack(
            redis_client,
            key,
            expected_raw=raw,
            encoded=encoded,
            ex=int(merge_result["ttl_seconds"]),
        )
        if cas_status == "APPLIED":
            return {
                **merge_result,
                "update_status": "APPLIED_NEWER_ATOMIC_CAS",
                "artifact_sha256": hashlib.sha256(encoded).hexdigest(),
                "cas_attempt_count": _attempt + 1,
            }
        if cas_status != "CONFLICT_RETRY":
            return {
                **merge_result,
                "update_status": "AGGREGATE_CAS_WRITE_FAILED",
                "rejection_reasons": [cas_status],
            }
    return {
        "update_status": "AGGREGATE_CAS_RETRY_EXHAUSTED",
        "aggregate_payload": {},
        "ttl_seconds": spec.ttl_seconds,
        "rejection_reasons": ["CONCURRENT_UPDATE_RETRY_EXHAUSTED"],
    }


def _merge_feature_payload(
    *,
    prior: Mapping[str, Any],
    envelope: Mapping[str, Any],
    spec: MoralisEndpointSpec,
    status: str,
    observed_at: str,
    token_map_count: int = 0,
    wallet_watchlist_count: int = 0,
    budget_status: Mapping[str, Any] | None = None,
    classifier_authentication_key: bytes | None = None,
    classifier_authentication_key_id: str | None = None,
) -> dict[str, Any]:
    endpoint_payloads: dict[str, dict[str, Any]] = {}
    prior_resolution_rejections = prior.get("source_resolution_rejection_reasons")
    endpoint_rejections: list[str] = (
        [str(value) for value in prior_resolution_rejections if isinstance(value, str)]
        if isinstance(prior_resolution_rejections, list)
        else []
    )
    now_dt = _parse_utc(observed_at) or datetime.now(UTC)
    source_state_reasons = _source_state_reasons(prior.get("source_state_reasons"))
    source_state_reasons.pop(spec.endpoint_id, None)
    prior_endpoints = prior.get("endpoint_payloads")
    if isinstance(prior_endpoints, Mapping):
        for endpoint_id, row in prior_endpoints.items():
            if not isinstance(row, Mapping):
                continue
            expires_at = _parse_utc(row.get("expires_at"))
            if expires_at is None or expires_at <= now_dt:
                endpoint_rejections.append(f"{endpoint_id}:SOURCE_OBSERVATION_STALE")
                continue
            integrity_reasons = _endpoint_integrity_rejection_reasons(
                row,
                classifier_authentication_key=classifier_authentication_key,
                classifier_authentication_key_id=classifier_authentication_key_id,
            )
            if integrity_reasons:
                endpoint_rejections.extend(
                    f"{endpoint_id}:{reason}" for reason in integrity_reasons
                )
                continue
            endpoint_payloads[str(endpoint_id)] = dict(row)

    admission_rejections = _endpoint_admission_rejection_reasons(
        envelope,
        observed_at=now_dt,
    )
    endpoint_row = {
        "endpoint_id": spec.endpoint_id,
        "feature_family": spec.group,
        "symbol": envelope.get("symbol"),
        "chain": envelope.get("chain"),
        "wallet": envelope.get("wallet"),
        "token": envelope.get("token"),
        "source_identity": envelope.get("source_identity"),
        "source_identity_material_canonical_json": envelope.get(
            "source_identity_material_canonical_json"
        ),
        "source_identity_material_sha256": envelope.get("source_identity_material_sha256"),
        "source_key": envelope.get("source_key"),
        "source_schema_version": envelope.get("source_schema_version"),
        "source_payload_canonical_json": envelope.get("source_payload_canonical_json"),
        "source_payload_sha256": envelope.get("source_payload_sha256"),
        "source_payload_digest_algorithm": "sha256",
        "source_binding_canonical_json": envelope.get("source_binding_canonical_json"),
        "source_binding_sha256": envelope.get("source_binding_sha256"),
        "raw_response_evidence_schema_version": envelope.get(
            "raw_response_evidence_schema_version"
        ),
        "raw_response_evidence_bound": envelope.get("raw_response_evidence_bound") is True,
        "raw_response_evidence_persisted": (
            envelope.get("raw_response_evidence_persisted") is True
        ),
        "raw_response_evidence_rejection_reasons": list(
            envelope.get("raw_response_evidence_rejection_reasons") or []
        ),
        "raw_response_sha256": envelope.get("raw_response_sha256"),
        "raw_response_byte_count": envelope.get("raw_response_byte_count"),
        "raw_response_bytes_scope": envelope.get("raw_response_bytes_scope"),
        "source_artifact_expires_at": envelope.get("source_artifact_expires_at"),
        "raw_provenance_ttl_seconds": envelope.get("raw_provenance_ttl_seconds"),
        "classifier_authentication_key_id": envelope.get("classifier_authentication_key_id"),
        "classifier_request_target_kind": envelope.get("classifier_request_target_kind"),
        "classifier_request_target": envelope.get("classifier_request_target"),
        "features": dict(envelope.get("features") or {}),
        "diagnostic_features": dict(envelope.get("diagnostic_features") or {}),
        "raw_transport_record_count": int(envelope.get("raw_transport_record_count") or 0),
        "source_feature_claim_count": int(envelope.get("source_feature_claim_count") or 0),
        "source_diagnostic_claim_count": int(envelope.get("source_diagnostic_claim_count") or 0),
        "source_semantic_claim_count": int(envelope.get("source_semantic_claim_count") or 0),
        "admitted_feature_count": 0,
        "feature_evidence": dict(envelope.get("feature_evidence") or {}),
        "diagnostic_evidence": dict(envelope.get("diagnostic_evidence") or {}),
        "feature_rejection_reasons": dict(envelope.get("feature_rejection_reasons") or {}),
        "feature_origins": dict(envelope.get("feature_origins") or {}),
        "diagnostic_origins": dict(envelope.get("diagnostic_origins") or {}),
        "event_time": envelope.get("event_time"),
        "feature_cutoff": envelope.get("feature_cutoff"),
        "transport_started_at": envelope.get("transport_started_at"),
        "observed_at": envelope.get("observed_at"),
        "ingested_at": envelope.get("ingested_at"),
        "generated_at": envelope.get("generated_at"),
        "available_at": None,
        "expires_at": _expires_at(envelope.get("generated_at"), spec.ttl_seconds),
        "source_observation_present": True,
        "actual_payload_present": False,
        "provider_ready": False,
        "publication_authority": False,
        "publication_atomic": False,
        "postcommit_receipt_bound": False,
        "publication_status": "NON_AUTHORITATIVE_POSTCOMMIT_RECEIPT_UNBOUND",
        "trainer_authority": False,
        "prediction_authority": False,
        "risk_authority": False,
        "orchestrator_authority": False,
        "allocator_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "status": status,
        "ttl_seconds": spec.ttl_seconds,
        "admission_rejection_reasons": admission_rejections,
    }
    integrity_reasons = _endpoint_integrity_rejection_reasons(
        endpoint_row,
        classifier_authentication_key=classifier_authentication_key,
        classifier_authentication_key_id=classifier_authentication_key_id,
    )
    if integrity_reasons:
        return {
            "update_status": "CURRENT_SOURCE_INTEGRITY_REJECTED",
            "aggregate_payload": dict(prior),
            "ttl_seconds": max(1, int(spec.ttl_seconds)),
            "rejection_reasons": integrity_reasons,
        }
    monotonic_status = _monotonic_source_update_status(endpoint_payloads, endpoint_row)
    if monotonic_status != "DETERMINISTIC_NEWER_SOURCE_ACCEPTED":
        return {
            "update_status": monotonic_status,
            "aggregate_payload": dict(prior),
            "ttl_seconds": max(1, int(spec.ttl_seconds)),
            "rejection_reasons": [monotonic_status],
        }
    _upsert_endpoint_claim(endpoint_payloads, endpoint_row)
    endpoint_rejections.extend(f"{spec.endpoint_id}:{reason}" for reason in admission_rejections)

    (
        merged_features,
        merged_evidence,
        merged_origins,
        feature_conflicts,
        merge_rejections,
    ) = _merge_claims(endpoint_payloads, field="features", allowed=FEATURE_NAMES)
    (
        merged_diagnostics,
        merged_diagnostic_evidence,
        merged_diagnostic_origins,
        diagnostic_conflicts,
        diagnostic_rejections,
    ) = _merge_claims(
        endpoint_payloads,
        field="diagnostic_features",
        allowed=DIAGNOSTIC_FEATURE_NAMES,
    )
    endpoint_rejections.extend(merge_rejections)
    endpoint_rejections.extend(diagnostic_rejections)
    active_expires = [
        value
        for value in (_parse_utc(row.get("expires_at")) for row in endpoint_payloads.values())
        if value is not None
    ]
    active_provenance_expires = [
        value
        for value in (
            _parse_utc(row.get("source_artifact_expires_at")) for row in endpoint_payloads.values()
        )
        if value is not None
    ]
    bounded_expires = [*active_expires, *active_provenance_expires]
    ttl = spec.ttl_seconds
    if bounded_expires:
        ttl = max(1, int((min(bounded_expires) - now_dt).total_seconds()))
    aggregate_expires_at = _iso_utc(min(bounded_expires)) if bounded_expires else None
    source_provenance_expires_at = (
        _iso_utc(min(active_provenance_expires)) if active_provenance_expires else None
    )
    raw_transport_record_count = sum(
        _strict_nonnegative_count(row.get("raw_transport_record_count")) or 0
        for row in endpoint_payloads.values()
    )
    source_feature_claim_count = sum(
        _strict_nonnegative_count(row.get("source_feature_claim_count")) or 0
        for row in endpoint_payloads.values()
    )
    source_diagnostic_claim_count = sum(
        _strict_nonnegative_count(row.get("source_diagnostic_claim_count")) or 0
        for row in endpoint_payloads.values()
    )
    event_time = _latest_strict_utc(
        [str(row["event_time"]) for row in endpoint_payloads.values() if row.get("event_time")]
    )
    feature_cutoff = _latest_strict_utc(
        [
            str(row["feature_cutoff"])
            for row in endpoint_payloads.values()
            if row.get("feature_cutoff")
        ]
    )
    generated_at = _latest_strict_utc(
        [str(row["generated_at"]) for row in endpoint_payloads.values() if row.get("generated_at")],
        microseconds=True,
    )
    transport_started_at = _latest_strict_utc(
        [
            str(row["transport_started_at"])
            for row in endpoint_payloads.values()
            if row.get("transport_started_at")
        ],
        microseconds=True,
    )
    response_observed_at = _latest_strict_utc(
        [str(row["observed_at"]) for row in endpoint_payloads.values() if row.get("observed_at")],
        microseconds=True,
    )
    ingested_at = _latest_strict_utc(
        [str(row["ingested_at"]) for row in endpoint_payloads.values() if row.get("ingested_at")],
        microseconds=True,
    )
    raw_response_evidence_bound_endpoint_count = sum(
        row.get("raw_response_evidence_bound") is True for row in endpoint_payloads.values()
    )
    feature_rejection_reasons = _merge_feature_rejection_reasons(endpoint_payloads)
    for name in feature_conflicts:
        feature_rejection_reasons[name] = ["FEATURE_CONFLICT_QUARANTINED"]
    aggregate = build_moralis_feature_payload(
        symbol=str(envelope.get("symbol") or ""),
        timeframe=str(envelope.get("timeframe") or "1m"),
        features=merged_features,
        diagnostic_features=merged_diagnostics,
        feature_evidence=merged_evidence,
        diagnostic_evidence=merged_diagnostic_evidence,
        feature_rejection_reasons=feature_rejection_reasons,
        feature_origins=merged_origins,
        diagnostic_origins=merged_diagnostic_origins,
        feature_conflicts=feature_conflicts,
        source_state_reasons=source_state_reasons,
        token_map_count=token_map_count,
        wallet_watchlist_count=wallet_watchlist_count,
        actual_payload_present=bool(merged_features or merged_diagnostics),
        event_time=event_time,
        feature_cutoff=feature_cutoff,
        ingested_at=ingested_at,
        available_at=None,
        ttl_seconds=ttl,
        stale_after=ttl,
        compute_unit_status=budget_status or envelope.get("compute_budget_status") or {},
        upstream_temporal_rejection_reasons=sorted(set(endpoint_rejections)),
    )
    aggregate.update(
        {
            "schema_version": "moralis_feature_aggregate_v2",
            "endpoint_id": "moralis_aggregate",
            "feature_family": "moralis_aggregate",
            "chain": envelope.get("chain"),
            "wallet": envelope.get("wallet"),
            "token": envelope.get("token"),
            "event_time": event_time,
            "feature_cutoff": feature_cutoff,
            "transport_started_at": transport_started_at,
            "observed_at": response_observed_at,
            "ingested_at": ingested_at,
            "generated_at": generated_at or aggregate.get("generated_at"),
            "expires_at": aggregate_expires_at,
            "source_provenance_expires_at": source_provenance_expires_at,
            "aggregate_expiry_bounded_by_source_provenance": bool(
                aggregate_expires_at
                and source_provenance_expires_at
                and aggregate_expires_at <= source_provenance_expires_at
            ),
            "available_at": None,
            "features": {},
            "source_features": merged_features,
            "diagnostic_features": merged_diagnostics,
            "feature_evidence": merged_evidence,
            "feature_origins": merged_origins,
            "diagnostic_evidence": merged_diagnostic_evidence,
            "diagnostic_origins": merged_diagnostic_origins,
            "feature_conflicts": feature_conflicts,
            "diagnostic_conflicts": diagnostic_conflicts,
            "source_state_reasons": source_state_reasons,
            "endpoint_payloads": endpoint_payloads,
            "source_observation_endpoint_count": len(endpoint_payloads),
            "raw_response_evidence_bound_endpoint_count": (
                raw_response_evidence_bound_endpoint_count
            ),
            "all_endpoint_raw_response_evidence_bound": bool(endpoint_payloads)
            and raw_response_evidence_bound_endpoint_count == len(endpoint_payloads),
            "raw_transport_record_count": raw_transport_record_count,
            "source_feature_claim_count": source_feature_claim_count,
            "source_diagnostic_claim_count": source_diagnostic_claim_count,
            "source_semantic_claim_count": (
                source_feature_claim_count + source_diagnostic_claim_count
            ),
            "admitted_feature_count": 0,
            "actual_payload_endpoint_count": 0,
            "admissible_endpoint_count": 0,
            "endpoint_temporal_rejection_reasons": sorted(set(endpoint_rejections)),
            "endpoint_rejection_reasons": sorted(set(endpoint_rejections)),
            "source_resolution_rejection_reasons": sorted(
                set(
                    str(value)
                    for value in (
                        prior_resolution_rejections
                        if isinstance(prior_resolution_rejections, list)
                        else []
                    )
                )
            ),
            "rejected_endpoint_count": len(
                {reason.split(":", 1)[0] for reason in endpoint_rejections}
            ),
            "source_available_at": None,
            "provider_ready": False,
            "feature_bridge_ready": False,
            "publication_authority": False,
            "publication_atomic": False,
            "postcommit_receipt_bound": False,
            "publication_status": "NON_AUTHORITATIVE_POSTCOMMIT_RECEIPT_UNBOUND",
            "aggregate_update_contract": "MONOTONIC_ATOMIC_CAS_V1",
            "subscription_status": "SOURCE_OBSERVATION_NON_AUTHORITATIVE"
            if endpoint_payloads
            else status,
            "auth_status": status,
            "dashboard_color": "GRAY",
            "trainer_authority": False,
            "prediction_authority": False,
            "risk_authority": False,
            "orchestrator_authority": False,
            "allocator_authority": False,
            "paper_authority": False,
            "live_authority": False,
        }
    )
    return {
        "update_status": "DETERMINISTIC_NEWER_SOURCE_ACCEPTED",
        "aggregate_payload": aggregate,
        "ttl_seconds": ttl,
        "merged_features": merged_features,
        "merged_diagnostics": merged_diagnostics,
        "merged_evidence": merged_evidence,
        "merged_origins": merged_origins,
        "merged_diagnostic_evidence": merged_diagnostic_evidence,
        "merged_diagnostic_origins": merged_diagnostic_origins,
        "feature_conflicts": feature_conflicts,
        "source_observation_present": bool(merged_features or merged_diagnostics),
    }


def _merge_claims(
    endpoint_payloads: Mapping[str, Mapping[str, Any]],
    *,
    field: str,
    allowed: tuple[str, ...],
) -> tuple[
    dict[str, float],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, Any],
    list[str],
]:
    claims: dict[str, list[dict[str, Any]]] = {name: [] for name in allowed}
    rejections: list[str] = []
    for endpoint_id, row in endpoint_payloads.items():
        values = row.get(field)
        if not isinstance(values, Mapping):
            continue
        evidence_field = "feature_evidence" if field == "features" else "diagnostic_evidence"
        origins_field = "feature_origins" if field == "features" else "diagnostic_origins"
        evidence_map = row.get(evidence_field)
        if not isinstance(evidence_map, Mapping):
            evidence_map = {}
        origins = row.get(origins_field)
        if not isinstance(origins, Mapping):
            origins = {}
        for name in allowed:
            if name not in values:
                continue
            value = _finite_number(values.get(name))
            evidence = evidence_map.get(name)
            origin = origins.get(name)
            if value is None:
                rejections.append(f"{endpoint_id}:{name}:NUMERIC_VALUE_INVALID")
                continue
            if not _feature_evidence_valid(evidence):
                rejections.append(f"{endpoint_id}:{name}:SEMANTIC_EVIDENCE_INVALID")
                continue
            if not _feature_origin_matches_row(origin, row, evidence=evidence):
                rejections.append(f"{endpoint_id}:{name}:SOURCE_ORIGIN_INVALID")
                continue
            claims[name].append(
                {
                    "endpoint_id": endpoint_id,
                    "value": value,
                    "evidence": dict(evidence) if isinstance(evidence, Mapping) else {},
                    "origin": dict(origin) if isinstance(origin, Mapping) else {},
                }
            )
    merged: dict[str, float] = {}
    evidence_out: dict[str, dict[str, Any]] = {}
    origins_out: dict[str, dict[str, Any]] = {}
    conflicts: dict[str, Any] = {}
    for name, rows in claims.items():
        if not rows:
            continue
        if len(rows) > 1:
            conflicts[name] = {
                "reason": "MULTIPLE_SOURCE_CLAIMS_NO_AGGREGATION_POLICY",
                "claims": [
                    {
                        "endpoint_id": item["endpoint_id"],
                        "value": item["value"],
                        "source_key": item["origin"].get("source_key"),
                        "source_payload_sha256": item["origin"].get("source_payload_sha256"),
                    }
                    for item in rows
                ],
            }
            rejections.append(f"aggregate:{name}:FEATURE_CONFLICT_QUARANTINED")
            continue
        claim = rows[0]
        merged[name] = claim["value"]
        evidence_out[name] = claim["evidence"]
        origins_out[name] = claim["origin"]
    return merged, evidence_out, origins_out, conflicts, rejections


def _upsert_endpoint_claim(
    endpoint_payloads: dict[str, dict[str, Any]],
    row: Mapping[str, Any],
) -> None:
    """Retain distinct source identities; replace only the same source's later sample."""
    endpoint_id = str(row.get("endpoint_id") or "")
    source_identity = str(row.get("source_identity") or "")
    peers = [
        key for key, prior in endpoint_payloads.items() if prior.get("endpoint_id") == endpoint_id
    ]
    same_source = [
        key for key in peers if endpoint_payloads[key].get("source_identity") == source_identity
    ]
    if same_source:
        endpoint_payloads[same_source[0]] = dict(row)
        return
    if not peers:
        endpoint_payloads[endpoint_id] = dict(row)
        return
    for key in peers:
        prior = endpoint_payloads.pop(key)
        endpoint_payloads[_endpoint_claim_key(prior)] = prior
    endpoint_payloads[_endpoint_claim_key(row)] = dict(row)


def _monotonic_source_update_status(
    endpoint_payloads: Mapping[str, Mapping[str, Any]],
    row: Mapping[str, Any],
) -> str:
    source_identity = row.get("source_identity")
    peers = [
        prior
        for prior in endpoint_payloads.values()
        if prior.get("source_identity") == source_identity
    ]
    if not peers:
        return "DETERMINISTIC_NEWER_SOURCE_ACCEPTED"
    if len(peers) != 1:
        return "SAME_SOURCE_IDENTITY_MULTIPLE_PRIORS_QUARANTINED"
    prior = peers[0]
    prior_clock = _parse_utc(prior.get("event_time"))
    new_clock = _parse_utc(row.get("event_time"))
    prior_digest = _source_event_content_digest(prior)
    new_digest = _source_event_content_digest(row)
    if prior_clock is None or new_clock is None:
        return "SOURCE_EVENT_CLOCK_INVALID"
    if new_clock < prior_clock:
        return "OLDER_SOURCE_EVENT_REJECTED"
    if new_clock == prior_clock:
        if prior_digest == new_digest:
            return "EXACT_DUPLICATE_NO_REFRESH"
        return "SAME_CLOCK_DIVERGENT_DIGEST_QUARANTINED"
    return "DETERMINISTIC_NEWER_SOURCE_ACCEPTED"


def _source_event_content_digest(row: Mapping[str, Any]) -> Any:
    raw_digest = row.get("raw_response_sha256")
    if row.get("raw_response_evidence_bound") is True and isinstance(raw_digest, str):
        return raw_digest
    return row.get("source_payload_sha256")


def _endpoint_claim_key(row: Mapping[str, Any]) -> str:
    endpoint_id = str(row.get("endpoint_id") or "unknown")
    source_identity = str(row.get("source_identity") or "")
    identity = hashlib.sha256(f"{endpoint_id}\x00{source_identity}".encode()).hexdigest()
    return f"{endpoint_id}#{identity}"


def _feature_origins(
    normalized: Mapping[str, Any],
    *,
    source_identity: str,
    source_key: str,
    source_payload_sha256: str,
    source_binding_sha256: str,
) -> dict[str, dict[str, Any]]:
    features = normalized.get("features")
    evidence = normalized.get("feature_evidence")
    if not isinstance(features, Mapping) or not isinstance(evidence, Mapping):
        return {}
    origins: dict[str, dict[str, Any]] = {}
    for name in FEATURE_NAMES:
        row = evidence.get(name)
        if name not in features or not isinstance(row, Mapping):
            continue
        origins[name] = {
            "provider": "moralis",
            "endpoint_id": normalized.get("endpoint_id"),
            "source_identity": source_identity,
            "source_key": source_key,
            "source_schema_version": normalized.get("schema_version"),
            "source_payload_sha256": source_payload_sha256,
            "source_binding_sha256": source_binding_sha256,
            "unit": row.get("unit"),
            "direction": row.get("direction"),
            "measurement_scope": row.get("measurement_scope"),
            "contributing_rows_sha256": row.get("contributing_rows_sha256"),
            "event_time": row.get("event_time"),
            "feature_cutoff": row.get("feature_cutoff"),
        }
    return origins


def _diagnostic_origins(
    normalized: Mapping[str, Any],
    *,
    source_identity: str,
    source_key: str,
    source_payload_sha256: str,
    source_binding_sha256: str,
) -> dict[str, dict[str, Any]]:
    diagnostics = normalized.get("diagnostic_features")
    evidence = normalized.get("diagnostic_evidence")
    if not isinstance(diagnostics, Mapping) or not isinstance(evidence, Mapping):
        return {}
    origins: dict[str, dict[str, Any]] = {}
    for name in DIAGNOSTIC_FEATURE_NAMES:
        row = evidence.get(name)
        if name not in diagnostics or not isinstance(row, Mapping):
            continue
        origins[name] = {
            "provider": "moralis",
            "endpoint_id": normalized.get("endpoint_id"),
            "source_identity": source_identity,
            "source_key": source_key,
            "source_schema_version": normalized.get("schema_version"),
            "source_payload_sha256": source_payload_sha256,
            "source_binding_sha256": source_binding_sha256,
            "unit": row.get("unit"),
            "direction": row.get("direction"),
            "measurement_scope": row.get("measurement_scope"),
            "contributing_rows_sha256": row.get("contributing_rows_sha256"),
            "event_time": row.get("event_time"),
            "feature_cutoff": row.get("feature_cutoff"),
        }
    return origins


def _raw_response_receipt_integrity_reasons(
    row: Mapping[str, Any],
    source_payload: Mapping[str, Any],
) -> list[str]:
    if row.get("raw_response_evidence_bound") is not True:
        return []
    reasons: list[str] = []
    if source_payload.get("raw_response_evidence_schema_version") != (
        "moralis_raw_response_evidence_v1"
    ):
        reasons.append("RAW_RESPONSE_EVIDENCE_SCHEMA_INVALID")
    if source_payload.get("raw_response_bytes_scope") != MORALIS_RAW_RESPONSE_BYTES_SCOPE:
        reasons.append("RAW_RESPONSE_BYTES_SCOPE_INVALID")
    if source_payload.get("raw_response_digest_algorithm") != "sha256":
        reasons.append("RAW_RESPONSE_DIGEST_ALGORITHM_INVALID")
    if source_payload.get("available_at") is not None:
        reasons.append("RAW_RESPONSE_AVAILABLE_AT_MUST_BE_NULL")
    encoded = source_payload.get("raw_response_body_base64")
    raw_bytes: bytes | None = None
    if not isinstance(encoded, str) or not encoded:
        reasons.append("RAW_RESPONSE_EXACT_BYTES_MISSING")
    elif len(encoded) > ((MAX_MORALIS_RAW_RESPONSE_BYTES + 2) // 3) * 4:
        reasons.append("RAW_RESPONSE_BASE64_LIMIT_EXCEEDED")
    else:
        try:
            raw_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            reasons.append("RAW_RESPONSE_BASE64_INVALID")
    byte_count = source_payload.get("raw_response_byte_count")
    digest = source_payload.get("raw_response_sha256")
    if (
        not isinstance(byte_count, int)
        or isinstance(byte_count, bool)
        or byte_count < 0
        or byte_count > MAX_MORALIS_RAW_RESPONSE_BYTES
    ):
        reasons.append("RAW_RESPONSE_BYTE_COUNT_INVALID")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        reasons.append("RAW_RESPONSE_SHA256_INVALID")
    if raw_bytes is not None:
        if len(raw_bytes) > MAX_MORALIS_RAW_RESPONSE_BYTES:
            reasons.append("RAW_RESPONSE_BYTE_LIMIT_EXCEEDED")
        if byte_count != len(raw_bytes):
            reasons.append("RAW_RESPONSE_BYTE_COUNT_MISMATCH")
        if isinstance(digest, str) and hashlib.sha256(raw_bytes).hexdigest() != digest:
            reasons.append("RAW_RESPONSE_SHA256_MISMATCH")
    clock_rejections = _raw_source_clock_rejections(
        event_time=row.get("event_time"),
        transport_started_at=row.get("transport_started_at"),
        observed_at=row.get("observed_at"),
        ingested_at=row.get("ingested_at"),
        generated_at=row.get("generated_at"),
    )
    reasons.extend(
        reason
        for reason in clock_rejections
        if reason not in {"AVAILABLE_AT_UNBOUND", "POSTCOMMIT_RECEIPT_UNBOUND"}
    )
    return sorted(set(reasons))


def _endpoint_integrity_rejection_reasons(
    row: Mapping[str, Any],
    *,
    classifier_authentication_key: bytes | None = None,
    classifier_authentication_key_id: str | None = None,
) -> list[str]:
    reasons: list[str] = []
    source_key = row.get("source_key")
    source_identity = row.get("source_identity")
    identity_material_json = row.get("source_identity_material_canonical_json")
    identity_material_digest = row.get("source_identity_material_sha256")
    schema = row.get("source_schema_version")
    source_json = row.get("source_payload_canonical_json")
    digest = row.get("source_payload_sha256")
    binding_json = row.get("source_binding_canonical_json")
    binding_digest = row.get("source_binding_sha256")
    count_fields = (
        "raw_transport_record_count",
        "source_feature_claim_count",
        "source_diagnostic_claim_count",
        "source_semantic_claim_count",
        "admitted_feature_count",
    )
    for field in count_fields:
        if _strict_nonnegative_count(row.get(field)) is None:
            reasons.append(f"{field.upper()}_INVALID")
    if not isinstance(source_key, str) or not source_key:
        reasons.append("SOURCE_KEY_MISSING")
    if not isinstance(source_identity, str) or not source_identity:
        reasons.append("SOURCE_IDENTITY_MISSING")
    if not isinstance(identity_material_json, str) or not identity_material_json:
        reasons.append("SOURCE_IDENTITY_MATERIAL_MISSING")
    if not isinstance(identity_material_digest, str) or not _SHA256_RE.fullmatch(
        identity_material_digest
    ):
        reasons.append("SOURCE_IDENTITY_MATERIAL_SHA256_INVALID")
    if not isinstance(schema, str) or not schema:
        reasons.append("SOURCE_SCHEMA_VERSION_MISSING")
    elif schema != _NORMALIZED_SCHEMA:
        reasons.append("SOURCE_SCHEMA_VERSION_UNSUPPORTED")
    if row.get("source_payload_digest_algorithm") != "sha256":
        reasons.append("SOURCE_PAYLOAD_DIGEST_ALGORITHM_INVALID")
    if not isinstance(source_json, str) or not source_json:
        reasons.append("SOURCE_PAYLOAD_BYTES_MISSING")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        reasons.append("SOURCE_PAYLOAD_SHA256_INVALID")
    elif (
        isinstance(source_key, str)
        and isinstance(source_identity, str)
        and source_key != f"v2:moralis:raw:v2:{source_identity}:{digest}"
    ):
        reasons.append("SOURCE_CONTENT_ADDRESS_KEY_MISMATCH")
    if isinstance(source_key, str) and not _redis_key_valid(source_key):
        reasons.append("SOURCE_KEY_SEGMENTS_INVALID")
    if not isinstance(binding_json, str) or not binding_json:
        reasons.append("SOURCE_BINDING_BYTES_MISSING")
    if not isinstance(binding_digest, str) or not _SHA256_RE.fullmatch(binding_digest):
        reasons.append("SOURCE_BINDING_SHA256_INVALID")
    source_payload: Mapping[str, Any] | None = None
    if isinstance(source_json, str):
        try:
            parsed_source = json.loads(source_json)
        except (TypeError, ValueError):
            reasons.append("SOURCE_PAYLOAD_JSON_INVALID")
        else:
            if isinstance(parsed_source, Mapping):
                source_payload = parsed_source
                try:
                    canonical_source = _json_bytes(parsed_source).decode("utf-8")
                except (TypeError, ValueError):
                    reasons.append("SOURCE_PAYLOAD_JSON_INVALID")
                    source_payload = None
                else:
                    if canonical_source != source_json:
                        reasons.append("SOURCE_PAYLOAD_NOT_CANONICAL")
            else:
                reasons.append("SOURCE_PAYLOAD_ENVELOPE_INVALID")
    if isinstance(digest, str) and _SHA256_RE.fullmatch(digest) and isinstance(source_json, str):
        actual_digest = hashlib.sha256(source_json.encode("utf-8")).hexdigest()
        if actual_digest != digest:
            reasons.append("SOURCE_PAYLOAD_SHA256_MISMATCH")
    if (
        isinstance(binding_digest, str)
        and _SHA256_RE.fullmatch(binding_digest)
        and isinstance(binding_json, str)
    ):
        actual_binding_digest = hashlib.sha256(binding_json.encode("utf-8")).hexdigest()
        if actual_binding_digest != binding_digest:
            reasons.append("SOURCE_BINDING_SHA256_MISMATCH")
        try:
            binding_payload = json.loads(binding_json)
        except (TypeError, ValueError):
            reasons.append("SOURCE_BINDING_JSON_INVALID")
        else:
            expected_binding = {
                "endpoint_id": row.get("endpoint_id"),
                "provider": "moralis",
                "source_identity": row.get("source_identity"),
                "source_key": row.get("source_key"),
                "source_payload_sha256": row.get("source_payload_sha256"),
                "source_schema_version": row.get("source_schema_version"),
            }
            if (
                not isinstance(binding_payload, Mapping)
                or dict(binding_payload) != expected_binding
            ):
                reasons.append("SOURCE_BINDING_IDENTITY_MISMATCH")
            else:
                try:
                    canonical_binding = _json_bytes(expected_binding).decode("utf-8")
                except (TypeError, ValueError):
                    reasons.append("SOURCE_BINDING_JSON_INVALID")
                else:
                    if canonical_binding != binding_json:
                        reasons.append("SOURCE_BINDING_NOT_CANONICAL")
    if source_payload is not None:
        if (
            source_payload.get("provider") != "moralis"
            or source_payload.get("endpoint_id") != row.get("endpoint_id")
            or source_payload.get("schema_version") != schema
        ):
            reasons.append("SOURCE_PAYLOAD_IDENTITY_MISMATCH")
        for row_field, source_field, reason in (
            ("feature_family", "feature_family", "SOURCE_FEATURE_FAMILY_MISMATCH"),
            ("symbol", "symbol", "SOURCE_SYMBOL_MISMATCH"),
            ("chain", "chain", "SOURCE_CHAIN_MISMATCH"),
            ("wallet", "wallet", "SOURCE_WALLET_MISMATCH"),
            ("token", "token", "SOURCE_TOKEN_MISMATCH"),
            ("event_time", "event_time", "SOURCE_EVENT_TIME_MISMATCH"),
        ):
            if row.get(row_field) != source_payload.get(source_field):
                reasons.append(reason)
        if row.get("raw_response_evidence_bound") is True:
            for row_field, source_field, reason in (
                (
                    "transport_started_at",
                    "transport_started_at",
                    "SOURCE_TRANSPORT_STARTED_AT_MISMATCH",
                ),
                ("observed_at", "observed_at", "SOURCE_OBSERVED_AT_MISMATCH"),
                ("ingested_at", "ingested_at", "SOURCE_INGESTED_AT_MISMATCH"),
                ("generated_at", "generated_at", "SOURCE_GENERATED_AT_MISMATCH"),
                (
                    "raw_response_evidence_schema_version",
                    "raw_response_evidence_schema_version",
                    "SOURCE_RAW_RESPONSE_EVIDENCE_SCHEMA_MISMATCH",
                ),
                (
                    "raw_response_evidence_bound",
                    "raw_response_evidence_bound",
                    "SOURCE_RAW_RESPONSE_EVIDENCE_BOUND_MISMATCH",
                ),
                (
                    "raw_response_sha256",
                    "raw_response_sha256",
                    "SOURCE_RAW_RESPONSE_SHA256_MISMATCH",
                ),
                (
                    "raw_response_byte_count",
                    "raw_response_byte_count",
                    "SOURCE_RAW_RESPONSE_BYTE_COUNT_MISMATCH",
                ),
                (
                    "raw_response_bytes_scope",
                    "raw_response_bytes_scope",
                    "SOURCE_RAW_RESPONSE_BYTES_SCOPE_MISMATCH",
                ),
            ):
                if row.get(row_field) != source_payload.get(source_field):
                    reasons.append(reason)
        for field in count_fields:
            source_label = field.removeprefix("source_").upper()
            source_count = _strict_nonnegative_count(source_payload.get(field))
            if source_count is None:
                reasons.append(f"EXACT_SOURCE_{source_label}_INVALID")
            elif row.get(field) != source_count:
                reasons.append(f"EXACT_SOURCE_{source_label}_MISMATCH")
        source_features = source_payload.get("features")
        source_diagnostics = source_payload.get("diagnostic_features")
        source_feature_count = _strict_nonnegative_count(
            source_payload.get("source_feature_claim_count")
        )
        source_diagnostic_count = _strict_nonnegative_count(
            source_payload.get("source_diagnostic_claim_count")
        )
        source_semantic_count = _strict_nonnegative_count(
            source_payload.get("source_semantic_claim_count")
        )
        if (
            isinstance(source_features, Mapping)
            and source_feature_count is not None
            and source_feature_count != len(source_features)
        ):
            reasons.append("SOURCE_FEATURE_CLAIM_COUNT_INCONSISTENT")
        if (
            isinstance(source_diagnostics, Mapping)
            and source_diagnostic_count is not None
            and source_diagnostic_count != len(source_diagnostics)
        ):
            reasons.append("SOURCE_DIAGNOSTIC_CLAIM_COUNT_INCONSISTENT")
        if (
            source_feature_count is not None
            and source_diagnostic_count is not None
            and source_semantic_count is not None
            and source_semantic_count != source_feature_count + source_diagnostic_count
        ):
            reasons.append("SOURCE_SEMANTIC_CLAIM_COUNT_INCONSISTENT")
        if source_payload.get("admitted_feature_count") != 0:
            reasons.append("SOURCE_ADMITTED_FEATURE_COUNT_MUST_BE_ZERO")
        expected_identity_material = _rederived_source_identity_material(row)
        try:
            expected_identity_bytes = _json_bytes(expected_identity_material)
        except (TypeError, ValueError):
            reasons.append("SOURCE_IDENTITY_REDERIVATION_FAILED")
        else:
            expected_identity_json = expected_identity_bytes.decode("utf-8")
            expected_identity_digest = hashlib.sha256(expected_identity_bytes).hexdigest()
            expected_identity = _source_identity_from_material(expected_identity_material)
            if identity_material_json != expected_identity_json:
                reasons.append("SOURCE_IDENTITY_MATERIAL_MISMATCH")
            if identity_material_digest != expected_identity_digest:
                reasons.append("SOURCE_IDENTITY_MATERIAL_SHA256_MISMATCH")
            if source_identity != expected_identity:
                reasons.append("SOURCE_IDENTITY_REDERIVATION_MISMATCH")
        if row.get("feature_cutoff") != source_payload.get("event_time"):
            reasons.append("SOURCE_FEATURE_CUTOFF_MISMATCH")
        if row.get("available_at") is not None:
            reasons.append("UNBOUND_AVAILABLE_AT_MUST_BE_NULL")
        reasons.extend(_raw_response_receipt_integrity_reasons(row, source_payload))
        for row_field, source_field, reason in (
            ("features", "features", "SOURCE_FEATURES_MISMATCH"),
            (
                "diagnostic_features",
                "diagnostic_features",
                "SOURCE_DIAGNOSTICS_MISMATCH",
            ),
            ("feature_evidence", "feature_evidence", "SOURCE_FEATURE_EVIDENCE_MISMATCH"),
            (
                "diagnostic_evidence",
                "diagnostic_evidence",
                "SOURCE_DIAGNOSTIC_EVIDENCE_MISMATCH",
            ),
            (
                "feature_rejection_reasons",
                "feature_rejection_reasons",
                "SOURCE_REJECTION_EVIDENCE_MISMATCH",
            ),
        ):
            row_value = row.get(row_field)
            source_value = source_payload.get(source_field)
            if not isinstance(row_value, Mapping) or dict(row_value) != dict(
                source_value if isinstance(source_value, Mapping) else {}
            ):
                reasons.append(reason)
        for origins_field, values_field, reason in (
            ("feature_origins", "features", "SOURCE_FEATURE_ORIGIN_MISMATCH"),
            (
                "diagnostic_origins",
                "diagnostic_features",
                "SOURCE_DIAGNOSTIC_ORIGIN_MISMATCH",
            ),
        ):
            origins = row.get(origins_field)
            values = row.get(values_field)
            evidence_field = (
                "feature_evidence" if values_field == "features" else "diagnostic_evidence"
            )
            evidence = row.get(evidence_field)
            if (
                not isinstance(origins, Mapping)
                or not isinstance(values, Mapping)
                or not isinstance(evidence, Mapping)
            ):
                reasons.append(reason)
                continue
            if any(
                name not in origins
                or not _feature_origin_matches_row(
                    origins.get(name),
                    row,
                    evidence=evidence.get(name),
                )
                for name in values
            ):
                reasons.append(reason)
        reasons.extend(
            classifier_evidence_reverification_reasons(
                row.get("feature_evidence"),
                chain=str(row.get("chain") or ""),
                endpoint_id=str(row.get("endpoint_id") or ""),
                request_target_kind=str(row.get("classifier_request_target_kind") or ""),
                request_target=str(row.get("classifier_request_target") or ""),
                symbol=str(row.get("symbol") or ""),
                authentication_key=classifier_authentication_key,
                authentication_key_id=classifier_authentication_key_id,
            )
        )
    endpoint_expires = _parse_utc(row.get("expires_at"))
    source_expires = _parse_utc(row.get("source_artifact_expires_at"))
    raw_ttl = row.get("raw_provenance_ttl_seconds")
    if source_expires is None:
        reasons.append("SOURCE_ARTIFACT_EXPIRY_MISSING_OR_INVALID")
    if endpoint_expires is None:
        reasons.append("ENDPOINT_EXPIRY_MISSING_OR_INVALID")
    if (
        endpoint_expires is not None
        and source_expires is not None
        and endpoint_expires > source_expires
    ):
        reasons.append("ENDPOINT_EXPIRY_OUTLIVES_SOURCE_PROVENANCE")
    if not isinstance(raw_ttl, int) or isinstance(raw_ttl, bool) or raw_ttl <= 0:
        reasons.append("RAW_PROVENANCE_TTL_INVALID")
    return sorted(set(reasons))


def _source_artifact_resolution_reasons(
    redis_client: Any,
    row: Mapping[str, Any],
    *,
    classifier_authentication_key: bytes | None = None,
    classifier_authentication_key_id: str | None = None,
    observed_at: str | None = None,
) -> list[str]:
    key = row.get("source_key")
    expected = row.get("source_payload_canonical_json")
    digest = row.get("source_payload_sha256")
    if not isinstance(key, str) or not key:
        return ["SOURCE_KEY_MISSING"]
    if not isinstance(expected, str) or not expected:
        return ["SOURCE_PAYLOAD_BYTES_MISSING"]
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        return ["SOURCE_PAYLOAD_SHA256_INVALID"]
    try:
        actual = redis_client.get(key)
        if isinstance(actual, bytes):
            if len(actual) > _MAX_JSON_BYTES:
                return ["SOURCE_ARTIFACT_BYTE_LIMIT_EXCEEDED"]
            actual = actual.decode("utf-8", errors="strict")
    except Exception:
        return ["SOURCE_ARTIFACT_READ_FAILED"]
    reasons: list[str] = []
    if actual is None:
        reasons.append("SOURCE_ARTIFACT_MISSING")
    elif not isinstance(actual, str):
        reasons.append("SOURCE_ARTIFACT_TYPE_INVALID")
    else:
        actual_bytes = actual.encode("utf-8", errors="strict")
        if len(actual_bytes) > _MAX_JSON_BYTES:
            reasons.append("SOURCE_ARTIFACT_BYTE_LIMIT_EXCEEDED")
        else:
            if actual != expected:
                reasons.append("SOURCE_ARTIFACT_EXACT_BYTES_MISMATCH")
            if hashlib.sha256(actual_bytes).hexdigest() != digest:
                reasons.append("SOURCE_ARTIFACT_SHA256_MISMATCH")
    try:
        ttl = redis_client.ttl(key)
    except Exception:
        reasons.append("SOURCE_ARTIFACT_TTL_READ_FAILED")
        ttl = None
    else:
        if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl <= 0:
            reasons.append("SOURCE_ARTIFACT_EXPIRED_OR_UNBOUNDED")
    observed = _parse_utc(observed_at)
    endpoint_expires = _parse_utc(row.get("expires_at"))
    if (
        isinstance(ttl, int)
        and not isinstance(ttl, bool)
        and ttl > 0
        and observed is not None
        and endpoint_expires is not None
        and ttl < max(1, math.ceil((endpoint_expires - observed).total_seconds()))
    ):
        reasons.append("SOURCE_ARTIFACT_TTL_SHORTER_THAN_ENDPOINT_LIFETIME")
    reasons.extend(
        _endpoint_integrity_rejection_reasons(
            row,
            classifier_authentication_key=classifier_authentication_key,
            classifier_authentication_key_id=classifier_authentication_key_id,
        )
    )
    return reasons


def _endpoint_admission_rejection_reasons(
    row: Mapping[str, Any],
    *,
    observed_at: datetime,
) -> list[str]:
    parsed: dict[str, datetime] = {}
    reasons: list[str] = []
    for field in (
        "event_time",
        "feature_cutoff",
        "transport_started_at",
        "observed_at",
        "ingested_at",
        "generated_at",
    ):
        value = row.get(field)
        if value in (None, ""):
            reasons.append(f"{field.upper()}_MISSING")
            continue
        clock = _parse_utc(value)
        if clock is None:
            reasons.append(f"{field.upper()}_NOT_STRICT_UTC")
            continue
        parsed[field] = clock
        if clock > observed_at:
            reasons.append(f"{field.upper()}_AFTER_OBSERVED_AT")
    for earlier, later, reason in (
        ("event_time", "feature_cutoff", "EVENT_TIME_AFTER_FEATURE_CUTOFF"),
        ("event_time", "observed_at", "EVENT_TIME_AFTER_OBSERVED_AT"),
        (
            "transport_started_at",
            "observed_at",
            "TRANSPORT_STARTED_AT_AFTER_OBSERVED_AT",
        ),
        ("observed_at", "ingested_at", "OBSERVED_AT_AFTER_INGESTED_AT"),
        ("feature_cutoff", "ingested_at", "FEATURE_CUTOFF_AFTER_INGESTED_AT"),
        ("ingested_at", "generated_at", "INGESTED_AT_AFTER_GENERATED_AT"),
    ):
        if earlier in parsed and later in parsed and parsed[earlier] > parsed[later]:
            reasons.append(reason)
    if row.get("raw_response_evidence_bound") is not True:
        reasons.append("RAW_RESPONSE_EVIDENCE_UNBOUND")
    reasons.extend(("AVAILABLE_AT_MISSING", "POSTCOMMIT_RECEIPT_UNBOUND"))
    return sorted(set(reasons))


def _raw_source_clock_rejections(
    *,
    event_time: Any,
    transport_started_at: Any,
    observed_at: Any,
    ingested_at: Any,
    generated_at: Any,
) -> list[str]:
    reasons = ["AVAILABLE_AT_UNBOUND", "POSTCOMMIT_RECEIPT_UNBOUND"]
    event = _parse_utc(event_time)
    transport_started = _parse_utc(transport_started_at)
    observed = _parse_utc(observed_at)
    ingested = _parse_utc(ingested_at)
    generated = _parse_utc(generated_at)
    if event is None:
        reasons.append("EVENT_TIME_MISSING_OR_INVALID")
    if transport_started is None:
        reasons.append("TRANSPORT_STARTED_AT_MISSING_OR_INVALID")
    if observed is None:
        reasons.append("OBSERVED_AT_MISSING_OR_INVALID")
    if ingested is None:
        reasons.append("INGESTED_AT_MISSING_OR_INVALID")
    if generated is None:
        reasons.append("GENERATED_AT_MISSING_OR_INVALID")
    for earlier, later, reason in (
        (event, observed, "EVENT_TIME_AFTER_OBSERVED_AT"),
        (transport_started, observed, "TRANSPORT_STARTED_AT_AFTER_OBSERVED_AT"),
        (observed, ingested, "OBSERVED_AT_AFTER_INGESTED_AT"),
        (ingested, generated, "INGESTED_AT_AFTER_GENERATED_AT"),
    ):
        if earlier is not None and later is not None and earlier > later:
            reasons.append(reason)
    return sorted(set(reasons))


def _feature_evidence_valid(value: Any) -> bool:
    return bool(
        isinstance(value, Mapping)
        and isinstance(value.get("unit"), str)
        and value.get("unit")
        and isinstance(value.get("direction"), str)
        and value.get("direction")
        and isinstance(value.get("measurement_scope"), str)
        and value.get("measurement_scope")
        and isinstance(value.get("contributing_row_count"), int)
        and not isinstance(value.get("contributing_row_count"), bool)
        and int(value["contributing_row_count"]) > 0
        and _contributor_evidence_valid(value)
    )


def _contributor_evidence_valid(value: Mapping[str, Any]) -> bool:
    rows = value.get("contributing_rows")
    count = value.get("contributing_row_count")
    expected_digest = value.get("contributing_rows_sha256")
    expected_event = _parse_utc(value.get("event_time"))
    if (
        not isinstance(rows, list)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or len(rows) != count
        or not isinstance(expected_digest, str)
        or not _SHA256_RE.fullmatch(expected_digest)
        or expected_event is None
        or value.get("feature_cutoff") != value.get("event_time")
        or value.get("freshness_status") != "FRESH_WITHIN_SOURCE_WINDOW"
    ):
        return False
    clocks: list[datetime] = []
    for receipt in rows:
        if not isinstance(receipt, Mapping):
            return False
        canonical = receipt.get("row_canonical_json")
        digest = receipt.get("row_sha256")
        clock = _parse_utc(receipt.get("event_time"))
        if (
            not isinstance(receipt.get("row_index"), int)
            or isinstance(receipt.get("row_index"), bool)
            or not isinstance(canonical, str)
            or not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
            or hashlib.sha256(canonical.encode("utf-8")).hexdigest() != digest
            or clock is None
        ):
            return False
        try:
            parsed = json.loads(canonical)
            roundtrip = _json_bytes(parsed).decode("utf-8")
        except (TypeError, ValueError):
            return False
        if not isinstance(parsed, Mapping) or roundtrip != canonical:
            return False
        clocks.append(clock)
    try:
        actual_digest = hashlib.sha256(_json_bytes(rows)).hexdigest()
    except (TypeError, ValueError):
        return False
    return actual_digest == expected_digest and max(clocks) == expected_event


def _feature_origin_matches_row(
    value: Any,
    row: Mapping[str, Any],
    *,
    evidence: Any,
) -> bool:
    return bool(
        isinstance(value, Mapping)
        and value.get("provider") == "moralis"
        and value.get("endpoint_id") == row.get("endpoint_id")
        and value.get("source_identity") == row.get("source_identity")
        and value.get("source_key") == row.get("source_key")
        and value.get("source_schema_version") == row.get("source_schema_version")
        and value.get("source_payload_sha256") == row.get("source_payload_sha256")
        and value.get("source_binding_sha256") == row.get("source_binding_sha256")
        and isinstance(evidence, Mapping)
        and value.get("unit") == evidence.get("unit")
        and value.get("direction") == evidence.get("direction")
        and value.get("measurement_scope") == evidence.get("measurement_scope")
        and value.get("contributing_rows_sha256") == evidence.get("contributing_rows_sha256")
        and value.get("event_time") == evidence.get("event_time")
        and value.get("feature_cutoff") == evidence.get("feature_cutoff")
    )


def _merge_feature_rejection_reasons(
    endpoints: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[str]]:
    out: dict[str, set[str]] = {name: set() for name in FEATURE_NAMES}
    for endpoint_id, row in endpoints.items():
        reasons = row.get("feature_rejection_reasons")
        if not isinstance(reasons, Mapping):
            continue
        for name in FEATURE_NAMES:
            values = reasons.get(name)
            if not isinstance(values, list):
                continue
            out[name].update(
                f"{endpoint_id}:{value}" for value in values if isinstance(value, str) and value
            )
    return {name: sorted(values) for name, values in out.items() if values}


def _source_state_reasons(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or len(value) > 64:
        return {}
    return {
        str(key): str(state)
        for key, state in value.items()
        if isinstance(key, str)
        and key
        and isinstance(state, str)
        and state
        and len(key.encode("utf-8")) <= 128
        and len(state.encode("utf-8")) <= 128
    }


def _first_normalization_rejection(envelope: Mapping[str, Any]) -> str:
    reasons = envelope.get("normalization_rejection_reasons")
    if isinstance(reasons, list):
        for reason in reasons:
            if isinstance(reason, str) and reason:
                return reason
    return "SOURCE_SEMANTIC_VALUES_MISSING"


def _retained_state(
    aggregate: Mapping[str, Any],
    *,
    observed_at: str,
) -> dict[str, Any]:
    observed = _parse_utc(observed_at)
    event_time = _parse_utc(aggregate.get("event_time"))
    expires_at = _parse_utc(aggregate.get("expires_at"))
    source_features = aggregate.get("source_features")
    diagnostics = aggregate.get("diagnostic_features")
    source_count = len(source_features) if isinstance(source_features, Mapping) else 0
    diagnostic_count = len(diagnostics) if isinstance(diagnostics, Mapping) else 0
    age_seconds = (
        max(0.0, (observed - event_time).total_seconds())
        if observed is not None and event_time is not None
        else None
    )
    if not aggregate:
        state = "NO_RETAINED_SOURCE_STATE"
    elif observed is None or event_time is None or expires_at is None:
        state = "RETAINED_STATE_CLOCK_INVALID"
    elif observed >= expires_at:
        state = "RETAINED_SOURCE_STATE_EXPIRED"
    else:
        state = "RETAINED_SOURCE_STATE_FRESH_NON_AUTHORITATIVE"
    return {
        "schema_version": "moralis_retained_source_state_v1",
        "state": state,
        "observed_at": _iso_utc(observed),
        "source_event_time": _iso_utc(event_time),
        "source_expires_at": _iso_utc(expires_at),
        "source_age_seconds": age_seconds,
        "source_feature_count": source_count,
        "diagnostic_feature_count": diagnostic_count,
        "source_payload_retained": bool(source_count or diagnostic_count),
        "source_carry_forward_observable": state == "RETAINED_SOURCE_STATE_FRESH_NON_AUTHORITATIVE",
        "admitted_carry_forward": False,
        "freshness_refreshed": False,
        "expiry_refreshed": False,
        "authority_refreshed": False,
        "available_at": None,
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


def _merge_endpoint_status(
    redis_client: Any,
    key: str,
    *,
    endpoint_id: str,
    row: Mapping[str, Any],
    provider: str,
    generated_utc: str,
) -> dict[str, Any]:
    existing = _read_mapping(redis_client, key)
    existing_endpoints = existing.get("endpoints")
    observed_at = _parse_utc(generated_utc) or datetime.now(UTC)
    endpoints: dict[str, Any] = {}
    if isinstance(existing_endpoints, Mapping):
        for prior_endpoint_id, prior_row in existing_endpoints.items():
            if not isinstance(prior_row, Mapping):
                continue
            expires_at = _parse_utc(prior_row.get("expires_at"))
            if expires_at is None or expires_at <= observed_at:
                continue
            if any(
                _strict_nonnegative_count(prior_row.get(field)) is None
                for field in (
                    "raw_transport_record_count",
                    "source_semantic_claim_count",
                    "admitted_feature_count",
                )
            ):
                continue
            endpoints[str(prior_endpoint_id)] = dict(prior_row)
    endpoints[endpoint_id] = dict(row)
    raw_count = sum(
        1
        for item in endpoints.values()
        if isinstance(item, Mapping) and item.get("raw_transport_actual_payload_present") is True
    )
    raw_record_count = sum(
        _strict_nonnegative_count(item.get("raw_transport_record_count")) or 0
        for item in endpoints.values()
        if isinstance(item, Mapping)
    )
    source_claim_count = sum(
        _strict_nonnegative_count(item.get("source_semantic_claim_count")) or 0
        for item in endpoints.values()
        if isinstance(item, Mapping)
    )
    return {
        "schema_version": "moralis_endpoint_status_v2",
        "provider": provider,
        "generated_utc": generated_utc,
        "available_at": None,
        "endpoints": endpoints,
        "actual_payload_endpoint_count": 0,
        "raw_transport_actual_endpoint_count": raw_count,
        "raw_transport_record_count": raw_record_count,
        "source_semantic_claim_count": source_claim_count,
        "admitted_feature_count": 0,
        "provider_ready": False,
        "publication_authority": False,
        "postcommit_receipt_bound": False,
        "heartbeat_only_green_allowed": False,
        "trainer_authority": False,
        "prediction_authority": False,
        "risk_authority": False,
        "orchestrator_authority": False,
        "allocator_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def _status_from_response(*, http_status: int | None, error_class: str | None) -> str:
    status = str(classify_status(http_status))
    error = str(error_class or "").upper()
    if "CADENCE" in error:
        return "CADENCE_DEFERRED"
    if any(
        marker in error
        for marker in (
            "API_KEY_MISSING",
            "IN_BODY_401",
            "IN_BODY_402",
            "IN_BODY_403",
            "UNAUTHORIZED",
            "UNSUBSCRIBED",
            "FORBIDDEN",
        )
    ):
        return "CONFIGURED_BUT_UNSUBSCRIBED_OR_FORBIDDEN"
    return status


def _source_observability_status(
    *,
    transport_status: str,
    transport_actual: bool,
    semantic_actual: bool,
) -> str:
    if transport_status != "READY":
        return transport_status
    if semantic_actual:
        return "SOURCE_OBSERVATION_NON_AUTHORITATIVE"
    if transport_actual:
        return "TRANSPORT_READY_NO_SEMANTIC_CLAIM"
    return "TRANSPORT_READY_NO_SOURCE_PAYLOAD"


def _read_mapping(redis_client: Any, key: str) -> dict[str, Any]:
    try:
        raw = redis_client.get(key)
        if raw is None:
            return {}
        if isinstance(raw, bytes):
            if len(raw) > _MAX_JSON_BYTES:
                return {}
            raw = raw.decode("utf-8", errors="strict")
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_JSON_BYTES:
            return {}
        parsed = json.loads(raw)
        _validate_closed_json(parsed)
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    except Exception:
        return {}


def _read_exact_mapping(
    redis_client: Any,
    key: str,
) -> tuple[str | None, dict[str, Any], str]:
    try:
        raw = redis_client.get(key)
    except Exception:
        return None, {}, "PRIOR_AGGREGATE_READ_FAILED"
    if raw is None:
        return None, {}, "OK"
    if isinstance(raw, bytes):
        if len(raw) > _MAX_JSON_BYTES:
            return None, {}, "PRIOR_AGGREGATE_BYTE_LIMIT_EXCEEDED"
        try:
            raw = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None, {}, "PRIOR_AGGREGATE_UTF8_INVALID"
    if not isinstance(raw, str):
        return None, {}, "PRIOR_AGGREGATE_TYPE_INVALID"
    if len(raw.encode("utf-8")) > _MAX_JSON_BYTES:
        return raw, {}, "PRIOR_AGGREGATE_BYTE_LIMIT_EXCEEDED"
    try:
        parsed = json.loads(raw)
        canonical = _json_bytes(parsed).decode("utf-8")
    except (TypeError, ValueError):
        return raw, {}, "PRIOR_AGGREGATE_JSON_INVALID"
    if not isinstance(parsed, Mapping):
        return raw, {}, "PRIOR_AGGREGATE_ENVELOPE_INVALID"
    if canonical != raw:
        return raw, {}, "PRIOR_AGGREGATE_NOT_CANONICAL"
    return raw, dict(parsed), "OK"


def _set_json_ack(redis_client: Any, key: str, encoded: bytes, *, ex: int) -> bool:
    try:
        return redis_client.set(key, encoded.decode("utf-8"), ex=max(1, int(ex))) is True
    except Exception:
        return False


def _set_content_addressed_json(
    redis_client: Any,
    key: str,
    encoded: bytes,
    *,
    ex: int,
) -> str:
    if hashlib.sha256(encoded).hexdigest() != key.rsplit(":", 1)[-1]:
        return "CONTENT_ADDRESS_KEY_DIGEST_MISMATCH"
    text = encoded.decode("utf-8")
    try:
        result = redis_client.set(key, text, ex=max(1, int(ex)), nx=True)
    except Exception:
        return "CONTENT_ADDRESS_WRITE_FAILED"
    if result is True:
        return "WRITTEN"
    try:
        existing = redis_client.get(key)
        if isinstance(existing, bytes):
            existing = existing.decode("utf-8", errors="strict")
    except Exception:
        return "CONTENT_ADDRESS_READBACK_FAILED"
    if existing == text:
        return "EXACT_DUPLICATE_NO_REFRESH"
    return "CONTENT_ADDRESS_CONFLICT_QUARANTINED"


def _set_immutable_json(
    redis_client: Any,
    key: str,
    encoded: bytes,
    *,
    ex: int,
) -> str:
    text = encoded.decode("utf-8")
    try:
        result = redis_client.set(key, text, ex=max(1, int(ex)), nx=True)
    except Exception:
        return "IMMUTABLE_WRITE_FAILED"
    if result is True:
        try:
            readback = redis_client.get(key)
            if isinstance(readback, bytes):
                readback = readback.decode("utf-8", errors="strict")
        except Exception:
            return "IMMUTABLE_READBACK_FAILED"
        return "WRITTEN" if readback == text else "IMMUTABLE_READBACK_MISMATCH"
    try:
        existing = redis_client.get(key)
        if isinstance(existing, bytes):
            existing = existing.decode("utf-8", errors="strict")
    except Exception:
        return "IMMUTABLE_READBACK_FAILED"
    if existing == text:
        return "EXACT_DUPLICATE_NO_REFRESH"
    return "IMMUTABLE_CONFLICT_QUARANTINED"


def _cas_set_json_ack(
    redis_client: Any,
    key: str,
    *,
    expected_raw: str | None,
    encoded: bytes,
    ex: int,
) -> str:
    try:
        result = redis_client.eval(
            _AGGREGATE_CAS_SCRIPT,
            1,
            key,
            "0" if expected_raw is None else "1",
            expected_raw or "",
            encoded.decode("utf-8"),
            str(max(1, int(ex))),
        )
    except Exception:
        return "CAS_EVAL_FAILED"
    if result == 1:
        return "APPLIED"
    if result == 0:
        return "CONFLICT_RETRY"
    return "CAS_ACK_INVALID"


def _json_bytes(payload: Any) -> bytes:
    _validate_closed_json(payload)
    encoded = json.dumps(
        payload,
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


def _source_binding_bytes(
    *,
    endpoint_id: str,
    source_identity: str,
    source_key: str,
    source_schema_version: str,
    source_payload_sha256: str,
) -> bytes:
    return _json_bytes(
        {
            "endpoint_id": endpoint_id,
            "provider": "moralis",
            "source_identity": source_identity,
            "source_key": source_key,
            "source_payload_sha256": source_payload_sha256,
            "source_schema_version": source_schema_version,
        }
    )


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _strict_nonnegative_count(value: Any) -> int | None:
    if type(value) is not int or value < 0:
        return None
    return int(value)


def _expires_at(generated_at: Any, ttl_seconds: int) -> str:
    generated = _parse_utc(generated_at) or datetime.now(UTC)
    return (
        (generated + timedelta(seconds=max(1, int(ttl_seconds))))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _earliest_utc(*values: Any) -> str:
    parsed = [clock for value in values if (clock := _parse_utc(value)) is not None]
    if not parsed:
        raise ValueError("no valid UTC expiry")
    return str(_iso_utc(min(parsed)))


def _remaining_ttl_seconds(expires_at: Any, *, observed_at: Any) -> int:
    expires = _parse_utc(expires_at)
    observed = _parse_utc(observed_at)
    if expires is None or observed is None:
        return 0
    return max(0, int((expires - observed).total_seconds()))


def _publication_key_rejection_reasons(
    *,
    spec: MoralisEndpointSpec,
    chain: str,
    symbol: str | None,
    wallet: str | None,
    token: str | None,
    timeframe: str,
) -> list[str]:
    reasons: list[str] = []
    if not _SAFE_KEY_SEGMENT_RE.fullmatch(spec.endpoint_id):
        reasons.append("ENDPOINT_ID")
    if not _SAFE_KEY_SEGMENT_RE.fullmatch(str(chain).strip().lower()):
        reasons.append("CHAIN")
    if symbol is not None and not _SYMBOL_KEY_SEGMENT_RE.fullmatch(str(symbol).strip().upper()):
        reasons.append("SYMBOL")
    if symbol is not None and not _TIMEFRAME_KEY_SEGMENT_RE.fullmatch(str(timeframe)):
        reasons.append("TIMEFRAME")
    for name, value in (("WALLET", wallet), ("TOKEN", token)):
        if value is None:
            continue
        if not _safe_identity_text(value):
            reasons.append(name)
    if spec.endpoint_id == "token_metadata":
        if not isinstance(token, str) or not _EVM_ADDRESS_RE.fullmatch(token.strip().lower()):
            reasons.append("TOKEN_METADATA_TOKEN")
    return sorted(set(reasons))


def _safe_identity_text(value: Any) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    if len(encoded) > 256:
        return False
    if unicodedata.normalize("NFC", value) != value:
        return False
    return all(not unicodedata.category(char).startswith("C") for char in value)


def _chain(value: object) -> str:
    raw = str(value or "").strip().lower()
    return str(MORALIS_EVM_CHAIN_ALIASES.get(raw, raw))


def _redis_key_valid(value: str) -> bool:
    if len(value.encode("ascii", errors="ignore")) != len(value) or len(value) > 512:
        return False
    segments = value.split(":")
    return bool(segments and all(_SAFE_KEY_SEGMENT_RE.fullmatch(segment) for segment in segments))


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


def _latest_strict_utc(values: list[str], *, microseconds: bool = False) -> str | None:
    valid = [value for value in (_parse_utc(item) for item in values) if value is not None]
    if not valid:
        return None
    return (
        max(valid)
        .isoformat(timespec="microseconds" if microseconds else "seconds")
        .replace("+00:00", "Z")
    )


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


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
