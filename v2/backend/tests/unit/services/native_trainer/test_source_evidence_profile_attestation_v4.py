from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

import pytest

from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION,
)
from v2.backend.app.services.native_trainer.feature_resolution_observation_v4 import (
    NEGATIVE_CADENCE_OR_RATE_LIMIT_DEFERRED,
)
from v2.backend.app.services.native_trainer.source_evidence_authenticator_v4 import (
    POSITIVE_SOURCE_READ_EVIDENCE_KIND,
    SOURCE_EVIDENCE_ATTESTATION_MATERIAL_V4_CONTRACT_VERSION,
    SourceEvidenceAuthenticatorV4,
    SourceEvidenceAuthenticatorV4VerificationError,
    SourceEvidenceVerifierV4,
)
from v2.backend.app.services.native_trainer.source_evidence_profile_attestation_v4 import (
    CANONICAL_BINANCE_CLOSED_OHLCV_ADAPTER_ID_V4,
    CANONICAL_BINANCE_CLOSED_OHLCV_BRANCH_ID_V4,
    CANONICAL_BINANCE_CLOSED_OHLCV_EVIDENCE_CLASS_V4,
    CANONICAL_BINANCE_CLOSED_OHLCV_PRODUCER_CLAIM_V4,
    CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4,
    CANONICAL_BINANCE_CLOSED_OHLCV_SOURCE_EVIDENCE_SCHEMA_V4,
    MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_ADAPTER_ID_V4,
    MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_BRANCH_ID_V4,
    MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_EVIDENCE_CLASS_V4,
    MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PRODUCER_CLAIM_V4,
    MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PROFILE_V4,
    MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_EVIDENCE_SCHEMA_V4,
    MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_KEY_V4,
    MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_SCHEMA_V4,
    SOURCE_EVIDENCE_PROFILE_ATTESTATION_V4_SCHEMA_VERSION,
    SOURCE_EVIDENCE_TYPED_NEGATIVE_KIND,
    SourceEvidenceProfileAttestationV4Error,
    verify_source_evidence_profile_attestation_v4,
)

AUTH_KEY_ID = "source-semantics-unit-v1"
AUTH_KEY = b"source-semantics-unit-provenance-key-v1"
PAYLOAD_SHA256 = "c" * 64


class _Resolver:
    def __init__(self, key: bytes = AUTH_KEY) -> None:
        self.key = key
        self.calls: list[str] = []

    def __call__(self, key_id: str) -> bytes:
        self.calls.append(key_id)
        if key_id != AUTH_KEY_ID:
            raise KeyError("unknown-key")
        return self.key


def _base_material() -> dict[str, object]:
    return {
        "contract_version": SOURCE_EVIDENCE_ATTESTATION_MATERIAL_V4_CONTRACT_VERSION,
        "source_evidence_schema_version": (
            CANONICAL_BINANCE_CLOSED_OHLCV_SOURCE_EVIDENCE_SCHEMA_V4
        ),
        "environment": "paper-audit",
        "namespace": "v2-native-trainer",
        "adapter_id": CANONICAL_BINANCE_CLOSED_OHLCV_ADAPTER_ID_V4,
        "adapter_code_sha256": "a" * 64,
        "adapter_config_sha256": "b" * 64,
        "evidence_kind": POSITIVE_SOURCE_READ_EVIDENCE_KIND,
        "evidence_class": CANONICAL_BINANCE_CLOSED_OHLCV_EVIDENCE_CLASS_V4,
        "upstream_producer_identity_claim": (CANONICAL_BINANCE_CLOSED_OHLCV_PRODUCER_CLAIM_V4),
        "source_key": "v2:market:ohlcv_closed:binance:BTCUSDT:1m",
        "source_locator": "redis-mget/v2-market/ohlcv-closed/BTCUSDT/1m",
        "source_schema_version": CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "run_id": "trainer-run-20260720-0001",
        "cycle_id": "sampling-cycle-20260720-0001",
        "decision_id": "decision-BTCUSDT-1m-20260720T120001",
        "exact_payload_sha256": PAYLOAD_SHA256,
        "exact_payload_byte_count": 12_345,
        "cas_namespace": "trainer-source-payload-cas-v1",
        "cas_address": f"sha256/{PAYLOAD_SHA256[:2]}/{PAYLOAD_SHA256}",
        "economic_event_time": "2026-07-20T12:00:00.000000Z",
        "producer_event_time": "2026-07-20T12:00:00.100000Z",
        "ingested_at": "2026-07-20T12:00:00.200000Z",
        "source_available_at": "2026-07-20T12:00:00.300000Z",
        "source_read_completed_at": "2026-07-20T12:00:00.400000Z",
        "decision_time": "2026-07-20T12:00:00.500000Z",
        "finality_kind": "CLOSED_INTERVAL",
        "finality_result": True,
        "branch_identity": CANONICAL_BINANCE_CLOSED_OHLCV_BRANCH_ID_V4,
        "negative_type_identity": None,
        "exact_atomic_read_verified": True,
        "source_schema_adapter_verified": True,
        "source_finality_verified": True,
        "adapter_attestation_verified": True,
        "upstream_producer_authenticated": False,
        "typed_negative_authenticated": False,
        "per_slot_dependency_complete": False,
        "trainer_admission_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "durable_ledger_appended": False,
        "feature_snapshot_published": False,
        "consumer_eligible": False,
        "runtime_wired": False,
        "audit_only": True,
    }


def _moralis_material() -> dict[str, object]:
    return {
        **_base_material(),
        "source_evidence_schema_version": (
            MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_EVIDENCE_SCHEMA_V4
        ),
        "adapter_id": MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_ADAPTER_ID_V4,
        "evidence_kind": SOURCE_EVIDENCE_TYPED_NEGATIVE_KIND,
        "evidence_class": MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_EVIDENCE_CLASS_V4,
        "upstream_producer_identity_claim": (MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PRODUCER_CLAIM_V4),
        "source_key": MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_KEY_V4,
        "source_locator": "redis-atomic-mget/moralis-scheduler-and-cu-budget",
        "source_schema_version": MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_SOURCE_SCHEMA_V4,
        "branch_identity": MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_BRANCH_ID_V4,
        "negative_type_identity": NEGATIVE_CADENCE_OR_RATE_LIMIT_DEFERRED,
        "finality_kind": "TYPED_NEGATIVE_CONTROL_STATE",
        "finality_result": False,
        "source_finality_verified": False,
    }


def _signed(material: dict[str, object]) -> Any:
    return SourceEvidenceAuthenticatorV4(
        auth_key_id=AUTH_KEY_ID,
        provenance_key=AUTH_KEY,
    ).sign(material)


def _verify(
    material: dict[str, object],
    profile: str,
    *,
    resolver: _Resolver | None = None,
    artifact: Any | None = None,
) -> Mapping[str, object]:
    return verify_source_evidence_profile_attestation_v4(
        verifier=SourceEvidenceVerifierV4(retained_key_resolver=resolver or _Resolver()),
        artifact=_signed(material) if artifact is None else artifact,
        expected_auth_key_id=AUTH_KEY_ID,
        expected_material=material,
        expected_profile_id=profile,
    )


def test_closed_ohlcv_positive_declaration_is_freshly_authenticated_and_classified() -> None:
    resolver = _Resolver()
    material = _base_material()
    result = _verify(material, CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4, resolver=resolver)

    assert resolver.calls == [AUTH_KEY_ID]
    assert result["schema_version"] == SOURCE_EVIDENCE_PROFILE_ATTESTATION_V4_SCHEMA_VERSION
    assert result["profile_id"] == CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4
    assert result["adapter_attestation_authenticated"] is True
    assert result["authenticated_adapter_declaration_verified"] is True
    assert result["source_profile_declaration_verified"] is True
    assert result["positive_source_profile_declared"] is True
    assert result["typed_negative_profile_declared"] is False
    assert result["source_specific_semantics_verified"] is False
    assert result["positive_source_read_semantics_verified"] is False
    assert result["typed_negative_semantics_verified"] is False
    assert result["payload_semantics_recomputed"] is False
    assert result["source_key"] == material["source_key"]
    assert result["exact_payload_sha256"] == PAYLOAD_SHA256
    assert result["cas_address"] == material["cas_address"]


def test_moralis_cadence_negative_is_distinct_from_positive_evidence() -> None:
    material = _moralis_material()
    result = _verify(material, MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PROFILE_V4)

    assert result["profile_id"] == MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PROFILE_V4
    assert result["evidence_kind"] == SOURCE_EVIDENCE_TYPED_NEGATIVE_KIND
    assert result["negative_type_identity"] == NEGATIVE_CADENCE_OR_RATE_LIMIT_DEFERRED
    assert result["positive_source_profile_declared"] is False
    assert result["typed_negative_profile_declared"] is True
    assert result["positive_source_read_semantics_verified"] is False
    assert result["typed_negative_semantics_verified"] is False


@pytest.mark.parametrize(
    "profile",
    (
        CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4,
        MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PROFILE_V4,
    ),
)
def test_profile_attestation_does_not_promote_arbitrary_unpinned_payload_or_adapter(
    profile: str,
) -> None:
    material = (
        _base_material()
        if profile == CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4
        else _moralis_material()
    )
    arbitrary_digest = "f" * 64
    material.update(
        {
            "adapter_code_sha256": "d" * 64,
            "adapter_config_sha256": "e" * 64,
            "exact_payload_sha256": arbitrary_digest,
            "exact_payload_byte_count": 7,
            "cas_address": f"sha256/{arbitrary_digest[:2]}/{arbitrary_digest}",
            "source_locator": "caller-selected/arbitrary-locator",
        }
    )

    result = _verify(material, profile)

    assert result["authenticated_adapter_declaration_verified"] is True
    assert result["source_profile_declaration_verified"] is True
    for field_name in (
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
    ):
        assert result[field_name] is False


@pytest.mark.parametrize(
    ("field_name", "replacement", "reason"),
    (
        ("source_evidence_schema_version", "other_schema_v4", "ohlcv_evidence_schema_invalid"),
        ("evidence_kind", SOURCE_EVIDENCE_TYPED_NEGATIVE_KIND, "ohlcv_kind_invalid"),
        ("evidence_class", "OTHER_CLASS", "ohlcv_class_invalid"),
        ("adapter_id", "other-adapter-v4", "ohlcv_adapter_invalid"),
        ("source_schema_version", "other_schema_v1", "ohlcv_schema_invalid"),
        ("upstream_producer_identity_claim", "other-producer", "ohlcv_producer_claim_invalid"),
        ("branch_identity", "other-branch-v4", "ohlcv_branch_invalid"),
        (
            "negative_type_identity",
            NEGATIVE_CADENCE_OR_RATE_LIMIT_DEFERRED,
            "ohlcv_negative_forbidden",
        ),
        ("finality_kind", "VERSIONED_SNAPSHOT", "ohlcv_finality_kind_invalid"),
        (
            "source_finality_verified",
            False,
            "ohlcv_finality_declaration_required",
        ),
        ("source_key", "v2:market:ohlcv_closed:binance:ETHUSDT:1m", "ohlcv_source_key_invalid"),
        (
            "exact_atomic_read_verified",
            False,
            "exact_atomic_read_declaration_required",
        ),
        (
            "source_schema_adapter_verified",
            False,
            "source_adapter_declaration_required",
        ),
        ("environment", "live", "environment_invalid"),
        ("namespace", "other-namespace", "namespace_invalid"),
        ("exact_payload_byte_count", 0, "empty_payload_forbidden"),
        ("cas_namespace", "other-cas-v1", "cas_namespace_invalid"),
        ("cas_address", f"sha256/cc/{'d' * 64}", "cas_address_binding_invalid"),
    ),
)
def test_closed_ohlcv_profile_rejects_every_declaration_binding_mutation(
    field_name: str,
    replacement: object,
    reason: str,
) -> None:
    material = _base_material()
    material[field_name] = replacement

    with pytest.raises(SourceEvidenceProfileAttestationV4Error, match=reason):
        _verify(material, CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4)


@pytest.mark.parametrize(
    ("field_name", "replacement", "reason"),
    (
        (
            "source_evidence_schema_version",
            "other_schema_v4",
            "moralis_negative_evidence_schema_invalid",
        ),
        ("evidence_kind", POSITIVE_SOURCE_READ_EVIDENCE_KIND, "moralis_negative_kind_invalid"),
        ("evidence_class", "OTHER_CLASS", "moralis_negative_class_invalid"),
        ("adapter_id", "other-adapter-v4", "moralis_negative_adapter_invalid"),
        ("source_schema_version", "other_schema_v1", "moralis_negative_schema_invalid"),
        (
            "upstream_producer_identity_claim",
            "other-producer",
            "moralis_negative_producer_claim_invalid",
        ),
        ("branch_identity", "other-branch-v4", "moralis_negative_branch_invalid"),
        (
            "source_key",
            "v2:provider:moralis:scheduler_status",
            "moralis_negative_source_key_invalid",
        ),
        ("negative_type_identity", "SOURCE_UNAVAILABLE", "moralis_negative_type_invalid"),
        ("finality_kind", "CLOSED_INTERVAL", "moralis_negative_finality_kind_invalid"),
        ("finality_result", True, "moralis_negative_finality_result_invalid"),
        (
            "exact_atomic_read_verified",
            False,
            "exact_atomic_read_declaration_required",
        ),
        (
            "source_schema_adapter_verified",
            False,
            "source_adapter_declaration_required",
        ),
        ("environment", "live", "environment_invalid"),
        ("namespace", "other-namespace", "namespace_invalid"),
    ),
)
def test_moralis_negative_profile_rejects_every_declaration_binding_mutation(
    field_name: str,
    replacement: object,
    reason: str,
) -> None:
    material = _moralis_material()
    material[field_name] = replacement

    with pytest.raises(SourceEvidenceProfileAttestationV4Error, match=reason):
        _verify(material, MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PROFILE_V4)


def test_closed_ohlcv_requires_close_strictly_before_availability_and_decision() -> None:
    material = _base_material()
    close = cast(str, material["economic_event_time"])
    material["producer_event_time"] = close
    material["ingested_at"] = close
    material["source_available_at"] = close

    with pytest.raises(SourceEvidenceProfileAttestationV4Error, match="not_available_after_close"):
        _verify(material, CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4)

    material = _base_material()
    close = cast(str, material["economic_event_time"])
    material["producer_event_time"] = close
    material["ingested_at"] = close
    material["source_available_at"] = close
    material["source_read_completed_at"] = close
    material["decision_time"] = close
    with pytest.raises(SourceEvidenceProfileAttestationV4Error, match="not_available_after_close"):
        _verify(material, CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4)


def test_declaration_profiles_reject_paired_finality_claim_mutations() -> None:
    positive = _base_material()
    positive["finality_result"] = False
    positive["source_finality_verified"] = False
    with pytest.raises(
        SourceEvidenceProfileAttestationV4Error, match="ohlcv_finality_result_invalid"
    ):
        _verify(positive, CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4)

    negative = _moralis_material()
    negative["finality_result"] = True
    negative["source_finality_verified"] = True
    with pytest.raises(
        SourceEvidenceProfileAttestationV4Error,
        match="moralis_negative_finality_result_invalid",
    ):
        _verify(negative, MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PROFILE_V4)


def test_public_error_reasons_use_declaration_profile_contract_names() -> None:
    material = _base_material()
    material["source_finality_verified"] = False

    with pytest.raises(SourceEvidenceProfileAttestationV4Error) as exc_info:
        _verify(material, CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4)

    assert exc_info.value.reasons == (
        "source_evidence_profile_attestation_v4_ohlcv_finality_declaration_required",
    )


def test_profile_is_caller_selected_and_cross_profile_substitution_fails() -> None:
    positive = _base_material()
    negative = _moralis_material()

    with pytest.raises(
        SourceEvidenceProfileAttestationV4Error,
        match="moralis_negative_evidence_schema_invalid",
    ):
        _verify(positive, MORALIS_CADENCE_RATE_LIMIT_NEGATIVE_PROFILE_V4)
    with pytest.raises(
        SourceEvidenceProfileAttestationV4Error,
        match="ohlcv_evidence_schema_invalid",
    ):
        _verify(negative, CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4)
    with pytest.raises(SourceEvidenceProfileAttestationV4Error, match="profile_invalid"):
        _verify(positive, "artifact-selected-profile-v4")


def test_authenticated_artifact_cannot_be_replayed_against_different_expected_context() -> None:
    material = _base_material()
    artifact = _signed(material)
    replacement = _base_material()
    replacement["decision_id"] = "decision-BTCUSDT-1m-replacement"

    with pytest.raises(
        SourceEvidenceAuthenticatorV4VerificationError,
        match="source_evidence_attestation_verification_failed",
    ):
        _verify(
            replacement,
            CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4,
            artifact=artifact,
        )


def test_string_and_bytes_artifacts_are_freshly_parsed_and_verified() -> None:
    material = _base_material()
    artifact_json = _signed(material).attestation_json

    string_result = _verify(
        material,
        CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4,
        artifact=artifact_json,
    )
    bytes_result = _verify(
        material,
        CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4,
        artifact=artifact_json.encode("ascii"),
    )

    assert dict(string_result) == dict(bytes_result)


def test_result_is_detached_read_only_and_grants_no_downstream_authority() -> None:
    material = _base_material()
    result = _verify(material, CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4)
    material["source_key"] = "v2:attacker:replacement"

    assert result["source_key"] == "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    with pytest.raises(TypeError):
        cast(Any, result)["source_key"] = "v2:attacker:replacement"
    for field_name in (
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
    ):
        assert result[field_name] is False
    assert result["audit_only"] is True


def test_output_hashes_bind_exact_attestation_and_material() -> None:
    material = _base_material()
    artifact = _signed(material)
    result = _verify(
        material,
        CANONICAL_BINANCE_CLOSED_OHLCV_PROFILE_V4,
        artifact=artifact,
    )

    assert len(cast(str, result["adapter_attestation_sha256"])) == 64
    assert len(cast(str, result["attestation_material_sha256"])) == 64
    assert result["adapter_attestation_sha256"] != result["attestation_material_sha256"]
    assert json.loads(artifact.attestation_json)["attestation_material"] == material
