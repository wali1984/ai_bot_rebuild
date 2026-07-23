from __future__ import annotations

import hashlib
import importlib
import json
import os
import struct
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    CAUSAL_COST_ORDERED_FEATURE_NAMES,
    CausalCostEvidenceV1Result,
)
from v2.backend.app.services.native_trainer.causal_expected_notional_policy_v1 import (
    CausalExpectedNotionalPolicyTokenV1,
    build_causal_expected_notional_policy_v1,
)
from v2.backend.app.services.native_trainer.paper_research_causal_cost_evidence_v1 import (
    PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_CLASSIFICATION,
    PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_DOWNSTREAM_STATUS,
    PAPER_RESEARCH_FEE_AUTHORITY_SCOPE,
    PAPER_RESEARCH_FEE_CONFIGURATION_AUTHENTICITY_SCOPE,
    PAPER_RESEARCH_FEE_SCHEDULE_MATERIAL_V1_SCHEMA_VERSION,
    PaperResearchCausalCostEvidenceV1IntegrityError,
    PaperResearchCausalCostEvidenceV1Result,
    PaperResearchCausalCostEvidenceV1ValidationError,
    assemble_paper_research_fee_schedule_attestation_v1,
    build_paper_research_causal_cost_evidence_v1,
    paper_research_fee_schedule_attestation_signing_bytes_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_enrichment_record_v1 import (
    ProfiledTrainingEnrichmentRecordV1Error,
)

_causal_support = importlib.import_module(
    "v2.backend.tests.unit.services.native_trainer.test_causal_cost_evidence_v1"
)
_profiled_enrichment = importlib.import_module(
    "v2.backend.app.services.native_trainer.profiled_training_enrichment_record_v1"
)
_notional_support = importlib.import_module(
    "v2.backend.tests.unit.services.native_trainer." "test_causal_expected_notional_policy_v1"
)

_PRIVATE_KEY_BYTES = b"\x19" * 32
_TRUST_ANCHOR_ID = "paper-research-fee-config-fixture-v1"
_SOURCE_DOCUMENT = (
    b'{"configuration":"public-paper-fee-schedule",' b'"revision":"fixture-2026-07-21"}'
)


def _public_key_bytes(private_key_bytes: bytes = _PRIVATE_KEY_BYTES) -> bytes:
    return (
        Ed25519PrivateKey.from_private_bytes(private_key_bytes)
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )


def _fee_material(
    *,
    source_document: bytes = _SOURCE_DOCUMENT,
    fee_decimal: str = "4.00000000",
    source_observed_at: str = "2026-07-21T11:59:59.700000Z",
    effective_at: str = "2026-07-01T00:00:00.000000Z",
    available_at: str = "2026-07-21T11:59:59.800000Z",
    expires_at: str = "2026-07-21T13:00:00.000000Z",
    account_specific_commission_authenticated: bool = False,
    upstream_exchange_signature_verified: bool = False,
) -> dict[str, object]:
    document_sha256 = hashlib.sha256(source_document).hexdigest()
    return {
        "schema_version": PAPER_RESEARCH_FEE_SCHEDULE_MATERIAL_V1_SCHEMA_VERSION,
        "evidence_classification": (
            "SIGNED_OPERATOR_CONFIGURED_PUBLIC_FEE_SCHEDULE_NOT_ACCOUNT_COMMISSION"
        ),
        "venue": "BINANCE",
        "market": "USD_M_PERPETUAL",
        "symbol": "BTCUSDT",
        "liquidity_role": "TAKER",
        "fee_semantics": "PER_SIDE_EXECUTION_FEE_NOT_ROUND_TRIP",
        "fee_unit": "BASIS_POINTS_DECIMAL_STRING",
        "taker_fee_bps_per_side_decimal": fee_decimal,
        "source_document_sha256": document_sha256,
        "source_document_byte_count": len(source_document),
        "source_document_media_type": "application/json",
        "source_document_locator": "public:operator-configured-fee-schedule",
        "source_revision": document_sha256,
        "source_observed_at": source_observed_at,
        "effective_at": effective_at,
        "available_at": available_at,
        "expires_at": expires_at,
        "authority_scope": PAPER_RESEARCH_FEE_AUTHORITY_SCOPE,
        "configuration_authenticity_scope": (PAPER_RESEARCH_FEE_CONFIGURATION_AUTHENTICITY_SCOPE),
        "account_specific_commission_authenticated": (account_specific_commission_authenticated),
        "upstream_exchange_signature_verified": upstream_exchange_signature_verified,
        "audit_only": True,
        "trainer_admission_authorized": False,
        "optimizer_execution_authorized": False,
        "checkpoint_write_authorized": False,
        "model_write_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "order_submission_authorized": False,
        "execution_authorized": False,
        "runtime_wired": False,
    }


def _inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    material: dict[str, object] | None = None,
    source_document: bytes = _SOURCE_DOCUMENT,
    private_key_bytes: bytes = _PRIVATE_KEY_BYTES,
    registry_public_key_bytes: bytes | None = None,
    signed_material: dict[str, object] | None = None,
    notional_token: CausalExpectedNotionalPolicyTokenV1 | None = None,
    pttl_ms: int = 60_000,
    payloads: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base = _causal_support._inputs(  # noqa: SLF001
        tmp_path,
        monkeypatch,
        pttl_ms=pttl_ms,
        payloads=payloads,
    )
    for name in (
        "fee_schedule_artifact_bytes",
        "fee_schedule_raw_response_bytes",
        "fee_schedule_receipt",
        "expected_notional_usd",
        "expected_notional_policy_artifact_bytes",
        "expected_notional_policy_receipt",
    ):
        base.pop(name)
    resolved_notional_token = notional_token or build_causal_expected_notional_policy_v1(
        atomic_capture=_notional_support._batch(  # noqa: SLF001
            _notional_support._raw_status(_notional_support._status())  # noqa: SLF001
        ),
        source_payload_store=base["source_payload_store"],
        symbol="BTCUSDT",
        feature_snapshot_identity=_causal_support._SNAPSHOT_IDENTITY,  # noqa: SLF001
        feature_snapshot_decision_time=datetime(
            2026,
            7,
            21,
            12,
            0,
            1,
            tzinfo=UTC,
        ),
    )
    resolved_material = material or _fee_material(source_document=source_document)
    signer_public_key = _public_key_bytes(private_key_bytes)
    signer_public_key_sha256 = hashlib.sha256(signer_public_key).hexdigest()
    material_to_sign = signed_material or resolved_material
    signing_bytes = paper_research_fee_schedule_attestation_signing_bytes_v1(
        fee_schedule_material=material_to_sign,
        declared_trust_anchor_id=_TRUST_ANCHOR_ID,
        declared_public_key_sha256=signer_public_key_sha256,
    )
    signature = Ed25519PrivateKey.from_private_bytes(private_key_bytes).sign(signing_bytes)
    attestation = assemble_paper_research_fee_schedule_attestation_v1(
        fee_schedule_material=material_to_sign,
        declared_trust_anchor_id=_TRUST_ANCHOR_ID,
        declared_public_key_sha256=signer_public_key_sha256,
        signature_bytes=signature,
    )
    public_key = registry_public_key_bytes or signer_public_key
    return {
        **base,
        "fee_schedule_source_document_bytes": source_document,
        "fee_schedule_signed_attestation": attestation,
        "fee_schedule_material": resolved_material,
        "fee_schedule_registry_public_key_bytes": public_key,
        "fee_schedule_registry_public_key_sha256": hashlib.sha256(public_key).hexdigest(),
        "fee_schedule_expected_trust_anchor_id": _TRUST_ANCHOR_ID,
        "fee_schedule_expected_source_revision": hashlib.sha256(source_document).hexdigest(),
        "expected_notional_policy": resolved_notional_token,
    }


def test_builds_separately_typed_signed_research_cost_without_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = build_paper_research_causal_cost_evidence_v1(**_inputs(tmp_path, monkeypatch))

    assert type(result) is PaperResearchCausalCostEvidenceV1Result
    assert not isinstance(result, CausalCostEvidenceV1Result)
    assert result.ordered_values[0] == pytest.approx(4.0)
    assert result.ordered_values[1] > 0.0
    assert result.ordered_values[2] > 0.0
    assert result.ordered_values[3] == pytest.approx(1.0)
    contract = result.contract
    assert contract["ordered_feature_names"] == list(CAUSAL_COST_ORDERED_FEATURE_NAMES)
    assert contract["evidence_classification"] == (
        PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_CLASSIFICATION
    )
    assert contract["downstream_status"] == (
        PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_DOWNSTREAM_STATUS
    )
    assert contract["fee_source"]["configuration_authenticity_verified"] is True
    assert contract["account_specific_commission_authenticated"] is False
    assert contract["profiled_account_lane_compatible"] is False
    assert contract["research_cost_components_complete"] is True
    assert contract["source_cas_object_count"] == len(result._exact_objects) - 1  # noqa: SLF001
    assert (
        contract["source_cas_object_inventory_sha256"]
        == hashlib.sha256(
            json.dumps(
                contract["source_cas_object_inventory"],
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
        ).hexdigest()
    )
    assert set(contract["authorization"].values()) == {False}
    assert all(
        set(receipt["authorization"].values()) == {False}
        and receipt["feature_role"] == "RESEARCH_LABEL_ONLY_AUXILIARY_NOT_MODEL_INPUT"
        for receipt in result.ordered_receipts
    )


def test_profiled_enrichment_rejects_research_result_exact_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = build_paper_research_causal_cost_evidence_v1(**_inputs(tmp_path, monkeypatch))

    with pytest.raises(
        ProfiledTrainingEnrichmentRecordV1Error,
        match="EXACT_COST_FACTORY_RESULT_REQUIRED",
    ):
        _profiled_enrichment._causal_contract(result)  # noqa: SLF001


def test_rejects_untrusted_key_signature_and_material_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrong_key = _public_key_bytes(b"\x23" * 32)
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1IntegrityError,
        match="ATTESTATION_",
    ):
        build_paper_research_causal_cost_evidence_v1(
            **_inputs(
                tmp_path / "wrong-key",
                monkeypatch,
                registry_public_key_bytes=wrong_key,
            )
        )

    material = _fee_material(fee_decimal="5.00000000")
    signed_material = _fee_material(fee_decimal="4.00000000")
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1IntegrityError,
        match="ATTESTATION_",
    ):
        build_paper_research_causal_cost_evidence_v1(
            **_inputs(
                tmp_path / "material",
                monkeypatch,
                material=material,
                signed_material=signed_material,
            )
        )


def test_rejects_signature_encoding_canonicalization_and_fingerprint_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _inputs(tmp_path / "signature", monkeypatch)
    envelope = json.loads(values["fee_schedule_signed_attestation"])
    original = envelope["signature_hex"]
    envelope["signature_hex"] = ("0" if original[0] != "0" else "1") + original[1:]
    values["fee_schedule_signed_attestation"] = json.dumps(
        envelope,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1IntegrityError,
        match="ATTESTATION_UNVERIFIED",
    ):
        build_paper_research_causal_cost_evidence_v1(**values)

    values = _inputs(tmp_path / "noncanonical", monkeypatch)
    values["fee_schedule_signed_attestation"] = b" " + values["fee_schedule_signed_attestation"]
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1ValidationError,
        match="NOT_EXACT_CANONICAL_JSON",
    ):
        build_paper_research_causal_cost_evidence_v1(**values)

    values = _inputs(tmp_path / "fingerprint", monkeypatch)
    values["fee_schedule_registry_public_key_sha256"] = "0" * 64
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1IntegrityError,
        match="PUBLIC_KEY_FINGERPRINT_MISMATCH",
    ):
        build_paper_research_causal_cost_evidence_v1(**values)

    values = _inputs(tmp_path / "revision", monkeypatch)
    values["fee_schedule_expected_source_revision"] = "f" * 64
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1ValidationError,
        match="SOURCE_DOCUMENT_BINDING_INVALID",
    ):
        build_paper_research_causal_cost_evidence_v1(**values)


def test_rejects_source_bytes_future_expiry_and_account_authority_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = _fee_material()
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1ValidationError,
        match="SOURCE_DOCUMENT_BINDING_INVALID",
    ):
        build_paper_research_causal_cost_evidence_v1(
            **_inputs(
                tmp_path / "source-bytes",
                monkeypatch,
                material=material,
                signed_material=material,
                source_document=_SOURCE_DOCUMENT + b"x",
            )
        )

    future = _fee_material(available_at="2026-07-21T12:00:02.000000Z")
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1ValidationError,
        match="CLOCK_OR_EXPIRY_INVALID",
    ):
        build_paper_research_causal_cost_evidence_v1(
            **_inputs(tmp_path / "future", monkeypatch, material=future)
        )

    expired = _fee_material(expires_at="2026-07-21T12:00:01.000000Z")
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1ValidationError,
        match="CLOCK_OR_EXPIRY_INVALID",
    ):
        build_paper_research_causal_cost_evidence_v1(
            **_inputs(tmp_path / "expired", monkeypatch, material=expired)
        )

    overclaim = _fee_material(account_specific_commission_authenticated=True)
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1ValidationError,
        match="IDENTITY_OR_AUTHORITY_INVALID",
    ):
        build_paper_research_causal_cost_evidence_v1(
            **_inputs(tmp_path / "overclaim", monkeypatch, material=overclaim)
        )

    type_confusion = _fee_material()
    type_confusion["account_specific_commission_authenticated"] = 0
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1ValidationError,
        match="IDENTITY_OR_AUTHORITY_INVALID",
    ):
        build_paper_research_causal_cost_evidence_v1(
            **_inputs(
                tmp_path / "type-confusion",
                monkeypatch,
                material=type_confusion,
            )
        )


def test_rejects_invalid_causal_market_expiry_future_clock_and_notional(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1ValidationError,
        match="PERSISTED_EXPIRY",
    ):
        build_paper_research_causal_cost_evidence_v1(
            **_inputs(tmp_path / "pttl", monkeypatch, pttl_ms=0)
        )

    payloads = _causal_support._market_payloads(monkeypatch)  # noqa: SLF001
    payloads["mark"]["available_at"] = "2026-07-21T12:00:02.000Z"
    payloads["mark"]["generated_at"] = "2026-07-21T12:00:02.000Z"
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1ValidationError,
        match="CLOCK_ORDER",
    ):
        build_paper_research_causal_cost_evidence_v1(
            **_inputs(tmp_path / "future-mark", monkeypatch, payloads=payloads)
        )

    values = _inputs(tmp_path / "notional", monkeypatch)
    values["expected_notional_policy"] = replace(
        values["expected_notional_policy"],
        expected_notional_usd=(values["expected_notional_policy"].expected_notional_usd + 1.0),
    )
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1IntegrityError,
        match="NOTIONAL_TOKEN_INTEGRITY_INVALID",
    ):
        build_paper_research_causal_cost_evidence_v1(**values)


def test_fresh_property_reverifies_signature_and_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = build_paper_research_causal_cost_evidence_v1(**_inputs(tmp_path, monkeypatch))
    wrong_key = _public_key_bytes(b"\x31" * 32)
    forged_key_result = replace(
        result,
        _registry_public_key_bytes=wrong_key,
        _registry_public_key_sha256=hashlib.sha256(wrong_key).hexdigest(),
    )
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1IntegrityError,
        match="FACTORY_SEAL_INVALID",
    ):
        _ = forged_key_result.contract

    address, payload = result._exact_objects[0]  # noqa: SLF001
    path = result._store.root_path / address.relative_path  # noqa: SLF001
    os.chmod(path, 0o600)
    path.write_bytes(b"x" * len(payload))
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1IntegrityError,
        match="CAS_READBACK",
    ):
        _ = result.contract


def test_result_scalar_substitution_cannot_validate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = build_paper_research_causal_cost_evidence_v1(**_inputs(tmp_path, monkeypatch))
    forged = replace(
        result,
        ordered_values=(result.ordered_values[0] + 1.0, *result.ordered_values[1:]),
    )
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1IntegrityError,
        match="FACTORY_SEAL_INVALID",
    ):
        _ = forged.contract


def test_result_cannot_omit_contract_bound_source_cas_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = build_paper_research_causal_cost_evidence_v1(**_inputs(tmp_path, monkeypatch))
    artifact_bytes = result.artifact_json.encode("ascii")
    forged = replace(
        result,
        _exact_objects=((result.artifact_address, artifact_bytes),),
    )

    with pytest.raises(
        PaperResearchCausalCostEvidenceV1IntegrityError,
        match="FACTORY_SEAL_INVALID",
    ):
        _ = forged.contract


def test_coherent_result_artifact_replacement_cannot_bypass_factory_seal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = build_paper_research_causal_cost_evidence_v1(**_inputs(tmp_path, monkeypatch))
    contract = result.contract
    forged_values = list(contract["ordered_values"])
    forged_values[0] += 1.0
    scalar_bytes = struct.pack("!f", forged_values[0])
    forged_receipt = contract["ordered_receipts"][0]
    forged_receipt["value"] = forged_values[0]
    forged_receipt["value_float32_be_hex"] = scalar_bytes.hex()
    forged_receipt["payload_sha256"] = hashlib.sha256(scalar_bytes).hexdigest()
    receipt_material = {
        key: value for key, value in forged_receipt.items() if key != "receipt_sha256"
    }
    forged_receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(
            receipt_material,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    forged_receipt_sha256s = [receipt["receipt_sha256"] for receipt in contract["ordered_receipts"]]
    contract["ordered_values"] = forged_values
    contract["ordered_receipt_sha256s"] = forged_receipt_sha256s
    contract_material = {
        key: value
        for key, value in contract.items()
        if key not in {"evidence_id", "contract_material_sha256"}
    }
    contract_material_sha256 = hashlib.sha256(
        json.dumps(
            contract_material,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    contract["contract_material_sha256"] = contract_material_sha256
    contract["evidence_id"] = f"paper_research_causal_cost_evidence_v1_{contract_material_sha256}"
    artifact_bytes = json.dumps(
        contract,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    artifact_address = result._store.put(  # noqa: SLF001
        artifact_bytes,
        expected_sha256=hashlib.sha256(artifact_bytes).hexdigest(),
        expected_byte_count=len(artifact_bytes),
    )
    forged = replace(
        result,
        artifact_sha256=artifact_address.payload_sha256,
        artifact_json=artifact_bytes.decode("ascii"),
        artifact_address=artifact_address,
        ordered_values=tuple(forged_values),
        ordered_receipt_sha256s=tuple(forged_receipt_sha256s),
        _exact_objects=(*result._exact_objects[:-1], (artifact_address, artifact_bytes)),  # noqa: SLF001
    )

    with pytest.raises(
        PaperResearchCausalCostEvidenceV1IntegrityError,
        match="FACTORY_SEAL_INVALID",
    ):
        _ = forged.contract


def test_fee_material_is_integer_string_only_for_signature_stability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = _fee_material()
    invalid["taker_fee_bps_per_side_decimal"] = 4.0
    with pytest.raises(
        PaperResearchCausalCostEvidenceV1ValidationError,
        match="FEE_DECIMAL_INVALID",
    ):
        build_paper_research_causal_cost_evidence_v1(
            **_inputs(
                tmp_path,
                monkeypatch,
                material=invalid,
                signed_material=_fee_material(),
            )
        )

    # The signed material remains strict canonical JSON with no binary-float
    # interpretation at the signature boundary.
    valid = _fee_material(fee_decimal="0.00000001")
    encoded = json.dumps(valid, allow_nan=False, sort_keys=True)
    assert '"taker_fee_bps_per_side_decimal": "0.00000001"' in encoded


def test_signed_zero_fee_is_evidence_not_a_hardcoded_positive_floor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = _fee_material(fee_decimal="0")
    result = build_paper_research_causal_cost_evidence_v1(
        **_inputs(tmp_path, monkeypatch, material=material)
    )

    assert result.ordered_values[0] == 0.0
    assert result.contract["no_static_fallback_or_floor"] is True


def test_research_cost_primitive_remains_unwired_from_application_runtime() -> None:
    repo = Path(__file__).resolve().parents[6]
    app_root = repo / "v2" / "backend" / "app"
    module_path = (
        app_root / "services" / "native_trainer" / "paper_research_causal_cost_evidence_v1.py"
    )
    imports = [
        path
        for path in app_root.rglob("*.py")
        if path != module_path
        and "paper_research_causal_cost_evidence_v1"
        in path.read_text(encoding="utf-8", errors="strict")
    ]
    assert imports == []
