from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, cast

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.services.native_trainer import (
    source_evidence_ed25519_attestation_v4 as attestation_module,
)
from v2.backend.app.services.native_trainer.source_evidence_ed25519_attestation_v4 import (
    MAX_SOURCE_EVIDENCE_ED25519_ATTESTATION_BYTES,
    MAX_SOURCE_EVIDENCE_ED25519_CONTAINER_ITEMS,
    MAX_SOURCE_EVIDENCE_ED25519_JSON_DEPTH,
    MAX_SOURCE_EVIDENCE_ED25519_JSON_NODES,
    MAX_SOURCE_EVIDENCE_ED25519_KEY_BYTES,
    MAX_SOURCE_EVIDENCE_ED25519_STRING_BYTES,
    SOURCE_EVIDENCE_ED25519_ALGORITHM,
    SOURCE_EVIDENCE_ED25519_ATTESTATION_V4_SCHEMA_VERSION,
    SOURCE_EVIDENCE_ED25519_DOMAIN,
    SOURCE_EVIDENCE_ED25519_DOMAIN_SEPARATOR,
    SOURCE_EVIDENCE_ED25519_VERIFICATION_V4_SCHEMA_VERSION,
    SourceEvidenceEd25519AttestationV4,
    SourceEvidenceEd25519AttestationV4ValidationError,
    SourceEvidenceEd25519AttestationV4VerificationError,
    parse_source_evidence_ed25519_attestation_v4,
    sign_source_evidence_ed25519_attestation_v4_for_producer,
    source_evidence_ed25519_public_key_sha256_v4,
    verify_source_evidence_ed25519_attestation_v4,
)

# This deterministic key is test-fixture material only.  Its name, seed input,
# and trust-anchor ID are deliberately and visibly distinct from any deployable
# registry anchor.  It must never be copied into a production registry.
TEST_TRUST_ANCHOR_ID = "TEST_ONLY_source_evidence_ed25519_v4_unit_anchor_DO_NOT_DEPLOY"
TEST_PRIVATE_KEY_BYTES = hashlib.sha256(
    b"TEST-ONLY source evidence Ed25519 v4 unit key; never deploy"
).digest()
OTHER_PRIVATE_KEY_BYTES = hashlib.sha256(
    b"TEST-ONLY arbitrary attacker Ed25519 v4 unit key; never deploy"
).digest()

_FALSE_AUTHORITY_FIELDS = (
    "upstream_producer_authenticated",
    "source_payload_semantics_verified",
    "source_finality_recomputed",
    "dependency_manifest_bound",
    "per_field_receipt_bound",
    "feature_snapshot_published",
    "consumer_eligible",
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "runtime_wired",
)


def _public_key_bytes(private_key_bytes: bytes) -> bytes:
    return (
        Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )


TEST_PUBLIC_KEY_BYTES = _public_key_bytes(TEST_PRIVATE_KEY_BYTES)
TEST_PUBLIC_KEY_SHA256 = hashlib.sha256(TEST_PUBLIC_KEY_BYTES).hexdigest()
OTHER_PUBLIC_KEY_BYTES = _public_key_bytes(OTHER_PRIVATE_KEY_BYTES)
OTHER_PUBLIC_KEY_SHA256 = hashlib.sha256(OTHER_PUBLIC_KEY_BYTES).hexdigest()


def _material() -> dict[str, object]:
    return {
        "adapter_id": "canonical-ohlcv-closed-adapter-v4",
        "audit_only": True,
        "clock_identity": {
            "decision_time": "2026-07-20T12:00:00.500000Z",
            "event_time": "2026-07-20T12:00:00.000000Z",
            "source_available_at": "2026-07-20T12:00:00.300000Z",
        },
        "exact_payload_byte_count": 12345,
        "exact_payload_sha256": "c" * 64,
        "optional_observations": [None, False, "CADENCE_DEFERRED"],
        "paper_trading_authorized": False,
        "symbol": "BTCUSDT",
        "trainer_admission_authorized": False,
    }


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
    private_key_bytes: bytes = TEST_PRIVATE_KEY_BYTES,
    trust_anchor_id: str = TEST_TRUST_ANCHOR_ID,
) -> SourceEvidenceEd25519AttestationV4:
    return sign_source_evidence_ed25519_attestation_v4_for_producer(
        private_key_bytes=private_key_bytes,
        declared_trust_anchor_id=trust_anchor_id,
        attested_material=_material() if material is None else material,
    )


def _verify(
    artifact: SourceEvidenceEd25519AttestationV4 | str | bytes,
    material: dict[str, object] | None = None,
    *,
    public_key_bytes: bytes = TEST_PUBLIC_KEY_BYTES,
    public_key_sha256: str = TEST_PUBLIC_KEY_SHA256,
    trust_anchor_id: str = TEST_TRUST_ANCHOR_ID,
) -> Any:
    return verify_source_evidence_ed25519_attestation_v4(
        artifact,
        registry_public_key_bytes=public_key_bytes,
        registry_public_key_sha256=public_key_sha256,
        expected_trust_anchor_id=trust_anchor_id,
        expected_material=_material() if material is None else material,
    )


def test_exact_domain_separated_signature_and_registry_owned_verification() -> None:
    material = _material()
    artifact = _sign(material)
    document = cast(dict[str, object], json.loads(artifact.attestation_json))
    signature = bytes.fromhex(cast(str, document.pop("signature_hex")))
    unsigned_bytes = _canonical(document).encode("ascii")

    public_key = Ed25519PrivateKey.from_private_bytes(TEST_PRIVATE_KEY_BYTES).public_key()
    public_key.verify(signature, SOURCE_EVIDENCE_ED25519_DOMAIN_SEPARATOR + unsigned_bytes)
    with pytest.raises(InvalidSignature):
        public_key.verify(signature, unsigned_bytes)

    result = _verify(artifact, material)
    assert artifact.schema_version == SOURCE_EVIDENCE_ED25519_ATTESTATION_V4_SCHEMA_VERSION
    assert artifact.declared_trust_anchor_id == TEST_TRUST_ANCHOR_ID
    assert artifact.declared_public_key_sha256 == TEST_PUBLIC_KEY_SHA256
    assert source_evidence_ed25519_public_key_sha256_v4(TEST_PUBLIC_KEY_BYTES) == (
        TEST_PUBLIC_KEY_SHA256
    )
    assert result["schema_version"] == SOURCE_EVIDENCE_ED25519_VERIFICATION_V4_SCHEMA_VERSION
    assert result["signature_algorithm"] == SOURCE_EVIDENCE_ED25519_ALGORITHM
    assert result["signature_domain"] == SOURCE_EVIDENCE_ED25519_DOMAIN
    assert result["trust_anchor_id"] == TEST_TRUST_ANCHOR_ID
    assert result["registry_public_key_sha256"] == TEST_PUBLIC_KEY_SHA256
    assert result["cryptographic_signature_verified"] is True
    assert result["registry_trust_anchor_binding_verified"] is True
    assert result["expected_material_exact_match_verified"] is True
    assert result["attested_material_canonical_json"] == _canonical(material)
    assert result["audit_only"] is True
    for field_name in _FALSE_AUTHORITY_FIELDS:
        assert result[field_name] is False


def test_result_is_detached_flat_read_only_and_signer_snapshots_caller_material() -> None:
    material = _material()
    expected = json.loads(_canonical(material))
    artifact = _sign(material)
    cast(dict[str, Any], material["clock_identity"])["decision_time"] = (
        "2099-01-01T00:00:00.000000Z"
    )
    cast(list[object], material["optional_observations"]).append("future")

    result = _verify(artifact, cast(dict[str, object], expected))
    assert all(type(value) in (str, bool) for value in result.values())
    with pytest.raises(TypeError):
        cast(dict[str, object], result)["runtime_wired"] = True
    assert json.loads(cast(str, result["attested_material_canonical_json"])) == expected


def test_test_anchor_is_explicitly_nonproduction_and_private_material_is_never_serialized() -> None:
    artifact = _sign()

    assert TEST_TRUST_ANCHOR_ID.startswith("TEST_ONLY_")
    assert TEST_PRIVATE_KEY_BYTES.hex() not in artifact.attestation_json
    assert TEST_PUBLIC_KEY_BYTES.hex() not in artifact.attestation_json
    assert "public_key_bytes" not in artifact.attestation_json
    assert "private_key" not in artifact.attestation_json
    assert "<redacted>" in repr(artifact)


def test_arbitrary_other_private_key_under_same_anchor_id_is_rejected() -> None:
    attacker_artifact = _sign(private_key_bytes=OTHER_PRIVATE_KEY_BYTES)
    assert attacker_artifact.declared_trust_anchor_id == TEST_TRUST_ANCHOR_ID
    assert attacker_artifact.declared_public_key_sha256 == OTHER_PUBLIC_KEY_SHA256

    with pytest.raises(
        SourceEvidenceEd25519AttestationV4VerificationError,
        match="attestation_verification_failed",
    ):
        _verify(attacker_artifact)


def test_artifact_cannot_select_or_substitute_the_registry_trust_anchor() -> None:
    artifact = _sign()
    verifier_parameters = inspect.signature(
        verify_source_evidence_ed25519_attestation_v4
    ).parameters
    assert "registry_public_key_bytes" in verifier_parameters
    assert "registry_public_key_sha256" in verifier_parameters
    assert "expected_trust_anchor_id" in verifier_parameters
    assert "expected_material" in verifier_parameters
    assert "resolver" not in verifier_parameters
    assert "private_key" not in verifier_parameters

    with pytest.raises(SourceEvidenceEd25519AttestationV4VerificationError):
        _verify(
            artifact,
            public_key_bytes=OTHER_PUBLIC_KEY_BYTES,
            public_key_sha256=OTHER_PUBLIC_KEY_SHA256,
        )
    with pytest.raises(
        SourceEvidenceEd25519AttestationV4VerificationError,
        match="registry_public_key_fingerprint_mismatch",
    ):
        _verify(artifact, public_key_sha256=OTHER_PUBLIC_KEY_SHA256)
    with pytest.raises(SourceEvidenceEd25519AttestationV4VerificationError):
        _verify(artifact, trust_anchor_id="TEST_ONLY_substituted_anchor")

    injected_key = cast(dict[str, object], json.loads(artifact.attestation_json))
    injected_key["public_key_hex"] = OTHER_PUBLIC_KEY_BYTES.hex()
    with pytest.raises(
        SourceEvidenceEd25519AttestationV4ValidationError,
        match="envelope_field_set_mismatch",
    ):
        parse_source_evidence_ed25519_attestation_v4(_canonical(injected_key))


def test_material_tamper_and_complete_expected_material_mismatch_fail_closed() -> None:
    artifact = _sign()
    expected_material = _material()
    wrong_expected = _material()
    wrong_expected["symbol"] = "ETHUSDT"
    with pytest.raises(
        SourceEvidenceEd25519AttestationV4VerificationError,
        match="attestation_verification_failed",
    ):
        _verify(artifact, wrong_expected)

    tampered = cast(dict[str, Any], json.loads(artifact.attestation_json))
    cast(dict[str, object], tampered["attested_material"])["symbol"] = "ETHUSDT"
    tampered_material_bytes = _canonical(tampered["attested_material"]).encode("ascii")
    tampered["attested_material_sha256"] = hashlib.sha256(tampered_material_bytes).hexdigest()
    coherently_rehashed_but_unsigned = parse_source_evidence_ed25519_attestation_v4(
        _canonical(tampered)
    )
    with pytest.raises(
        SourceEvidenceEd25519AttestationV4VerificationError,
        match="attestation_verification_failed",
    ):
        _verify(coherently_rehashed_but_unsigned, expected_material)


@pytest.mark.parametrize(
    "forbidden_material",
    [
        {"trainer_admission_authorized": True},
        {"nested": {"live_execution_authorized": 1}},
        {"audit_only": False},
        {"cryptographic_signature_verified": True},
        {"nested": [{"expected_material_exact_match_verified": False}]},
    ],
)
def test_attested_material_cannot_embed_authority_or_verifier_claims(
    forbidden_material: dict[str, object],
) -> None:
    with pytest.raises(SourceEvidenceEd25519AttestationV4ValidationError):
        _sign(forbidden_material)


def test_declared_key_fingerprint_tamper_and_noncanonical_signature_reject() -> None:
    artifact = _sign()
    fingerprint_tamper = cast(dict[str, object], json.loads(artifact.attestation_json))
    fingerprint_tamper["declared_public_key_sha256"] = OTHER_PUBLIC_KEY_SHA256
    parsed_tamper = parse_source_evidence_ed25519_attestation_v4(_canonical(fingerprint_tamper))
    with pytest.raises(SourceEvidenceEd25519AttestationV4VerificationError):
        _verify(parsed_tamper)

    uppercase_signature = cast(dict[str, object], json.loads(artifact.attestation_json))
    uppercase_signature["signature_hex"] = cast(str, uppercase_signature["signature_hex"]).upper()
    with pytest.raises(
        SourceEvidenceEd25519AttestationV4ValidationError,
        match="signature_encoding_invalid",
    ):
        parse_source_evidence_ed25519_attestation_v4(_canonical(uppercase_signature))


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"", "json_input_invalid"),
        (b"[]", "json_not_exact_object"),
        (b'{"x":1,"x":2}', "duplicate_json_key"),
        (b'{"x":1.0}', "json_float_forbidden"),
        (b'{"x":NaN}', "json_constant_forbidden"),
        (b'{"x":9223372036854775808}', "json_integer_out_of_range"),
        (b'{"x":-9223372036854775809}', "json_integer_out_of_range"),
        ('{"x":"\u00e9"}'.encode(), "json_input_invalid"),
        (b'{"x":"\\u00e9"}', "non_ascii_text_forbidden"),
        (b'{ "x":1}', "json_not_exact_canonical"),
        (b'{"z":0,"a":1}', "json_not_exact_canonical"),
    ],
)
def test_parser_strict_duplicate_numeric_ascii_and_canonical_handling(
    raw: bytes,
    reason: str,
) -> None:
    with pytest.raises(SourceEvidenceEd25519AttestationV4ValidationError, match=reason):
        parse_source_evidence_ed25519_attestation_v4(raw)


@pytest.mark.parametrize(
    "material",
    [
        {"float": 0.0},
        {"nan": float("nan")},
        {"infinity": float("inf")},
        {"integer": 2**100},
        {"bytes": b"not-json"},
        {"tuple": (1, 2)},
        {"unicode": "\u00e9"},
        {"": "empty-key"},
    ],
)
def test_python_material_types_and_numeric_edges_are_total_and_fail_closed(
    material: dict[str, object],
) -> None:
    with pytest.raises(SourceEvidenceEd25519AttestationV4ValidationError):
        _sign(material)


def test_depth_node_container_key_string_and_raw_byte_limits() -> None:
    nested: object = "leaf"
    for _index in range(MAX_SOURCE_EVIDENCE_ED25519_JSON_DEPTH + 1):
        nested = {"child": nested}
    with pytest.raises(
        SourceEvidenceEd25519AttestationV4ValidationError,
        match="json_depth_limit_exceeded",
    ):
        _sign(cast(dict[str, object], nested))

    node_heavy: dict[str, object] = {
        "groups": [
            [None] * 8 for _index in range((MAX_SOURCE_EVIDENCE_ED25519_JSON_NODES // 8) + 1)
        ]
    }
    with pytest.raises(
        SourceEvidenceEd25519AttestationV4ValidationError,
        match="json_node_limit_exceeded",
    ):
        _sign(node_heavy)

    resource_cases: tuple[tuple[dict[str, object], str], ...] = (
        (
            {"values": [None] * (MAX_SOURCE_EVIDENCE_ED25519_CONTAINER_ITEMS + 1)},
            "json_container_limit_exceeded",
        ),
        ({"k" * (MAX_SOURCE_EVIDENCE_ED25519_KEY_BYTES + 1): 1}, "json_key_invalid"),
        (
            {"value": "x" * (MAX_SOURCE_EVIDENCE_ED25519_STRING_BYTES + 1)},
            "json_string_limit_exceeded",
        ),
    )
    for material, reason in resource_cases:
        with pytest.raises(SourceEvidenceEd25519AttestationV4ValidationError, match=reason):
            _sign(material)

    with pytest.raises(
        SourceEvidenceEd25519AttestationV4ValidationError,
        match="json_input_invalid",
    ):
        parse_source_evidence_ed25519_attestation_v4(
            b"{" + b"x" * MAX_SOURCE_EVIDENCE_ED25519_ATTESTATION_BYTES + b"}"
        )


@pytest.mark.parametrize(
    "artifact",
    [
        None,
        0,
        True,
        {},
        [],
        bytearray(b"{}"),
        memoryview(b"{}"),
        object(),
    ],
)
def test_verifier_is_total_for_wrong_artifact_runtime_types(artifact: object) -> None:
    with pytest.raises(SourceEvidenceEd25519AttestationV4VerificationError):
        _verify(cast(Any, artifact))


@pytest.mark.parametrize(
    ("public_key", "fingerprint", "anchor_id", "material"),
    [
        (b"short", TEST_PUBLIC_KEY_SHA256, TEST_TRUST_ANCHOR_ID, _material()),
        (TEST_PUBLIC_KEY_BYTES, "A" * 64, TEST_TRUST_ANCHOR_ID, _material()),
        (TEST_PUBLIC_KEY_BYTES, TEST_PUBLIC_KEY_SHA256, "bad anchor space", _material()),
        (TEST_PUBLIC_KEY_BYTES, TEST_PUBLIC_KEY_SHA256, TEST_TRUST_ANCHOR_ID, {}),
    ],
)
def test_verifier_is_total_for_invalid_registry_expected_context(
    public_key: bytes,
    fingerprint: str,
    anchor_id: str,
    material: dict[str, object],
) -> None:
    with pytest.raises(
        SourceEvidenceEd25519AttestationV4VerificationError,
        match="expected_registry_context_invalid",
    ):
        _verify(
            _sign(),
            material,
            public_key_bytes=public_key,
            public_key_sha256=fingerprint,
            trust_anchor_id=anchor_id,
        )


def test_artifact_factory_is_not_an_authentication_bypass() -> None:
    artifact = _sign()
    with pytest.raises(
        SourceEvidenceEd25519AttestationV4ValidationError,
        match="factory_construction_required",
    ):
        SourceEvidenceEd25519AttestationV4(
            schema_version=artifact.schema_version,
            declared_trust_anchor_id=artifact.declared_trust_anchor_id,
            declared_public_key_sha256=artifact.declared_public_key_sha256,
            attested_material_sha256=artifact.attested_material_sha256,
            signature_hex=artifact.signature_hex,
            attestation_json=artifact.attestation_json,
            _construction_token=object(),
        )


def test_module_remains_unwired_and_has_no_runtime_or_network_io() -> None:
    repo = Path(__file__).resolve().parents[6]
    app_root = repo / "v2" / "backend" / "app"
    module_path = (
        app_root / "services" / "native_trainer" / "source_evidence_ed25519_attestation_v4.py"
    )
    imports = [
        path
        for path in app_root.rglob("*.py")
        if path != module_path
        and "source_evidence_ed25519_attestation_v4"
        in path.read_text(encoding="utf-8", errors="strict")
    ]
    assert imports == []

    module_source = module_path.read_text(encoding="utf-8", errors="strict")
    for forbidden in (
        "import redis",
        "import requests",
        "import httpx",
        "import socket",
        "import subprocess",
        "systemctl",
    ):
        assert forbidden not in module_source
    assert "TEST_PRIVATE_KEY_BYTES" not in module_source
    assert TEST_TRUST_ANCHOR_ID not in module_source
    assert "retained_key_resolver" not in module_source


def test_contract_constants_are_not_adaptive_market_thresholds() -> None:
    assert MAX_SOURCE_EVIDENCE_ED25519_ATTESTATION_BYTES == 64 * 1024
    assert MAX_SOURCE_EVIDENCE_ED25519_JSON_NODES == 512
    assert MAX_SOURCE_EVIDENCE_ED25519_JSON_DEPTH == 10
    assert attestation_module.MIN_SOURCE_EVIDENCE_ED25519_INTEGER == -(2**63)
    assert attestation_module.MAX_SOURCE_EVIDENCE_ED25519_INTEGER == 2**63 - 1
