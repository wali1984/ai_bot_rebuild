"""Audit-only profile attestation for authenticated source declarations v4.

The generic source-evidence authenticator proves only that one retained key
authenticated one exact adapter-output declaration.  This module additionally
checks that the authenticated declaration matches one of two narrowly defined
profiles: canonical Binance closed-OHLCV or a Moralis cadence/rate-limit typed
negative.  Those checks authenticate and classify declarations only.

This module does not resolve or reopen the referenced CAS object, recompute its
byte count or digest, parse its payload schema, establish an adapter registry,
recompute candle finality, or derive a Moralis deferral from scheduler and
compute-unit records.  It therefore never reports source or payload semantics
as verified.  The result is detached, flat, read-only audit data and grants no
trainer, prediction, paper, live, or runtime authority.

This module is not wired into runtime.  It does not read Redis, create an
atomic Moralis control snapshot, append a ledger, bind a feature dependency,
publish a feature snapshot, or admit a trainer row.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import NoReturn, cast

from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION,
)
from v2.backend.app.services.native_trainer.source_evidence_authenticator_v4 import (
    POSITIVE_SOURCE_READ_EVIDENCE_KIND,
    SourceEvidenceAdapterAttestationV4,
    SourceEvidenceVerifierV4,
    parse_source_evidence_adapter_attestation_v4,
)

SOURCE_EVIDENCE_PROFILE_ATTESTATION_V4_SCHEMA_VERSION = (
    "trainer_source_evidence_profile_attestation_v4"
)
SOURCE_EVIDENCE_TYPED_NEGATIVE_KIND = "TYPED_NEGATIVE_SOURCE_READ"
_NEGATIVE_CADENCE_OR_RATE_LIMIT_DEFERRED = "CADENCE_OR_RATE_LIMIT_DEFERRED"

CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4 = "canonical_binance_closed_ohlcv_profile_v4"
MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PROFILE_V4 = "moralis_cadence_rate_limit_negative_profile_v4"

CANONICAL_BINANCE_CLOSED_OHLCV_ADAPTER_ID_V4 = "canonical-ohlcv-closed-adapter-v4"
CANONICAL_BINANCE_CLOSED_OHLCV_SOURCE_EVIDENCE_SCHEMA_V4 = (
    "canonical_binance_closed_ohlcv_source_evidence_v4"
)
CANONICAL_BINANCE_CLOSED_OHLCV_EVIDENCE_CLASS_V4 = "EXACT_ATOMIC_CANONICAL_BINANCE_CLOSED_OHLCV"
CANONICAL_BINANCE_CLOSED_OHLCV_PRODUCER_CLAIM_V4 = "binance-public-market-data"
CANONICAL_BINANCE_CLOSED_OHLCV_BRANCH_ID_V4 = "canonical-ohlcv-atomic-adapter-v4"

MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_ADAPTER_ID_V4 = "moralis-cadence-budget-negative-adapter-v4"
MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_EVIDENCE_CLASS_V4 = (
    "EXACT_ATOMIC_MORALIS_CADENCE_OR_RATE_LIMIT_TYPED_NEGATIVE"
)
MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_SCHEMA_V4 = "moralis_cadence_budget_atomic_snapshot_v1"
MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_EVIDENCE_SCHEMA_V4 = (
    "moralis_typed_negative_source_evidence_v4"
)
MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PRODUCER_CLAIM_V4 = (
    "moralis-provider-loop-durable-control-plane"
)
MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_BRANCH_ID_V4 = "moralis-cadence-budget-negative-adapter-v4"
MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_KEY_V4 = (
    "v2:provider:moralis:scheduler_status+v2:provider:moralis:cu_budget_status"
)

_OHLCV_FINALITY_KIND = "CLOSED_INTERVAL"
_MORALIS_NEGATIVE_FINALITY_KIND = "TYPED_NEGATIVE_CONTROL_STATE"
_CAS_NAMESPACE = "trainer-source-payload-cas-v1"
_AUDIT_ENVIRONMENT = "paper-audit"
_TRAINER_NAMESPACE = "v2-native-trainer"
_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_FIXED_FALSE_AUTHORIZATION_FIELDS = (
    "upstream_producer_authenticated",
    "dependency_manifest_bound",
    "per_field_receipt_bound",
    "source_scope_complete",
    "feature_snapshot_published",
    "consumer_eligible",
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "runtime_wired",
)

_FIXED_FALSE_SEMANTIC_PROOF_FIELDS = (
    "source_specific_semantics_verified",
    "positive_source_read_semantics_verified",
    "typed_negative_semantics_verified",
    "payload_semantics_recomputed",
    "adapter_code_registry_pinned",
    "adapter_config_registry_pinned",
    "source_locator_semantics_verified",
    "cas_payload_reopened",
    "cas_payload_hash_recomputed",
    "payload_schema_replayed",
    "source_finality_recomputed",
    "moralis_cadence_state_recomputed",
)


class SourceEvidenceProfileAttestationV4Error(RuntimeError):
    """Authenticated material failed one exact declaration profile."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise SourceEvidenceProfileAttestationV4Error(*reasons) from None


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("source_evidence_profile_attestation_v4_canonicalization_failed")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _parse_clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str:
        _fail(reason)
    text = value
    try:
        parsed = datetime.strptime(text, _CLOCK_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        _fail(reason)
    if parsed < _EPOCH or parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != text:
        _fail(reason)
    return parsed


def _require_exact(value: object, expected: object, *, reason: str) -> None:
    if type(value) is not type(expected) or value != expected:
        _fail(reason)


def _require_positive_payload(material: Mapping[str, object]) -> None:
    byte_count = material["exact_payload_byte_count"]
    if type(byte_count) is not int or byte_count <= 0:
        _fail("source_evidence_profile_attestation_v4_empty_payload_forbidden")
    digest = material["exact_payload_sha256"]
    if type(digest) is not str:
        _fail("source_evidence_profile_attestation_v4_payload_digest_invalid")
    expected_address = f"sha256/{digest[:2]}/{digest}"
    _require_exact(
        material["cas_namespace"],
        _CAS_NAMESPACE,
        reason="source_evidence_profile_attestation_v4_cas_namespace_invalid",
    )
    _require_exact(
        material["cas_address"],
        expected_address,
        reason="source_evidence_profile_attestation_v4_cas_address_binding_invalid",
    )


def _strict_complete_clocks(material: Mapping[str, object]) -> dict[str, datetime]:
    names = (
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "source_available_at",
        "source_read_completed_at",
        "decision_time",
    )
    parsed = {
        name: _parse_clock(
            material[name],
            reason=f"source_evidence_profile_attestation_v4_{name}_invalid",
        )
        for name in names
    }
    ordered = [parsed[name] for name in names]
    if any(earlier > later for earlier, later in zip(ordered, ordered[1:], strict=False)):
        _fail("source_evidence_profile_attestation_v4_causal_clock_order_invalid")
    return parsed


def _validate_common_adapter_evidence(material: Mapping[str, object]) -> dict[str, datetime]:
    _require_exact(
        material["environment"],
        _AUDIT_ENVIRONMENT,
        reason="source_evidence_profile_attestation_v4_environment_invalid",
    )
    _require_exact(
        material["namespace"],
        _TRAINER_NAMESPACE,
        reason="source_evidence_profile_attestation_v4_namespace_invalid",
    )
    _require_exact(
        material["exact_atomic_read_verified"],
        True,
        reason="source_evidence_profile_attestation_v4_exact_atomic_read_declaration_required",
    )
    _require_exact(
        material["source_schema_adapter_verified"],
        True,
        reason="source_evidence_profile_attestation_v4_source_adapter_declaration_required",
    )
    _require_exact(
        material["adapter_attestation_verified"],
        True,
        reason="source_evidence_profile_attestation_v4_adapter_declaration_required",
    )
    _require_exact(
        material["audit_only"],
        True,
        reason="source_evidence_profile_attestation_v4_audit_only_required",
    )
    _require_positive_payload(material)
    return _strict_complete_clocks(material)


def _validate_canonical_ohlcv(material: Mapping[str, object]) -> None:
    _require_exact(
        material["source_evidence_schema_version"],
        CANONICAL_BINANCE_CLOSED_OHLCV_SOURCE_EVIDENCE_SCHEMA_V4,
        reason="source_evidence_profile_attestation_v4_ohlcv_evidence_schema_invalid",
    )
    _require_exact(
        material["evidence_kind"],
        POSITIVE_SOURCE_READ_EVIDENCE_KIND,
        reason="source_evidence_profile_attestation_v4_ohlcv_kind_invalid",
    )
    _require_exact(
        material["evidence_class"],
        CANONICAL_BINANCE_CLOSED_OHLCV_EVIDENCE_CLASS_V4,
        reason="source_evidence_profile_attestation_v4_ohlcv_class_invalid",
    )
    _require_exact(
        material["adapter_id"],
        CANONICAL_BINANCE_CLOSED_OHLCV_ADAPTER_ID_V4,
        reason="source_evidence_profile_attestation_v4_ohlcv_adapter_invalid",
    )
    _require_exact(
        material["source_schema_version"],
        CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION,
        reason="source_evidence_profile_attestation_v4_ohlcv_schema_invalid",
    )
    _require_exact(
        material["upstream_producer_identity_claim"],
        CANONICAL_BINANCE_CLOSED_OHLCV_PRODUCER_CLAIM_V4,
        reason="source_evidence_profile_attestation_v4_ohlcv_producer_claim_invalid",
    )
    _require_exact(
        material["branch_identity"],
        CANONICAL_BINANCE_CLOSED_OHLCV_BRANCH_ID_V4,
        reason="source_evidence_profile_attestation_v4_ohlcv_branch_invalid",
    )
    _require_exact(
        material["negative_type_identity"],
        None,
        reason="source_evidence_profile_attestation_v4_ohlcv_negative_forbidden",
    )
    _require_exact(
        material["finality_kind"],
        _OHLCV_FINALITY_KIND,
        reason="source_evidence_profile_attestation_v4_ohlcv_finality_kind_invalid",
    )
    _require_exact(
        material["finality_result"],
        True,
        reason="source_evidence_profile_attestation_v4_ohlcv_finality_result_invalid",
    )
    _require_exact(
        material["source_finality_verified"],
        True,
        reason="source_evidence_profile_attestation_v4_ohlcv_finality_declaration_required",
    )
    expected_key = f"v2:market:ohlcv_closed:binance:{material['symbol']}:{material['timeframe']}"
    _require_exact(
        material["source_key"],
        expected_key,
        reason="source_evidence_profile_attestation_v4_ohlcv_source_key_invalid",
    )
    clocks = _validate_common_adapter_evidence(material)
    if clocks["economic_event_time"] >= clocks["source_available_at"]:
        _fail("source_evidence_profile_attestation_v4_ohlcv_not_available_after_close")
    if clocks["economic_event_time"] >= clocks["decision_time"]:
        _fail("source_evidence_profile_attestation_v4_ohlcv_not_closed_before_decision")


def _validate_moralis_cadence_negative(material: Mapping[str, object]) -> None:
    _require_exact(
        material["source_evidence_schema_version"],
        MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_EVIDENCE_SCHEMA_V4,
        reason="source_evidence_profile_attestation_v4_moralis_negative_evidence_schema_invalid",
    )
    _require_exact(
        material["evidence_kind"],
        SOURCE_EVIDENCE_TYPED_NEGATIVE_KIND,
        reason="source_evidence_profile_attestation_v4_moralis_negative_kind_invalid",
    )
    _require_exact(
        material["evidence_class"],
        MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_EVIDENCE_CLASS_V4,
        reason="source_evidence_profile_attestation_v4_moralis_negative_class_invalid",
    )
    _require_exact(
        material["adapter_id"],
        MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_ADAPTER_ID_V4,
        reason="source_evidence_profile_attestation_v4_moralis_negative_adapter_invalid",
    )
    _require_exact(
        material["source_schema_version"],
        MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_SCHEMA_V4,
        reason="source_evidence_profile_attestation_v4_moralis_negative_schema_invalid",
    )
    _require_exact(
        material["upstream_producer_identity_claim"],
        MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PRODUCER_CLAIM_V4,
        reason="source_evidence_profile_attestation_v4_moralis_negative_producer_claim_invalid",
    )
    _require_exact(
        material["branch_identity"],
        MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_BRANCH_ID_V4,
        reason="source_evidence_profile_attestation_v4_moralis_negative_branch_invalid",
    )
    _require_exact(
        material["source_key"],
        MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_KEY_V4,
        reason="source_evidence_profile_attestation_v4_moralis_negative_source_key_invalid",
    )
    _require_exact(
        material["negative_type_identity"],
        _NEGATIVE_CADENCE_OR_RATE_LIMIT_DEFERRED,
        reason="source_evidence_profile_attestation_v4_moralis_negative_type_invalid",
    )
    _require_exact(
        material["finality_kind"],
        _MORALIS_NEGATIVE_FINALITY_KIND,
        reason="source_evidence_profile_attestation_v4_moralis_negative_finality_kind_invalid",
    )
    _require_exact(
        material["finality_result"],
        False,
        reason="source_evidence_profile_attestation_v4_moralis_negative_finality_result_invalid",
    )
    _require_exact(
        material["source_finality_verified"],
        False,
        reason="source_evidence_profile_attestation_v4_moralis_negative_finality_claim_forbidden",
    )
    _validate_common_adapter_evidence(material)


def _artifact_json(
    artifact: SourceEvidenceAdapterAttestationV4 | str | bytes,
) -> str:
    if type(artifact) is SourceEvidenceAdapterAttestationV4:
        return artifact.attestation_json
    if type(artifact) is str:
        return parse_source_evidence_adapter_attestation_v4(artifact).attestation_json
    if type(artifact) is bytes:
        return parse_source_evidence_adapter_attestation_v4(artifact).attestation_json
    _fail("source_evidence_profile_attestation_v4_artifact_invalid")


def verify_source_evidence_profile_attestation_v4(
    *,
    verifier: SourceEvidenceVerifierV4,
    artifact: SourceEvidenceAdapterAttestationV4 | str | bytes,
    expected_auth_key_id: str,
    expected_material: dict[str, object],
    expected_profile_id: str,
) -> Mapping[str, object]:
    """Freshly authenticate and classify one exact adapter declaration.

    The caller owns the expected key ID, complete material, and declaration
    profile.  Artifact-selected expectations are never accepted.  Profile
    classification does not prove the referenced payload or source semantics.
    A downstream consumer must separately use a trusted adapter registry,
    independently resolve and verify the CAS payload, replay source-specific
    semantics, and bind its complete dependency manifest and per-field proofs.
    """

    if type(verifier) is not SourceEvidenceVerifierV4:
        _fail("source_evidence_profile_attestation_v4_verifier_invalid")
    if type(expected_profile_id) is not str:
        _fail("source_evidence_profile_attestation_v4_profile_invalid")
    verified = verifier.verify(
        artifact,
        expected_auth_key_id=expected_auth_key_id,
        expected_material=expected_material,
    )
    if expected_profile_id == CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4:
        _validate_canonical_ohlcv(verified)
        positive_declared = True
        negative_declared = False
    elif expected_profile_id == MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PROFILE_V4:
        _validate_moralis_cadence_negative(verified)
        positive_declared = False
        negative_declared = True
    else:
        _fail("source_evidence_profile_attestation_v4_profile_invalid")

    exact_artifact_json = _artifact_json(artifact)
    result: dict[str, object] = {
        "schema_version": SOURCE_EVIDENCE_PROFILE_ATTESTATION_V4_SCHEMA_VERSION,
        "profile_id": expected_profile_id,
        "auth_key_id": expected_auth_key_id,
        "adapter_attestation_sha256": hashlib.sha256(
            exact_artifact_json.encode("ascii", errors="strict")
        ).hexdigest(),
        "attestation_material_sha256": _sha256_json(dict(verified)),
        "evidence_kind": verified["evidence_kind"],
        "negative_type_identity": verified["negative_type_identity"],
        "source_key": verified["source_key"],
        "symbol": verified["symbol"],
        "timeframe": verified["timeframe"],
        "exact_payload_sha256": verified["exact_payload_sha256"],
        "exact_payload_byte_count": verified["exact_payload_byte_count"],
        "cas_namespace": verified["cas_namespace"],
        "cas_address": verified["cas_address"],
        "source_available_at": verified["source_available_at"],
        "source_read_completed_at": verified["source_read_completed_at"],
        "decision_time": verified["decision_time"],
        "adapter_attestation_authenticated": True,
        "authenticated_adapter_declaration_verified": True,
        "source_profile_declaration_verified": True,
        "positive_source_profile_declared": positive_declared,
        "typed_negative_profile_declared": negative_declared,
        **{field_name: False for field_name in _FIXED_FALSE_SEMANTIC_PROOF_FIELDS},
        **{field_name: False for field_name in _FIXED_FALSE_AUTHORIZATION_FIELDS},
        "audit_only": True,
    }
    # Detach once more so no mapping supplied by the verifier is retained.
    return MappingProxyType(cast(dict[str, object], json.loads(_canonical_json_bytes(result))))


__all__ = [
    "CANONICAL_BINANCE_CLOSED_OHLCV_ADAPTER_ID_V4",
    "CANONICAL_BINANCE_CLOSED_OHLCV_BRANCH_ID_V4",
    "CANONICAL_BINANCE_CLOSED_OHLCV_EVIDENCE_CLASS_V4",
    "CANONICAL_BINANCE_CLOSED_OHLCV_PRODUCER_CLAIM_V4",
    "CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4",
    "CANONICAL_BINANCE_CLOSED_OHLCV_SOURCE_EVIDENCE_SCHEMA_V4",
    "MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_ADAPTER_ID_V4",
    "MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_BRANCH_ID_V4",
    "MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_EVIDENCE_CLASS_V4",
    "MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PRODUCER_CLAIM_V4",
    "MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PROFILE_V4",
    "MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_KEY_V4",
    "MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_EVIDENCE_SCHEMA_V4",
    "MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_SCHEMA_V4",
    "SOURCE_EVIDENCE_PROFILE_ATTESTATION_V4_SCHEMA_VERSION",
    "SOURCE_EVIDENCE_TYPED_NEGATIVE_KIND",
    "SourceEvidenceProfileAttestationV4Error",
    "verify_source_evidence_profile_attestation_v4",
]
