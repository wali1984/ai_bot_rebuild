from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import FrozenInstanceError, dataclass, replace
from pathlib import Path
from typing import Any, cast

import pytest

from v2.backend.app.services.native_trainer import (
    authenticated_feature_resolution_capture_v4 as capture_module,
)
from v2.backend.app.services.native_trainer.authenticated_feature_resolution_capture_v4 import (
    AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_DOWNSTREAM_STATUS,
    AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_EVIDENCE_CLASSIFICATION,
    AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SCHEMA_VERSION,
    OPTIONAL_TYPED_NEGATIVE_RECEIPT_KIND_V4,
    POSITIVE_SOURCE_READ_RECEIPT_KIND_V4,
    SOURCE_EVIDENCE_CAS_NAMESPACE_V4,
    AuthenticatedFeatureResolutionCaptureCandidateV4,
    AuthenticatedFeatureResolutionCaptureV4ValidationError,
    FeatureResolutionEvidenceReferenceV4,
    build_authenticated_feature_resolution_capture_candidate_v4,
    build_feature_resolution_evidence_reference_v4,
    parse_authenticated_feature_resolution_capture_candidate_v4,
    validate_authenticated_feature_resolution_capture_candidate_v4,
)
from v2.backend.app.services.native_trainer.feature_resolution_observation_v4 import (
    NEGATIVE_CADENCE_OR_RATE_LIMIT_DEFERRED,
    RESOLUTION_STATUS_RESOLVED,
    RESOLUTION_STATUS_TYPED_NEGATIVE,
)
from v2.backend.app.services.native_trainer.feature_resolution_trace_v4 import (
    FeatureResolutionTraceArtifactV4,
    build_feature_resolution_trace_v4,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT,
    FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_feature_resolution_trace_v4 as trace_harness,
)

_SHA_RECEIPT = "5" * 64
_SHA_ATTESTATION = "6" * 64
_SHA_MATERIAL = "7" * 64
_SHA_PUBLIC_KEY = "8" * 64


@dataclass(frozen=True, slots=True)
class _Harness:
    trace: FeatureResolutionTraceArtifactV4
    references: tuple[FeatureResolutionEvidenceReferenceV4, ...]
    artifact: AuthenticatedFeatureResolutionCaptureCandidateV4


def _fixture_sha256(*parts: object) -> str:
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def _trace(
    *, negative_index: int | None = None, stale: bool = False
) -> FeatureResolutionTraceArtifactV4:
    tensor = trace_harness._tensor(negative_index=negative_index, stale=stale)
    return build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=trace_harness._SHA_D,
        observations=trace_harness._observations(tensor),
    )


def _references(
    trace: FeatureResolutionTraceArtifactV4,
) -> tuple[FeatureResolutionEvidenceReferenceV4, ...]:
    references: list[FeatureResolutionEvidenceReferenceV4] = []
    for ordinal, observation in enumerate(trace.trace["slot_observations"]):
        resolved = observation["resolution_status"] == RESOLUTION_STATUS_RESOLVED
        payload_sha256 = cast(
            str,
            (
                observation["source_root_sha256"]
                if resolved
                else observation["negative_evidence_sha256"]
            ),
        )
        payload_byte_count = int(payload_sha256[:8], 16) % 65_535 + 1
        receipt_kind = (
            POSITIVE_SOURCE_READ_RECEIPT_KIND_V4
            if resolved
            else OPTIONAL_TYPED_NEGATIVE_RECEIPT_KIND_V4
        )
        receipt_schema = "source-evidence-receipt-v4"
        cas_address = f"sha256/{payload_sha256[:2]}/{payload_sha256}"
        receipt_sha256 = _fixture_sha256(
            receipt_schema,
            receipt_kind,
            observation["resolution_status"],
            observation["negative_reason"],
            SOURCE_EVIDENCE_CAS_NAMESPACE_V4,
            cas_address,
            payload_sha256,
            payload_byte_count,
            observation["event_time"],
            observation["ingested_at"],
            observation["available_at"],
            observation["feature_cutoff"],
            observation["decision_time"],
            observation["consumer_observed_at"],
        )
        attestation_schema = "source-evidence-attestation-v4"
        attestation_sha256 = _fixture_sha256(
            attestation_schema,
            receipt_sha256,
            "paper-audit-source-key-v1",
            _SHA_PUBLIC_KEY,
        )
        references.append(
            build_feature_resolution_evidence_reference_v4(
                ordinal=ordinal,
                feature_name=observation["feature_name"],
                raw_cas_namespace=SOURCE_EVIDENCE_CAS_NAMESPACE_V4,
                raw_cas_address=cas_address,
                raw_payload_sha256=payload_sha256,
                raw_payload_byte_count=payload_byte_count,
                source_evidence_receipt_kind=receipt_kind,
                source_evidence_receipt_schema_version=receipt_schema,
                source_evidence_receipt_sha256=receipt_sha256,
                source_attestation_schema_version=attestation_schema,
                source_attestation_sha256=attestation_sha256,
                attested_material_sha256=receipt_sha256,
                declared_trust_anchor_id="paper-audit-source-key-v1",
                declared_public_key_sha256=_SHA_PUBLIC_KEY,
            )
        )
    return tuple(references)


def _harness(*, negative_index: int | None = None, stale: bool = False) -> _Harness:
    trace = _trace(negative_index=negative_index, stale=stale)
    references = _references(trace)
    artifact = build_authenticated_feature_resolution_capture_candidate_v4(
        registry=FEATURE_SOURCE_REGISTRY_V4,
        resolution_trace=trace,
        evidence_references=references,
    )
    return _Harness(trace=trace, references=references, artifact=artifact)


@pytest.fixture(scope="module")
def positive_harness() -> _Harness:
    return _harness()


@pytest.fixture(scope="module")
def optional_negative_harness() -> _Harness:
    # Slot 259 is the first Moralis OPTIONAL_EVENT_DEPENDENT slot.  A stale
    # declaration supplies every source clock required by the capture layer.
    return _harness(negative_index=259, stale=True)


def _rehash_candidate(candidate: dict[str, Any], *, changed_slot: int | None = None) -> None:
    if changed_slot is not None:
        slot = candidate["slot_captures"][changed_slot]
        material = {key: item for key, item in slot.items() if key != "slot_capture_sha256"}
        slot["slot_capture_sha256"] = capture_module._sha256(material)
    candidate["ordered_slot_capture_chain_sha256"] = capture_module._chain_sha256(
        trace_sha256=candidate["feature_resolution_trace_sha256"],
        slot_sha256s=[slot["slot_capture_sha256"] for slot in candidate["slot_captures"]],
    )
    material = {key: item for key, item in candidate.items() if key != "capture_sha256"}
    candidate["capture_sha256"] = capture_module._sha256(material)


def _assert_reason(
    exc_info: pytest.ExceptionInfo[AuthenticatedFeatureResolutionCaptureV4ValidationError],
    reason: str,
) -> None:
    assert reason in exc_info.value.reasons


def test_complete_446_slot_candidate_binds_registry_trace_and_every_identity(
    positive_harness: _Harness,
) -> None:
    artifact = positive_harness.artifact
    capture = artifact.capture

    assert artifact.schema_version == AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SCHEMA_VERSION
    assert isinstance(artifact, AuthenticatedFeatureResolutionCaptureCandidateV4)
    assert capture["feature_source_registry_sha256"] == FEATURE_SOURCE_REGISTRY_V4_SHA256
    assert capture["feature_resolution_trace_sha256"] == positive_harness.trace.trace_sha256
    assert capture["feature_abi_sha256"] == FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256
    assert capture["feature_slot_count"] == FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT == 446
    assert capture["required_slot_count"] == FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT == 383
    assert capture["optional_slot_count"] == FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT == 63
    assert len(capture["slot_captures"]) == 446
    assert capture["resolved_slot_count"] == 446
    assert capture["declared_optional_typed_negative_slot_count"] == 0
    assert capture["complete_slot_capture_set"] is True
    assert capture["declared_point_in_time_order_valid"] is True
    assert capture["required_value_contract_valid"] is True

    for ordinal, slot in enumerate(capture["slot_captures"]):
        registry_slot = FEATURE_SOURCE_REGISTRY_V4.slots[ordinal]
        observation = positive_harness.trace.trace["slot_observations"][ordinal]
        assert slot["ordinal"] == ordinal
        assert slot["feature_name"] == registry_slot.feature_name
        assert slot["configured_source_label"] == registry_slot.configured_source_label
        assert slot["requirement_class"] == registry_slot.requirement_class
        assert (
            slot["resolver_branch"]["resolved_source_label"] == observation["resolved_source_label"]
        )
        assert slot["resolver_branch"]["selected_alias"] == observation["selected_alias"]
        assert slot["transform"]["transform_code_sha256"] == observation["transform_code_sha256"]
        assert slot["clocks"]["event_time"] == observation["event_time"]
        assert slot["clocks"]["ingested_at"] == observation["ingested_at"]
        assert slot["clocks"]["available_at"] == observation["available_at"]
        assert slot["clocks"]["feature_cutoff"] == observation["feature_cutoff"]
        assert slot["clocks"]["decision_time"] == observation["decision_time"]
        assert slot["source_evidence"]["raw_payload_sha256"] == observation["source_root_sha256"]
        assert (
            slot["source_evidence"]["source_evidence_receipt_sha256"]
            == positive_harness.references[ordinal].source_evidence_receipt_sha256
        )
        assert (
            slot["source_evidence"]["source_attestation_sha256"]
            == positive_harness.references[ordinal].source_attestation_sha256
        )


def test_candidate_is_explicitly_unauthenticated_unwired_and_non_authorizing(
    positive_harness: _Harness,
) -> None:
    artifact = positive_harness.artifact
    capture = artifact.capture

    assert (
        capture["evidence_classification"]
        == AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_EVIDENCE_CLASSIFICATION
    )
    assert capture["downstream_status"] == (
        AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_DOWNSTREAM_STATUS
    )
    assert "UNAUTHENTICATED" in capture["evidence_classification"]
    assert "NON_CONSUMABLE" in capture["downstream_status"]
    assert capture["capture_candidate_only"] is True
    assert capture["audit_only"] is True
    for field_name in capture_module._FIXED_FALSE_FIELDS:
        assert capture[field_name] is False
        assert getattr(artifact, field_name) is False
    for slot in capture["slot_captures"]:
        assert slot["optional_typed_negative_authentication_verified"] is False
        evidence = slot["source_evidence"]
        assert evidence["source_receipt_authentication_verified"] is False
        assert evidence["source_attestation_authentication_verified"] is False
        assert evidence["raw_cas_payload_verified"] is False
        assert evidence["source_semantics_verified"] is False


def test_optional_typed_negative_is_null_never_numeric_zero_and_not_authenticated(
    optional_negative_harness: _Harness,
) -> None:
    capture = optional_negative_harness.artifact.capture
    slot = capture["slot_captures"][259]
    observation = optional_negative_harness.trace.trace["slot_observations"][259]

    assert slot["requirement_class"] == "OPTIONAL_EVENT_DEPENDENT"
    assert slot["resolution_status"] == RESOLUTION_STATUS_TYPED_NEGATIVE
    assert slot["negative_reason"] == observation["negative_reason"] == "SOURCE_STALE"
    assert slot["transform"]["resolved_value_float32_be_hex"] is None
    assert slot["source_evidence"]["raw_payload_sha256"] == observation["negative_evidence_sha256"]
    assert slot["source_evidence"]["source_evidence_receipt_kind"] == (
        OPTIONAL_TYPED_NEGATIVE_RECEIPT_KIND_V4
    )
    assert slot["optional_typed_negative_authentication_verified"] is False
    assert capture["resolved_slot_count"] == 445
    assert capture["declared_optional_typed_negative_slot_count"] == 1
    assert capture["authenticated_optional_typed_negative_complete"] is False
    serialized_slot = json.dumps(slot, allow_nan=False, sort_keys=True)
    assert '"resolved_value_float32_be_hex": null' in serialized_slot


def test_coinapi_optional_missing_requires_typed_negative_receipt_and_null_value() -> None:
    harness = _harness(negative_index=133, stale=True)
    capture = harness.artifact.capture
    slot = capture["slot_captures"][133]

    assert slot["feature_name"] == "coinapi_wsds_tape_imbalance"
    assert slot["requirement_class"] == "OPTIONAL_EVENT_DEPENDENT"
    assert slot["resolution_status"] == RESOLUTION_STATUS_TYPED_NEGATIVE
    assert slot["transform"]["resolved_value_float32_be_hex"] is None
    assert slot["source_evidence"]["source_evidence_receipt_kind"] == (
        OPTIONAL_TYPED_NEGATIVE_RECEIPT_KIND_V4
    )
    assert capture["declared_optional_typed_negative_slot_count"] == 1

    hostile_references = list(harness.references)
    hostile_references[133] = replace(
        hostile_references[133],
        source_evidence_receipt_kind=POSITIVE_SOURCE_READ_RECEIPT_KIND_V4,
    )
    with pytest.raises(
        AuthenticatedFeatureResolutionCaptureV4ValidationError,
        match="RECEIPT_KIND_STATUS_MISMATCH",
    ):
        build_authenticated_feature_resolution_capture_candidate_v4(
            registry=FEATURE_SOURCE_REGISTRY_V4,
            resolution_trace=harness.trace,
            evidence_references=tuple(hostile_references),
        )


def test_required_slot_may_never_use_typed_negative() -> None:
    trace = _trace(negative_index=0, stale=True)
    with pytest.raises(
        AuthenticatedFeatureResolutionCaptureV4ValidationError,
        match="REQUIRED_TYPED_NEGATIVE_FORBIDDEN",
    ):
        build_authenticated_feature_resolution_capture_candidate_v4(
            registry=FEATURE_SOURCE_REGISTRY_V4,
            resolution_trace=trace,
            evidence_references=_references(trace),
        )


def test_optional_negative_without_complete_source_clocks_fails_closed() -> None:
    trace = _trace(negative_index=259, stale=False)
    with pytest.raises(
        AuthenticatedFeatureResolutionCaptureV4ValidationError,
        match="EVENT_TIME_INVALID",
    ):
        build_authenticated_feature_resolution_capture_candidate_v4(
            registry=FEATURE_SOURCE_REGISTRY_V4,
            resolution_trace=trace,
            evidence_references=_references(trace),
        )


def test_capture_accepts_source_availability_after_feature_cutoff() -> None:
    tensor = trace_harness._tensor()
    observations = tuple(
        replace(
            observation,
            feature_cutoff="2026-07-20T00:00:00.000000Z",
            masa_feature_cutoff="2026-07-20T00:00:00.000000Z",
        )
        for observation in trace_harness._observations(tensor)
    )
    trace = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=trace_harness._SHA_D,
        observations=observations,
    )
    artifact = build_authenticated_feature_resolution_capture_candidate_v4(
        registry=FEATURE_SOURCE_REGISTRY_V4,
        resolution_trace=trace,
        evidence_references=_references(trace),
    )

    first_clocks = artifact.capture["slot_captures"][0]["clocks"]
    assert first_clocks["feature_cutoff"] < first_clocks["available_at"]
    assert artifact.capture["declared_point_in_time_order_valid"] is True


def test_capture_defense_rejects_generation_before_ingestion(
    positive_harness: _Harness,
) -> None:
    observation = dict(positive_harness.trace.trace["slot_observations"][0])
    observation["generated_at"] = "2026-07-20T00:00:00.050000Z"
    with pytest.raises(
        AuthenticatedFeatureResolutionCaptureV4ValidationError,
        match="CLOCK_ORDER_INVALID",
    ):
        capture_module._slot_mapping(
            ordinal=0,
            observation=observation,
            reference=positive_harness.references[0],
        )


@pytest.mark.parametrize(
    ("change", "reason"),
    (
        ("ordinal", "EVIDENCE_ORDER_MISMATCH"),
        ("feature_name", "EVIDENCE_ORDER_MISMATCH"),
        ("receipt_kind", "RECEIPT_KIND_STATUS_MISMATCH"),
        ("payload_sha256", "RAW_PAYLOAD_TRACE_MISMATCH"),
    ),
)
def test_evidence_reference_must_bind_exact_slot_status_and_trace_root(
    positive_harness: _Harness,
    change: str,
    reason: str,
) -> None:
    references = list(positive_harness.references)
    reference = references[0]
    if change == "ordinal":
        references[0] = replace(reference, ordinal=1)
    elif change == "feature_name":
        references[0] = replace(reference, feature_name="forged_feature")
    elif change == "receipt_kind":
        references[0] = replace(
            reference,
            source_evidence_receipt_kind=OPTIONAL_TYPED_NEGATIVE_RECEIPT_KIND_V4,
        )
    else:
        digest = "9" * 64
        references[0] = replace(
            reference,
            raw_payload_sha256=digest,
            raw_cas_address=f"sha256/{digest[:2]}/{digest}",
        )
    with pytest.raises(AuthenticatedFeatureResolutionCaptureV4ValidationError) as exc_info:
        build_authenticated_feature_resolution_capture_candidate_v4(
            registry=FEATURE_SOURCE_REGISTRY_V4,
            resolution_trace=positive_harness.trace,
            evidence_references=references,
        )
    _assert_reason(exc_info, f"AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_{reason}")


@pytest.mark.parametrize("references", ((), [], [object()] * 446))
def test_incomplete_or_wrong_type_evidence_set_fails_closed(
    positive_harness: _Harness, references: object
) -> None:
    with pytest.raises(AuthenticatedFeatureResolutionCaptureV4ValidationError):
        build_authenticated_feature_resolution_capture_candidate_v4(
            registry=FEATURE_SOURCE_REGISTRY_V4,
            resolution_trace=positive_harness.trace,
            evidence_references=cast(Any, references),
        )


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        ({"raw_cas_namespace": "other-cas"}, "CAS_NAMESPACE_INVALID"),
        ({"raw_cas_address": "sha256/00/" + "0" * 64}, "CAS_ADDRESS_INVALID"),
        ({"raw_payload_byte_count": 0}, "RAW_PAYLOAD_BYTE_COUNT_INVALID"),
        ({"source_evidence_receipt_sha256": "A" * 64}, "RECEIPT_SHA256_INVALID"),
        ({"declared_trust_anchor_id": "bad trust anchor"}, "TRUST_ANCHOR_ID_INVALID"),
    ),
)
def test_reference_contract_is_strict(
    positive_harness: _Harness, changes: dict[str, object], reason: str
) -> None:
    reference = positive_harness.references[0]
    with pytest.raises(AuthenticatedFeatureResolutionCaptureV4ValidationError) as exc_info:
        replace(reference, **cast(Any, changes))
    _assert_reason(exc_info, f"AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_{reason}")


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        ("cas", "CAS_IDENTITY_CONTRADICTION"),
        ("receipt", "RECEIPT_IDENTITY_CONTRADICTION"),
        ("attested_material", "ATTESTED_MATERIAL_IDENTITY_CONTRADICTION"),
        ("attestation", "ATTESTATION_IDENTITY_CONTRADICTION"),
        ("trust_anchor", "TRUST_ANCHOR_IDENTITY_CONTRADICTION"),
    ),
)
def test_fully_rehashed_cross_slot_identity_contradictions_fail_closed(
    positive_harness: _Harness,
    optional_negative_harness: _Harness,
    mutation: str,
    reason: str,
) -> None:
    harness = (
        optional_negative_harness
        if mutation in {"receipt", "attested_material", "attestation"}
        else positive_harness
    )
    candidate = harness.artifact.capture
    ordinal = 259 if harness is optional_negative_harness else 1
    evidence = candidate["slot_captures"][ordinal]["source_evidence"]
    first_evidence = candidate["slot_captures"][0]["source_evidence"]
    if mutation == "cas":
        evidence["raw_payload_byte_count"] += 1
    elif mutation == "receipt":
        evidence["source_evidence_receipt_sha256"] = first_evidence[
            "source_evidence_receipt_sha256"
        ]
    elif mutation == "attested_material":
        evidence["attested_material_sha256"] = first_evidence["attested_material_sha256"]
    elif mutation == "attestation":
        evidence["source_attestation_sha256"] = first_evidence["source_attestation_sha256"]
    else:
        evidence["declared_public_key_sha256"] = "9" * 64
        evidence["source_attestation_sha256"] = "a" * 64
    _rehash_candidate(candidate, changed_slot=ordinal)

    with pytest.raises(AuthenticatedFeatureResolutionCaptureV4ValidationError) as exc_info:
        validate_authenticated_feature_resolution_capture_candidate_v4(candidate)
    _assert_reason(exc_info, f"AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_{reason}")


def test_fully_rehashed_receipt_identity_with_different_source_clock_fails_closed() -> None:
    tensor = trace_harness._tensor()
    observations = list(trace_harness._observations(tensor))
    observations[1] = replace(
        observations[1],
        event_time="2026-07-20T00:00:00.050000Z",
    )
    trace = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=trace_harness._SHA_D,
        observations=observations,
    )
    artifact = build_authenticated_feature_resolution_capture_candidate_v4(
        registry=FEATURE_SOURCE_REGISTRY_V4,
        resolution_trace=trace,
        evidence_references=_references(trace),
    )
    candidate = artifact.capture
    candidate["slot_captures"][1]["source_evidence"]["source_evidence_receipt_sha256"] = candidate[
        "slot_captures"
    ][0]["source_evidence"]["source_evidence_receipt_sha256"]
    _rehash_candidate(candidate, changed_slot=1)

    with pytest.raises(AuthenticatedFeatureResolutionCaptureV4ValidationError) as exc_info:
        validate_authenticated_feature_resolution_capture_candidate_v4(candidate)
    _assert_reason(
        exc_info,
        "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_RECEIPT_IDENTITY_CONTRADICTION",
    )


def test_fully_rehashed_typed_negative_identity_alias_fails_closed() -> None:
    tensor = trace_harness._tensor(negative_index=259)
    values = list(tensor.values)
    missing = list(tensor.missing_mask)
    available = list(tensor.source_availability)
    values[260] = 0.0
    missing[260] = 1
    available[260] = 0
    tensor = replace(
        tensor,
        values=tuple(values),
        missing_mask=tuple(missing),
        source_availability=tuple(available),
        source_availability_vector=tuple(available),
        missing_feature_names=tuple(
            name for name, mask in zip(tensor.feature_names, missing, strict=True) if mask == 1
        ),
        data_coverage_percent=100.0 * (len(missing) - sum(missing)) / len(missing),
    )
    observations = list(trace_harness._observations(tensor))
    source_clocks = {
        "event_time": "2026-07-20T00:00:00.000000Z",
        "ingested_at": "2026-07-20T00:00:00.100000Z",
        "generated_at": "2026-07-20T00:00:00.200000Z",
        "available_at": "2026-07-20T00:00:00.300000Z",
    }
    observations[259] = replace(observations[259], **source_clocks)
    observations[260] = replace(
        observations[260],
        negative_reason=NEGATIVE_CADENCE_OR_RATE_LIMIT_DEFERRED,
        **source_clocks,
    )
    trace = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=trace_harness._SHA_D,
        observations=observations,
    )
    artifact = build_authenticated_feature_resolution_capture_candidate_v4(
        registry=FEATURE_SOURCE_REGISTRY_V4,
        resolution_trace=trace,
        evidence_references=_references(trace),
    )
    candidate = artifact.capture
    candidate["slot_captures"][260]["source_evidence"]["source_evidence_receipt_sha256"] = (
        candidate["slot_captures"][259]["source_evidence"]["source_evidence_receipt_sha256"]
    )
    _rehash_candidate(candidate, changed_slot=260)

    with pytest.raises(AuthenticatedFeatureResolutionCaptureV4ValidationError) as exc_info:
        validate_authenticated_feature_resolution_capture_candidate_v4(candidate)
    _assert_reason(
        exc_info,
        "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_RECEIPT_IDENTITY_CONTRADICTION",
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        ("configured_source", "SLOT_TRACE_BINDING_MISMATCH"),
        ("resolver_alias", "SLOT_TRACE_BINDING_MISMATCH"),
        ("transform_code", "SLOT_TRACE_BINDING_MISMATCH"),
        ("clock", "SLOT_TRACE_BINDING_MISMATCH"),
        ("negative_numeric_zero", "SLOT_TRACE_BINDING_MISMATCH"),
    ),
)
def test_rehashed_semantic_slot_forgery_fails_against_embedded_trace(
    positive_harness: _Harness,
    optional_negative_harness: _Harness,
    mutation: str,
    reason: str,
) -> None:
    harness = optional_negative_harness if mutation == "negative_numeric_zero" else positive_harness
    candidate = harness.artifact.capture
    ordinal = 259 if mutation == "negative_numeric_zero" else 0
    slot = candidate["slot_captures"][ordinal]
    if mutation == "configured_source":
        slot["configured_source_label"] = "v2:market:forged"
    elif mutation == "resolver_alias":
        slot["resolver_branch"]["selected_alias"] = "forged_alias"
    elif mutation == "transform_code":
        slot["transform"]["transform_code_sha256"] = "9" * 64
    elif mutation == "clock":
        slot["clocks"]["available_at"] = "2026-07-20T00:00:00.000000Z"
    else:
        slot["transform"]["resolved_value_float32_be_hex"] = "00000000"
    _rehash_candidate(candidate, changed_slot=ordinal)

    with pytest.raises(AuthenticatedFeatureResolutionCaptureV4ValidationError) as exc_info:
        validate_authenticated_feature_resolution_capture_candidate_v4(candidate)
    _assert_reason(exc_info, f"AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_{reason}")


@pytest.mark.parametrize(
    "flag_path",
    (
        ("authentication_complete",),
        ("trainer_admission_authorized",),
        ("slot_captures", 0, "optional_typed_negative_authentication_verified"),
        ("slot_captures", 0, "source_evidence", "source_attestation_authentication_verified"),
    ),
)
def test_even_fully_rehashed_authentication_or_authority_claims_are_forbidden(
    positive_harness: _Harness, flag_path: tuple[object, ...]
) -> None:
    candidate = positive_harness.artifact.capture
    target: Any = candidate
    for part in flag_path[:-1]:
        target = target[part]
    target[flag_path[-1]] = True
    changed_slot = 0 if flag_path[0] == "slot_captures" else None
    _rehash_candidate(candidate, changed_slot=changed_slot)

    with pytest.raises(AuthenticatedFeatureResolutionCaptureV4ValidationError):
        validate_authenticated_feature_resolution_capture_candidate_v4(candidate)


def test_slot_tamper_permutation_and_chain_tamper_fail_closed(
    positive_harness: _Harness,
) -> None:
    for mutation in ("leaf", "permutation", "chain"):
        candidate = positive_harness.artifact.capture
        if mutation == "leaf":
            candidate["slot_captures"][0]["source_evidence"]["source_evidence_receipt_sha256"] = (
                "9" * 64
            )
        elif mutation == "permutation":
            candidate["slot_captures"][0], candidate["slot_captures"][1] = (
                candidate["slot_captures"][1],
                candidate["slot_captures"][0],
            )
        else:
            candidate["ordered_slot_capture_chain_sha256"] = "9" * 64
        with pytest.raises(AuthenticatedFeatureResolutionCaptureV4ValidationError):
            validate_authenticated_feature_resolution_capture_candidate_v4(candidate)


def test_capture_hash_is_deterministic_and_binds_every_byte(
    positive_harness: _Harness,
) -> None:
    rebuilt = build_authenticated_feature_resolution_capture_candidate_v4(
        registry=FEATURE_SOURCE_REGISTRY_V4,
        resolution_trace=positive_harness.trace,
        evidence_references=positive_harness.references,
    )
    assert rebuilt.capture_json == positive_harness.artifact.capture_json
    assert rebuilt.capture_sha256 == positive_harness.artifact.capture_sha256
    material = positive_harness.artifact.capture
    assert material.pop("capture_sha256") == positive_harness.artifact.capture_sha256
    expected = hashlib.sha256(
        json.dumps(
            material,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    assert expected == positive_harness.artifact.capture_sha256


def test_canonical_parser_round_trip_duplicate_keys_and_whitespace(
    positive_harness: _Harness,
) -> None:
    artifact = positive_harness.artifact
    parsed = parse_authenticated_feature_resolution_capture_candidate_v4(artifact.capture_json)
    parsed_bytes = parse_authenticated_feature_resolution_capture_candidate_v4(
        artifact.capture_json.encode("ascii")
    )
    assert parsed.capture_json == parsed_bytes.capture_json == artifact.capture_json

    duplicated = artifact.capture_json.replace(
        '{"audit_only":true,',
        '{"audit_only":true,"audit_only":true,',
        1,
    )
    with pytest.raises(
        AuthenticatedFeatureResolutionCaptureV4ValidationError,
        match="DUPLICATE_JSON_KEY",
    ):
        parse_authenticated_feature_resolution_capture_candidate_v4(duplicated)
    with pytest.raises(
        AuthenticatedFeatureResolutionCaptureV4ValidationError,
        match="JSON_NOT_CANONICAL",
    ):
        parse_authenticated_feature_resolution_capture_candidate_v4(" " + artifact.capture_json)


@pytest.mark.parametrize(
    "invalid_json",
    (
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":9223372036854775808}',
        '{"x":"\u2603"}',
        "[]",
    ),
)
def test_strict_json_rejects_constants_integer_overflow_unicode_and_non_object(
    invalid_json: str,
) -> None:
    with pytest.raises(AuthenticatedFeatureResolutionCaptureV4ValidationError):
        parse_authenticated_feature_resolution_capture_candidate_v4(invalid_json)


def test_artifact_and_references_are_factory_only_frozen_and_detached(
    positive_harness: _Harness,
) -> None:
    with pytest.raises(
        AuthenticatedFeatureResolutionCaptureV4ValidationError,
        match="FACTORY_CONSTRUCTION_REQUIRED",
    ):
        FeatureResolutionEvidenceReferenceV4(
            ordinal=0,
            feature_name="last_price",
            raw_cas_namespace=SOURCE_EVIDENCE_CAS_NAMESPACE_V4,
            raw_cas_address="sha256/11/" + "1" * 64,
            raw_payload_sha256="1" * 64,
            raw_payload_byte_count=1,
            source_evidence_receipt_kind=POSITIVE_SOURCE_READ_RECEIPT_KIND_V4,
            source_evidence_receipt_schema_version="receipt-v4",
            source_evidence_receipt_sha256=_SHA_RECEIPT,
            source_attestation_schema_version="attestation-v4",
            source_attestation_sha256=_SHA_ATTESTATION,
            attested_material_sha256=_SHA_MATERIAL,
            declared_trust_anchor_id="key-v1",
            declared_public_key_sha256=_SHA_PUBLIC_KEY,
            _construction_token=object(),
        )
    with pytest.raises(FrozenInstanceError):
        positive_harness.references[0].feature_name = "forged"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        positive_harness.artifact.capture_sha256 = "9" * 64  # type: ignore[misc]

    detached = positive_harness.artifact.capture
    detached["slot_captures"][0]["feature_name"] = "caller_mutation"
    assert positive_harness.artifact.capture["slot_captures"][0]["feature_name"] == "last_price"


def test_module_has_no_runtime_io_clock_or_service_wiring_surface() -> None:
    module_path = Path(capture_module.__file__)
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)

    assert not imported_roots & {
        "aiohttp",
        "asyncio",
        "httpx",
        "os",
        "pathlib",
        "redis",
        "requests",
        "socket",
        "subprocess",
        "time",
        "urllib",
    }
    assert not called_names & {
        "open",
        "read_bytes",
        "read_text",
        "time",
        "time_ns",
        "utcnow",
        "now",
        "publish",
    }
    assert "freshness_threshold" not in source
    assert "market_threshold" not in source

    app_root = module_path.parents[2]
    consumers = []
    for path in app_root.rglob("*.py"):
        if path == module_path:
            continue
        candidate_source = path.read_text(encoding="utf-8", errors="ignore")
        if "authenticated_feature_resolution_capture_v4" in candidate_source:
            consumers.append(path)
    assert consumers == []
