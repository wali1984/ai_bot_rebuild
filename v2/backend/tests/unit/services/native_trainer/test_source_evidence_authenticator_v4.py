from __future__ import annotations

import ast
import hashlib
import hmac
import json
import pickle
from collections.abc import Callable, Mapping
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import pytest

import v2.backend.app.services.native_trainer.source_evidence_authenticator_v4 as auth_module
from v2.backend.app.services.native_trainer.source_evidence_authenticator_v4 import (
    MAX_SOURCE_EVIDENCE_ATTESTATION_BYTES,
    MAX_SOURCE_EVIDENCE_PAYLOAD_BYTES,
    MIN_SOURCE_EVIDENCE_PROVENANCE_KEY_BYTES,
    POSITIVE_SOURCE_READ_EVIDENCE_KIND,
    SOURCE_EVIDENCE_ATTESTATION_MATERIAL_V4_CONTRACT_VERSION,
    SOURCE_EVIDENCE_ATTESTATION_V4_SCHEMA_VERSION,
    SOURCE_EVIDENCE_AUTH_ALGORITHM,
    SOURCE_EVIDENCE_AUTH_DOMAIN,
    SOURCE_EVIDENCE_AUTH_DOMAIN_SEPARATOR,
    SourceEvidenceAdapterAttestationV4,
    SourceEvidenceAuthenticatorV4,
    SourceEvidenceAuthenticatorV4ValidationError,
    SourceEvidenceAuthenticatorV4VerificationError,
    SourceEvidenceVerifierV4,
    parse_source_evidence_adapter_attestation_v4,
    validate_source_evidence_attestation_material_v4,
)

AUTH_KEY_ID = "source-provenance-unit-v1"
AUTH_KEY = b"source-provenance-unit-secret-01"
WRONG_KEY = b"source-provenance-unit-secret-02"

assert len(AUTH_KEY) >= MIN_SOURCE_EVIDENCE_PROVENANCE_KEY_BYTES
assert len(WRONG_KEY) >= MIN_SOURCE_EVIDENCE_PROVENANCE_KEY_BYTES


class _Resolver:
    def __init__(self, key: bytes = AUTH_KEY) -> None:
        self._key = key
        self.calls: list[str] = []

    def __call__(self, key_id: str) -> bytes:
        self.calls.append(key_id)
        if key_id != AUTH_KEY_ID:
            raise KeyError("resolver-secret-must-not-leak")
        return self._key


def _material(**overrides: object) -> dict[str, object]:
    material: dict[str, object] = {
        "contract_version": SOURCE_EVIDENCE_ATTESTATION_MATERIAL_V4_CONTRACT_VERSION,
        "source_evidence_schema_version": "future_positive_source_evidence_v4",
        "environment": "paper-audit",
        "namespace": "v2-native-trainer",
        "adapter_id": "canonical-ohlcv-closed-adapter-v4",
        "adapter_code_sha256": "a" * 64,
        "adapter_config_sha256": "b" * 64,
        "evidence_kind": POSITIVE_SOURCE_READ_EVIDENCE_KIND,
        "evidence_class": "EXACT_ATOMIC_SOURCE_ADAPTER_OUTPUT",
        "upstream_producer_identity_claim": "binance-public-market-data",
        "source_key": "v2:market:ohlcv_closed:binance:BTCUSDT:1m",
        "source_locator": "redis-primary/v2-market/ohlcv-closed/BTCUSDT/1m",
        "source_schema_version": "trainer_ohlcv_closed_window_v1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "run_id": "trainer-run-20260720-0001",
        "cycle_id": "sampling-cycle-20260720-0001",
        "decision_id": "decision-BTCUSDT-1m-20260720T120001",
        "exact_payload_sha256": "c" * 64,
        "exact_payload_byte_count": 12_345,
        "cas_namespace": "trainer-source-payload-cas-v1",
        "cas_address": "sha256/cc/" + ("c" * 64),
        "economic_event_time": "2026-07-20T12:00:00.000000Z",
        "producer_event_time": "2026-07-20T12:00:00.100000Z",
        "ingested_at": "2026-07-20T12:00:00.200000Z",
        "source_available_at": "2026-07-20T12:00:00.300000Z",
        "source_read_completed_at": "2026-07-20T12:00:00.400000Z",
        "decision_time": "2026-07-20T12:00:00.500000Z",
        "finality_kind": "CLOSED_INTERVAL",
        "finality_result": True,
        "branch_identity": "tensor-builder-branch-ohlcv-close-v1",
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
    material.update(overrides)
    return material


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sign(
    material: dict[str, object] | None = None,
    *,
    key: bytes = AUTH_KEY,
    key_id: str = AUTH_KEY_ID,
) -> SourceEvidenceAdapterAttestationV4:
    return SourceEvidenceAuthenticatorV4(
        auth_key_id=key_id,
        provenance_key=key,
    ).sign(_material() if material is None else material)


def _verify(
    artifact: SourceEvidenceAdapterAttestationV4 | str | bytes,
    *,
    expected_material: dict[str, object] | None = None,
    resolver: _Resolver | None = None,
    expected_key_id: str = AUTH_KEY_ID,
) -> Mapping[str, object]:
    return SourceEvidenceVerifierV4(
        retained_key_resolver=resolver or _Resolver(),
    ).verify(
        artifact,
        expected_auth_key_id=expected_key_id,
        expected_material=_material() if expected_material is None else expected_material,
    )


def _artifact_mapping(artifact: SourceEvidenceAdapterAttestationV4) -> dict[str, Any]:
    value = json.loads(artifact.attestation_json)
    assert isinstance(value, dict)
    return value


def test_sign_and_verify_exact_expected_replay_context() -> None:
    resolver = _Resolver()
    artifact = _sign()
    verified = _verify(artifact, resolver=resolver)

    assert resolver.calls == [AUTH_KEY_ID]
    assert artifact.schema_version == SOURCE_EVIDENCE_ATTESTATION_V4_SCHEMA_VERSION
    assert dict(verified) == _material()
    assert verified["adapter_attestation_verified"] is True
    assert verified["upstream_producer_authenticated"] is False
    assert verified["typed_negative_authenticated"] is False
    assert verified["per_slot_dependency_complete"] is False
    assert verified["trainer_admission_authorized"] is False
    assert verified["prediction_authorized"] is False
    assert verified["paper_trading_authorized"] is False
    assert verified["live_execution_authorized"] is False
    assert not hasattr(verified, "trainer_admission_authorized")


def test_manual_tag_uses_exact_domain_separated_hmac_sha256() -> None:
    artifact = _sign()
    envelope = _artifact_mapping(artifact)
    supplied = envelope.pop("auth_tag")
    expected = hmac.new(
        AUTH_KEY,
        SOURCE_EVIDENCE_AUTH_DOMAIN_SEPARATOR + _canonical(envelope).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()

    assert supplied == expected
    assert envelope["auth_algorithm"] == SOURCE_EVIDENCE_AUTH_ALGORITHM
    assert envelope["auth_domain"] == SOURCE_EVIDENCE_AUTH_DOMAIN


def test_parsed_artifact_is_not_a_verified_result() -> None:
    parsed = parse_source_evidence_adapter_attestation_v4(_sign().attestation_json)

    assert type(parsed) is SourceEvidenceAdapterAttestationV4
    assert "verify" not in vars(type(parsed))


def test_artifact_and_point_of_use_material_are_fresh_detached_read_only_copies() -> None:
    artifact = _sign()
    first = artifact.material
    first["symbol"] = "ETHUSDT"
    verified = _verify(artifact)

    assert artifact.material["symbol"] == "BTCUSDT"
    assert verified["source_key"] == _material()["source_key"]
    with pytest.raises(TypeError):
        cast(Any, verified)["source_key"] = "v2:attacker:replacement"
    assert verified["source_key"] == _material()["source_key"]
    with pytest.raises(FrozenInstanceError):
        artifact.auth_key_id = "replacement"  # type: ignore[misc]


def test_signer_and_verifier_are_immutable_redacted_and_not_serializable() -> None:
    signer = SourceEvidenceAuthenticatorV4(
        auth_key_id=AUTH_KEY_ID,
        provenance_key=AUTH_KEY,
    )
    verifier = SourceEvidenceVerifierV4(retained_key_resolver=_Resolver())
    secret_text = AUTH_KEY.decode("ascii")

    assert secret_text not in repr(signer)
    assert secret_text not in repr(verifier)
    assert secret_text not in _sign().attestation_json
    assert "<redacted>" in repr(signer)
    assert "<redacted>" in repr(verifier)
    with pytest.raises(AttributeError):
        signer.new_attribute = AUTH_KEY
    with pytest.raises(AttributeError):
        verifier.new_attribute = AUTH_KEY
    with pytest.raises(TypeError, match="not_serializable"):
        pickle.dumps(signer)
    with pytest.raises(TypeError, match="not_serializable"):
        pickle.dumps(verifier)


@pytest.mark.parametrize(
    "key_id",
    ("", " unsafe", "unsafe key", "unsafe\\key", "x" * 129),
)
def test_unsafe_key_ids_fail_without_echoing_input(key_id: str) -> None:
    with pytest.raises(SourceEvidenceAuthenticatorV4ValidationError) as exc_info:
        SourceEvidenceAuthenticatorV4(auth_key_id=key_id, provenance_key=AUTH_KEY)

    assert "auth_key_id_invalid" in str(exc_info.value)
    if key_id:
        assert key_id not in str(exc_info.value)


@pytest.mark.parametrize(
    "key",
    (
        b"short",
        bytearray(b"x" * 32),
        memoryview(b"x" * 32),
        "x" * 32,
    ),
)
def test_provenance_key_must_be_exact_bytes_and_at_least_32_bytes(key: object) -> None:
    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="source_evidence_provenance_key_invalid",
    ):
        SourceEvidenceAuthenticatorV4(auth_key_id=AUTH_KEY_ID, provenance_key=key)  # type: ignore[arg-type]


@pytest.mark.parametrize("field_name", sorted(_material()))
def test_material_requires_every_exact_field(field_name: str) -> None:
    material = _material()
    del material[field_name]

    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="material_field_set_mismatch",
    ):
        _sign(material)


def test_material_rejects_extra_fields_and_non_exact_dicts() -> None:
    material = _material(extra_claim="not-contract-owned")
    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="material_field_set_mismatch",
    ):
        _sign(material)
    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="material_not_exact_object",
    ):
        validate_source_evidence_attestation_material_v4(
            type("DictSubclass", (dict,), {})(_material())
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "reason"),
    (
        ("exact_payload_byte_count", True, "payload_byte_count_invalid"),
        ("exact_payload_byte_count", -1, "payload_byte_count_invalid"),
        (
            "exact_payload_byte_count",
            MAX_SOURCE_EVIDENCE_PAYLOAD_BYTES + 1,
            "payload_byte_count_invalid",
        ),
        ("exact_payload_byte_count", 10**100, "payload_byte_count_invalid"),
        ("exact_payload_byte_count", float("nan"), "payload_byte_count_invalid"),
        ("finality_result", 1, "finality_result_invalid"),
        ("exact_atomic_read_verified", 1, "exact_atomic_read_verified_invalid"),
        ("adapter_code_sha256", "A" * 64, "adapter_code_sha256_invalid"),
        ("symbol", "btcusdt", "symbol_invalid"),
        ("timeframe", "static", "timeframe_invalid"),
        ("environment", "paper-äudit", "environment_invalid"),
    ),
)
def test_scalar_types_ranges_and_ascii_fail_closed(
    field_name: str,
    invalid_value: object,
    reason: str,
) -> None:
    with pytest.raises(SourceEvidenceAuthenticatorV4ValidationError, match=reason):
        _sign(_material(**{field_name: invalid_value}))


@pytest.mark.parametrize(
    "field_name",
    (
        "upstream_producer_authenticated",
        "typed_negative_authenticated",
        "per_slot_dependency_complete",
        "trainer_admission_authorized",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
        "durable_ledger_appended",
        "feature_snapshot_published",
        "consumer_eligible",
        "runtime_wired",
    ),
)
def test_every_forbidden_authentication_or_downstream_flag_is_hash_bound_false(
    field_name: str,
) -> None:
    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="forbidden_authorization",
    ):
        _sign(_material(**{field_name: True}))


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "reason"),
    (
        ("adapter_attestation_verified", False, "adapter_attestation_not_hash_bound_true"),
        ("audit_only", False, "audit_only_not_hash_bound_true"),
        ("source_finality_verified", True, "finality_claim_inconsistent"),
    ),
)
def test_fixed_positive_flags_and_finality_consistency_fail_closed(
    field_name: str,
    invalid_value: object,
    reason: str,
) -> None:
    overrides: dict[str, object] = {field_name: invalid_value}
    if field_name == "source_finality_verified":
        overrides["finality_result"] = False
    with pytest.raises(SourceEvidenceAuthenticatorV4ValidationError, match=reason):
        _sign(_material(**overrides))


@pytest.mark.parametrize(
    ("earlier_field", "later_field"),
    (
        ("economic_event_time", "producer_event_time"),
        ("producer_event_time", "ingested_at"),
        ("ingested_at", "source_available_at"),
        ("source_available_at", "source_read_completed_at"),
        ("source_read_completed_at", "decision_time"),
    ),
)
def test_positive_read_enforces_complete_causal_clock_chain(
    earlier_field: str,
    later_field: str,
) -> None:
    material = _material()
    material[earlier_field], material[later_field] = (
        material[later_field],
        material[earlier_field],
    )

    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="causal_clock_order_invalid",
    ):
        _sign(material)


def test_positive_read_requires_every_source_clock_and_canonical_microsecond_utc() -> None:
    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="positive_read_clocks_required",
    ):
        _sign(_material(producer_event_time=None))
    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="decision_time_invalid",
    ):
        _sign(_material(decision_time="2026-07-20T12:00:00Z"))
    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="source_read_completed_at_invalid",
    ):
        _sign(_material(source_read_completed_at="2026-07-20T12:00:00.400000+00:00"))


def test_future_nonpositive_can_bind_no_clocks_without_authenticating_negative() -> None:
    material = _material(
        evidence_kind="FUTURE_TYPED_NEGATIVE_CANDIDATE",
        negative_type_identity="INTENTIONALLY_ISOLATED",
        economic_event_time=None,
        producer_event_time=None,
        ingested_at=None,
        source_available_at=None,
        source_read_completed_at=None,
        source_finality_verified=False,
        finality_result=False,
    )
    verified = _verify(_sign(material), expected_material=material)

    assert verified["negative_type_identity"] == "INTENTIONALLY_ISOLATED"
    assert verified["typed_negative_authenticated"] is False


def test_nonpositive_partial_source_clock_set_is_rejected() -> None:
    material = _material(
        evidence_kind="FUTURE_TYPED_NEGATIVE_CANDIDATE",
        negative_type_identity="SOURCE_STALE",
        producer_event_time=None,
    )
    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="source_clock_set_partial",
    ):
        _sign(material)


def test_wrong_key_and_wrong_expected_key_id_fail_closed() -> None:
    artifact = _sign()
    with pytest.raises(
        SourceEvidenceAuthenticatorV4VerificationError,
        match="attestation_verification_failed",
    ):
        _verify(artifact, resolver=_Resolver(WRONG_KEY))
    wrong_id_resolver = _Resolver()
    with pytest.raises(
        SourceEvidenceAuthenticatorV4VerificationError,
        match="retained_key_unavailable",
    ):
        _verify(artifact, resolver=wrong_id_resolver, expected_key_id="other-key-v1")
    assert wrong_id_resolver.calls == ["other-key-v1"]


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("environment", "different-environment"),
        ("namespace", "different-namespace"),
        ("adapter_id", "different-adapter-v4"),
        ("adapter_code_sha256", "d" * 64),
        ("adapter_config_sha256", "e" * 64),
        ("evidence_kind", "DIFFERENT_EVIDENCE_KIND"),
        ("evidence_class", "DIFFERENT_EVIDENCE_CLASS"),
        ("upstream_producer_identity_claim", "different-producer-claim"),
        ("source_key", "v2:market:ohlcv_closed:binance:ETHUSDT:1m"),
        ("source_locator", "redis-primary/v2-market/ohlcv-closed/ETHUSDT/1m"),
        ("source_schema_version", "different_source_schema_v1"),
        ("symbol", "ETHUSDT"),
        ("timeframe", "5m"),
        ("run_id", "different-run-0001"),
        ("cycle_id", "different-cycle-0001"),
        ("decision_id", "different-decision-0001"),
        ("exact_payload_sha256", "f" * 64),
        ("exact_payload_byte_count", 12_346),
        ("cas_namespace", "different-cas-v1"),
        ("cas_address", "sha256/ff/" + ("f" * 64)),
        ("decision_time", "2026-07-20T12:00:00.600000Z"),
        ("finality_kind", "VERSIONED_SNAPSHOT"),
        ("branch_identity", "different-resolver-branch-v1"),
        ("negative_type_identity", "SOURCE_STALE"),
    ),
)
def test_valid_tag_cannot_select_or_substitute_expected_replay_context(
    field_name: str,
    replacement: object,
) -> None:
    artifact = _sign()
    expected = _material(**{field_name: replacement})
    if field_name == "evidence_kind":
        expected["negative_type_identity"] = "FUTURE_NEGATIVE_IDENTITY"

    with pytest.raises(
        SourceEvidenceAuthenticatorV4VerificationError,
        match="attestation_verification_failed",
    ):
        _verify(artifact, expected_material=expected)


def test_validly_signed_attacker_context_still_cannot_replace_caller_expected_context() -> None:
    attacker_context = _material(symbol="ETHUSDT")
    artifact = _sign(attacker_context)

    with pytest.raises(
        SourceEvidenceAuthenticatorV4VerificationError,
        match="attestation_verification_failed",
    ):
        _verify(artifact, expected_material=_material())


def test_resealed_mutation_without_key_fails_authentication() -> None:
    artifact = _sign()
    envelope = _artifact_mapping(artifact)
    material = envelope["attestation_material"]
    assert isinstance(material, dict)
    material["source_key"] = "v2:market:ohlcv_closed:binance:ETHUSDT:1m"
    mutated = _canonical(envelope)

    with pytest.raises(
        SourceEvidenceAuthenticatorV4VerificationError,
        match="attestation_verification_failed",
    ):
        _verify(mutated, expected_material=_material(source_key=material["source_key"]))


def test_wrong_domain_schema_and_algorithm_are_structurally_rejected() -> None:
    for field_name, replacement in (
        ("auth_domain", "attacker-domain"),
        ("schema_version", "attacker_schema_v1"),
        ("auth_algorithm", "SHA256"),
    ):
        envelope = _artifact_mapping(_sign())
        envelope[field_name] = replacement
        with pytest.raises(SourceEvidenceAuthenticatorV4ValidationError):
            parse_source_evidence_adapter_attestation_v4(_canonical(envelope))


def test_verification_uses_compare_digest_for_tag_and_exact_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _sign()
    envelope = _artifact_mapping(artifact)
    envelope["auth_tag"] = "0" * 64
    mutated = _canonical(envelope)
    hmac_implementation = auth_module.hmac  # type: ignore[attr-defined]
    original_compare = cast(
        Callable[[object, object], bool],
        hmac_implementation.compare_digest,
    )
    comparisons: list[tuple[object, object]] = []

    def recording_compare(left: object, right: object) -> bool:
        comparisons.append((left, right))
        return original_compare(left, right)

    monkeypatch.setattr(hmac_implementation, "compare_digest", recording_compare)
    with pytest.raises(SourceEvidenceAuthenticatorV4VerificationError):
        _verify(mutated)

    assert any(right == "0" * 64 for _left, right in comparisons)
    assert any(type(left) is bytes and type(right) is bytes for left, right in comparisons)


def test_malformed_bounded_tag_still_reaches_compare_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = _artifact_mapping(_sign())
    envelope["auth_tag"] = "not-hex"
    mutated = _canonical(envelope)
    hmac_implementation = auth_module.hmac  # type: ignore[attr-defined]
    original_compare = cast(
        Callable[[object, object], bool],
        hmac_implementation.compare_digest,
    )
    seen_tag = False

    def recording_compare(left: object, right: object) -> bool:
        nonlocal seen_tag
        if right == "not-hex":
            seen_tag = True
        return original_compare(left, right)

    monkeypatch.setattr(hmac_implementation, "compare_digest", recording_compare)
    with pytest.raises(SourceEvidenceAuthenticatorV4VerificationError):
        _verify(mutated)
    assert seen_tag is True


def test_duplicate_noncanonical_nonfinite_deep_huge_and_oversize_json_fail_closed() -> None:
    canonical = _sign().attestation_json
    duplicate = '{"auth_algorithm":"HMAC-SHA256",' + canonical[1:]
    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="duplicate_json_key",
    ):
        parse_source_evidence_adapter_attestation_v4(duplicate)
    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="json_not_canonical",
    ):
        parse_source_evidence_adapter_attestation_v4(canonical + " ")
    with pytest.raises(SourceEvidenceAuthenticatorV4ValidationError):
        parse_source_evidence_adapter_attestation_v4('{"x":NaN}')
    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="json_integer_invalid",
    ):
        parse_source_evidence_adapter_attestation_v4('{"x":999999999999999999999}')
    deep: object = "leaf"
    for _index in range(8):
        deep = {"x": deep}
    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="json_depth_limit_exceeded",
    ):
        parse_source_evidence_adapter_attestation_v4(_canonical(deep))
    with pytest.raises(SourceEvidenceAuthenticatorV4ValidationError):
        parse_source_evidence_adapter_attestation_v4(
            "{" + (" " * MAX_SOURCE_EVIDENCE_ATTESTATION_BYTES) + "}"
        )


def test_duplicate_material_field_in_raw_json_fails_before_semantics() -> None:
    canonical = _sign().attestation_json
    needle = '"adapter_id":"canonical-ohlcv-closed-adapter-v4",'
    duplicate = canonical.replace(needle, needle + needle, 1)

    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="duplicate_json_key",
    ):
        parse_source_evidence_adapter_attestation_v4(duplicate)


def test_direct_dataclass_construction_is_only_an_integrity_guard_and_fails() -> None:
    artifact = _sign()
    with pytest.raises(
        SourceEvidenceAuthenticatorV4ValidationError,
        match="factory_construction_required",
    ):
        SourceEvidenceAdapterAttestationV4(
            schema_version=artifact.schema_version,
            auth_key_id=artifact.auth_key_id,
            auth_tag=artifact.auth_tag,
            attestation_json=artifact.attestation_json,
            _construction_token=object(),
        )


def test_reviewer_repro_reachable_module_token_cannot_bypass_invalid_tag() -> None:
    envelope = _artifact_mapping(_sign())
    envelope["auth_tag"] = "0" * 64
    forged_json = _canonical(envelope)
    construction_token = auth_module._CONSTRUCTION_TOKEN
    forged_artifact = SourceEvidenceAdapterAttestationV4(
        schema_version=SOURCE_EVIDENCE_ATTESTATION_V4_SCHEMA_VERSION,
        auth_key_id=AUTH_KEY_ID,
        auth_tag="0" * 64,
        attestation_json=forged_json,
        _construction_token=construction_token,
    )

    with pytest.raises(
        SourceEvidenceAuthenticatorV4VerificationError,
        match="attestation_verification_failed",
    ):
        _verify(forged_artifact)


def test_point_of_use_result_is_flat_read_only_data_without_authority_attributes() -> None:
    result = _verify(_sign())

    assert type(result) is type(MappingProxyType({}))
    assert dict(result) == _material()
    assert not hasattr(result, "trainer_admission_authorized")
    assert not hasattr(result, "prediction_authorized")
    assert result["trainer_admission_authorized"] is False
    with pytest.raises(TypeError):
        cast(Any, result)["trainer_admission_authorized"] = True
    with pytest.raises((AttributeError, TypeError)):
        object.__setattr__(result, "trainer_admission_authorized", True)
    assert result["trainer_admission_authorized"] is False


def test_every_verify_call_rechecks_hmac_and_prior_success_does_not_cover_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _sign()
    verifier = SourceEvidenceVerifierV4(retained_key_resolver=_Resolver())
    hmac_implementation = auth_module.hmac  # type: ignore[attr-defined]
    original_compare = cast(
        Callable[[object, object], bool],
        hmac_implementation.compare_digest,
    )
    supplied_tag = artifact.auth_tag
    tag_comparisons = 0

    def recording_compare(left: object, right: object) -> bool:
        nonlocal tag_comparisons
        if right == supplied_tag:
            tag_comparisons += 1
        return original_compare(left, right)

    monkeypatch.setattr(hmac_implementation, "compare_digest", recording_compare)
    first = verifier.verify(
        artifact,
        expected_auth_key_id=AUTH_KEY_ID,
        expected_material=_material(),
    )
    second = verifier.verify(
        artifact,
        expected_auth_key_id=AUTH_KEY_ID,
        expected_material=_material(),
    )
    assert tag_comparisons == 2
    assert first is not second

    envelope = _artifact_mapping(artifact)
    material = envelope["attestation_material"]
    assert isinstance(material, dict)
    material["source_key"] = "v2:market:ohlcv_closed:binance:ETHUSDT:1m"
    altered = _canonical(envelope)
    altered_expected = _material(source_key=material["source_key"])
    with pytest.raises(
        SourceEvidenceAuthenticatorV4VerificationError,
        match="attestation_verification_failed",
    ):
        verifier.verify(
            altered,
            expected_auth_key_id=AUTH_KEY_ID,
            expected_material=altered_expected,
        )
    assert first["source_key"] == _material()["source_key"]


def test_resolver_failures_and_bad_keys_are_generic_and_secret_free() -> None:
    marker = "resolver-private-material-must-not-leak"

    def raising_resolver(_key_id: str) -> bytes:
        raise RuntimeError(marker)

    for resolver in (
        raising_resolver,
        lambda _key_id: b"short",
        lambda _key_id: bytearray(b"x" * 32),
    ):
        with pytest.raises(
            SourceEvidenceAuthenticatorV4VerificationError,
            match="retained_key_unavailable",
        ) as exc_info:
            SourceEvidenceVerifierV4(retained_key_resolver=resolver).verify(
                _sign(),
                expected_auth_key_id=AUTH_KEY_ID,
                expected_material=_material(),
            )
        assert marker not in str(exc_info.value)
        assert AUTH_KEY.decode("ascii") not in str(exc_info.value)


def test_source_module_is_standard_library_only_and_has_no_io_or_runtime_wiring() -> None:
    module_path = Path(auth_module.__file__).resolve()
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    forbidden_call_names = {
        "open",
        "connect",
        "post",
        "publish",
        "request",
        "socket",
        "urlopen",
    }
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_names.add(node.func.id)

    assert imported_roots <= {
        "__future__",
        "collections",
        "dataclasses",
        "datetime",
        "hashlib",
        "hmac",
        "json",
        "re",
        "types",
        "typing",
    }
    assert imported_roots.isdisjoint({"app", "redis", "requests", "socket", "v2"})
    assert called_names.isdisjoint(forbidden_call_names)
    assert "class VerifiedSourceEvidenceAdapterAttestationV4" not in source
    assert "return MappingProxyType(dict(artifact_material))" in source
    assert '"trainer_admission_authorized"' in source
    assert '"prediction_authorized"' in source
    assert '"paper_trading_authorized"' in source
    assert '"live_execution_authorized"' in source


def test_only_point_of_use_hmac_verification_returns_read_only_material() -> None:
    artifact = _sign()
    parsed = parse_source_evidence_adapter_attestation_v4(artifact.attestation_json)

    assert type(parsed) is SourceEvidenceAdapterAttestationV4
    material = _verify(parsed)
    assert type(material) is type(MappingProxyType({}))
    assert material["adapter_attestation_verified"] is True
    assert material["trainer_admission_authorized"] is False
