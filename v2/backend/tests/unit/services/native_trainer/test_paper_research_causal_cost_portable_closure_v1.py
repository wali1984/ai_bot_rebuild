from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer import (
    paper_research_causal_cost_portable_closure_v1 as portable,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
)
from v2.backend.app.services.native_trainer.paper_research_causal_cost_evidence_v1 import (  # noqa: E501
    build_paper_research_causal_cost_evidence_v1,
)
from v2.backend.app.services.native_trainer.paper_research_causal_cost_portable_closure_v1 import (  # noqa: E501
    PAPER_RESEARCH_CAUSAL_COST_PORTABLE_CLOSURE_V1_CLASSIFICATION,
    PAPER_RESEARCH_CAUSAL_COST_PORTABLE_CLOSURE_V1_SCHEMA_VERSION,
    PaperResearchCausalCostPortableClosureV1IntegrityError,
    PaperResearchCausalCostPortableClosureV1ValidationError,
    open_paper_research_causal_cost_portable_closure_v1,
    publish_paper_research_causal_cost_portable_closure_v1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_paper_research_causal_cost_evidence_v1 as cost_support,
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _cost(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN202
    return build_paper_research_causal_cost_evidence_v1(
        **cost_support._inputs(tmp_path, monkeypatch)  # noqa: SLF001
    )


def _stored_objects(store: ImmutableSourcePayloadStore) -> tuple[Path, ...]:
    return tuple(
        path
        for path in (store.root_path / "sha256").glob("*/*")
        if path.is_file()
    )


def _publish_forged_manifest(
    store: ImmutableSourcePayloadStore,
    manifest: dict[str, object],
) -> SourcePayloadAddress:
    material = {
        key: value
        for key, value in manifest.items()
        if key != "closure_material_sha256"
    }
    manifest["closure_material_sha256"] = _sha256(material)
    payload = _canonical_bytes(manifest)
    return store.put(
        payload,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        expected_byte_count=len(payload),
    )


def test_publishes_complete_closure_and_reopens_in_fresh_process_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cost = _cost(tmp_path / "source", monkeypatch)
    root = tmp_path / "portable"
    store = ImmutableSourcePayloadStore(root)

    result = publish_paper_research_causal_cost_portable_closure_v1(
        cost_evidence=cost,
        store=store,
    )
    manifest = result.manifest

    assert manifest["schema_version"] == (
        PAPER_RESEARCH_CAUSAL_COST_PORTABLE_CLOSURE_V1_SCHEMA_VERSION
    )
    assert manifest["classification"] == (
        PAPER_RESEARCH_CAUSAL_COST_PORTABLE_CLOSURE_V1_CLASSIFICATION
    )
    assert manifest["portable_source_closure_complete"] is True
    assert manifest["restart_reopen_supported"] is True
    assert manifest["research_only"] is True
    assert manifest["authorization"] == {
        "trainer_admission_authorized": False,
        "optimizer_execution_authorized": False,
        "checkpoint_write_authorized": False,
        "model_write_authorized": False,
        "calibration_input_authorized": False,
        "prediction_authorized": False,
        "serving_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "exchange_access_authorized": False,
        "deployment_authorized": False,
        "order_submission_authorized": False,
        "execution_authorized": False,
        "runtime_wired": False,
    }
    assert result.source_cas_object_count == 13
    assert result.complete_cas_object_count == 15
    assert len(manifest["source_cas_object_inventory"]) == 13
    assert len(manifest["complete_cas_object_inventory"]) == 15
    assert manifest["complete_cas_object_inventory"][:-2] == manifest[
        "source_cas_object_inventory"
    ]
    assert manifest["complete_cas_object_inventory"][-2] == manifest[
        "cost_evidence_artifact_cas_address"
    ]
    assert manifest["complete_cas_object_inventory"][-1] == manifest[
        "registry_public_key_cas_address"
    ]
    assert len(_stored_objects(store)) == 16
    assert result.cost_contract == cost.contract
    assert len(result.ordered_receipts) == 4
    assert result.ordered_values == cost.ordered_values
    assert result.ordered_receipt_sha256s == cost.ordered_receipt_sha256s

    reopened = open_paper_research_causal_cost_portable_closure_v1(
        store=ImmutableSourcePayloadStore(root),
        closure_address=result.closure_address,
    )
    assert reopened.manifest == manifest
    assert reopened.cost_contract == cost.contract
    assert reopened.ordered_values == cost.ordered_values

    repo = Path(__file__).resolve().parents[6]
    restart_script = """
import json
import sys
from pathlib import Path
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
)
from v2.backend.app.services.native_trainer.paper_research_causal_cost_portable_closure_v1 import (
    open_paper_research_causal_cost_portable_closure_v1,
)
address = SourcePayloadAddress(
    schema_version=sys.argv[2],
    payload_sha256=sys.argv[3],
    payload_byte_count=int(sys.argv[4]),
    relative_path=sys.argv[5],
)
opened = open_paper_research_causal_cost_portable_closure_v1(
    store=ImmutableSourcePayloadStore(Path(sys.argv[1])),
    closure_address=address,
)
print(json.dumps(
    {
        "source": opened.source_cas_object_count,
        "complete": opened.complete_cas_object_count,
        "receipts": len(opened.ordered_receipts),
    },
    sort_keys=True,
))
"""
    restarted = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-c",
            restart_script,
            str(root),
            result.closure_address.schema_version,
            result.closure_address.payload_sha256,
            str(result.closure_address.payload_byte_count),
            result.closure_address.relative_path,
        ],
        cwd=repo,
        env={**os.environ, "PYTHONPATH": str(repo)},
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(restarted.stdout) == {
        "complete": 15,
        "receipts": 4,
        "source": 13,
    }

    idempotent = publish_paper_research_causal_cost_portable_closure_v1(
        cost_evidence=cost,
        store=ImmutableSourcePayloadStore(root),
    )
    assert idempotent.closure_address == result.closure_address
    assert len(_stored_objects(store)) == 16


def test_rejects_nonfactory_cost_before_target_store_write(tmp_path: Path) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "portable")

    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1ValidationError,
        match="PORTABLE_COST_CLOSURE_EXACT_COST_RESULT_REQUIRED",
    ):
        publish_paper_research_causal_cost_portable_closure_v1(
            cost_evidence={},
            store=store,
        )
    assert _stored_objects(store) == ()


def test_late_source_result_revalidation_failures_precede_target_store_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cost = _cost(tmp_path / "source", monkeypatch)
    target = ImmutableSourcePayloadStore(tmp_path / "portable")
    malformed_results = (
        replace(cost, _registry_public_key_bytes=b"\x41" * 32),
        replace(cost, _exact_objects=cost._exact_objects[:-1]),  # noqa: SLF001
        replace(
            cost,
            _notional_policy_token=replace(
                cost._notional_policy_token,  # noqa: SLF001
                expected_notional_usd=(
                    cost._notional_policy_token.expected_notional_usd + 1.0  # noqa: SLF001
                ),
            ),
        ),
    )
    for malformed in malformed_results:
        with pytest.raises(
            PaperResearchCausalCostPortableClosureV1IntegrityError,
            match="PORTABLE_COST_CLOSURE_SOURCE_RESULT_REVALIDATION_FAILED",
        ):
            publish_paper_research_causal_cost_portable_closure_v1(
                cost_evidence=malformed,
                store=target,
            )
        assert _stored_objects(target) == ()


def test_final_portable_preflight_failure_precedes_target_store_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cost = _cost(tmp_path / "source", monkeypatch)
    target = ImmutableSourcePayloadStore(tmp_path / "portable")

    def fail_preflight(**_kwargs):  # noqa: ANN003, ANN202
        raise PaperResearchCausalCostPortableClosureV1IntegrityError(
            "INJECTED_PORTABLE_PREFLIGHT_FAILURE"
        )

    monkeypatch.setattr(portable, "_revalidated_cost_contract", fail_preflight)
    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1IntegrityError,
        match="INJECTED_PORTABLE_PREFLIGHT_FAILURE",
    ):
        publish_paper_research_causal_cost_portable_closure_v1(
            cost_evidence=cost,
            store=target,
        )
    assert _stored_objects(target) == ()


def test_restart_open_rejects_missing_inventory_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cost = _cost(tmp_path / "source", monkeypatch)
    root = tmp_path / "portable"
    store = ImmutableSourcePayloadStore(root)
    result = publish_paper_research_causal_cost_portable_closure_v1(
        cost_evidence=cost,
        store=store,
    )
    for binding in result.manifest["complete_cas_object_inventory"]:
        path = root / binding["relative_path"]
        payload = path.read_bytes()
        path.unlink()
        with pytest.raises(
            PaperResearchCausalCostPortableClosureV1IntegrityError,
            match="PORTABLE_COST_CLOSURE_REOPEN_FAILED",
        ):
            open_paper_research_causal_cost_portable_closure_v1(
                store=ImmutableSourcePayloadStore(root),
                closure_address=result.closure_address,
            )
        restored = store.put(
            payload,
            expected_sha256=binding["payload_sha256"],
            expected_byte_count=binding["payload_byte_count"],
        )
        assert restored.relative_path == binding["relative_path"]


def test_restart_open_rejects_outer_fee_trust_key_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cost = _cost(tmp_path / "source", monkeypatch)
    store = ImmutableSourcePayloadStore(tmp_path / "portable")
    result = publish_paper_research_causal_cost_portable_closure_v1(
        cost_evidence=cost,
        store=store,
    )
    forged = result.manifest
    wrong_key = b"\x5a" * 32
    wrong_address = store.put(
        wrong_key,
        expected_sha256=hashlib.sha256(wrong_key).hexdigest(),
        expected_byte_count=len(wrong_key),
    )
    wrong_mapping = {
        "schema_version": wrong_address.schema_version,
        "payload_sha256": wrong_address.payload_sha256,
        "payload_byte_count": wrong_address.payload_byte_count,
        "relative_path": wrong_address.relative_path,
    }
    key_index = forged["complete_cas_object_inventory"].index(
        forged["registry_public_key_cas_address"]
    )
    forged["registry_public_key_sha256"] = wrong_address.payload_sha256
    forged["registry_public_key_cas_address"] = wrong_mapping
    forged["complete_cas_object_inventory"][key_index] = wrong_mapping
    forged["complete_cas_object_inventory_sha256"] = _sha256(
        forged["complete_cas_object_inventory"]
    )
    forged_address = _publish_forged_manifest(store, forged)

    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1IntegrityError,
        match="PORTABLE_COST_CLOSURE_FEE_TRUST_BINDING_INVALID",
    ):
        open_paper_research_causal_cost_portable_closure_v1(
            store=store,
            closure_address=forged_address,
        )


def test_restart_open_rejects_notional_proof_or_source_inventory_omission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cost = _cost(tmp_path / "source", monkeypatch)
    store = ImmutableSourcePayloadStore(tmp_path / "portable")
    result = publish_paper_research_causal_cost_portable_closure_v1(
        cost_evidence=cost,
        store=store,
    )

    forged_notional = result.manifest
    forged_notional["notional_policy_contract"]["read_only"] = False
    forged_notional["notional_policy_contract_sha256"] = _sha256(
        forged_notional["notional_policy_contract"]
    )
    forged_notional_address = _publish_forged_manifest(store, forged_notional)
    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1IntegrityError,
        match="PORTABLE_COST_CLOSURE_NOTIONAL_CONTRACT_INVALID",
    ):
        open_paper_research_causal_cost_portable_closure_v1(
            store=store,
            closure_address=forged_notional_address,
        )

    forged_inventory = result.manifest
    del forged_inventory["source_cas_object_inventory"][0]
    del forged_inventory["complete_cas_object_inventory"][0]
    forged_inventory["source_cas_object_count"] -= 1
    forged_inventory["complete_cas_object_count"] -= 1
    forged_inventory["source_cas_object_inventory_sha256"] = _sha256(
        forged_inventory["source_cas_object_inventory"]
    )
    forged_inventory["complete_cas_object_inventory_sha256"] = _sha256(
        forged_inventory["complete_cas_object_inventory"]
    )
    forged_inventory_address = _publish_forged_manifest(store, forged_inventory)
    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1IntegrityError,
        match="PORTABLE_COST_CLOSURE_OBJECT_COUNT_INVALID",
    ):
        open_paper_research_causal_cost_portable_closure_v1(
            store=store,
            closure_address=forged_inventory_address,
        )

    oversized = result.manifest
    oversized_binding = dict(oversized["source_cas_object_inventory"][0])
    oversized_binding["payload_byte_count"] = 8 * 1024 * 1024 + 1
    oversized["source_cas_object_inventory"][0] = oversized_binding
    oversized["complete_cas_object_inventory"][0] = oversized_binding
    oversized["source_cas_object_inventory_sha256"] = _sha256(
        oversized["source_cas_object_inventory"]
    )
    oversized["complete_cas_object_inventory_sha256"] = _sha256(
        oversized["complete_cas_object_inventory"]
    )
    oversized_address = _publish_forged_manifest(store, oversized)
    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1IntegrityError,
        match="PORTABLE_COST_CLOSURE_OBJECT_SIZE_INVALID",
    ):
        open_paper_research_causal_cost_portable_closure_v1(
            store=store,
            closure_address=oversized_address,
        )


def test_restart_open_rejects_manifest_field_injection_or_numeric_overflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cost = _cost(tmp_path / "source", monkeypatch)
    store = ImmutableSourcePayloadStore(tmp_path / "portable")
    result = publish_paper_research_causal_cost_portable_closure_v1(
        cost_evidence=cost,
        store=store,
    )

    injected = result.manifest
    injected["runtime_wired"] = True
    injected_address = _publish_forged_manifest(store, injected)
    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1IntegrityError,
        match="PORTABLE_COST_CLOSURE_MANIFEST_FIELDS_INVALID",
    ):
        open_paper_research_causal_cost_portable_closure_v1(
            store=store,
            closure_address=injected_address,
        )

    numeric_authority = result.manifest
    numeric_authority["authorization"] = {
        name: 0 for name in numeric_authority["authorization"]
    }
    numeric_authority_address = _publish_forged_manifest(
        store, numeric_authority
    )
    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1IntegrityError,
        match="PORTABLE_COST_CLOSURE_MANIFEST_AUTHORIZATION_INVALID",
    ):
        open_paper_research_causal_cost_portable_closure_v1(
            store=store,
            closure_address=numeric_authority_address,
        )

    numeric_count = result.manifest
    numeric_count["source_cas_object_count"] = 13.0
    numeric_count_address = _publish_forged_manifest(store, numeric_count)
    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1IntegrityError,
        match="PORTABLE_COST_CLOSURE_OBJECT_COUNT_INVALID",
    ):
        open_paper_research_causal_cost_portable_closure_v1(
            store=store,
            closure_address=numeric_count_address,
        )

    overflow_manifest = result.manifest
    overflow_contract = result.cost_contract
    overflow_contract["market_sources"]["orderbook_depth"][
        "redis_pttl_ms"
    ] = 10**100
    contract_material = {
        key: value
        for key, value in overflow_contract.items()
        if key not in {"evidence_id", "contract_material_sha256"}
    }
    contract_material_sha256 = _sha256(contract_material)
    overflow_contract["contract_material_sha256"] = contract_material_sha256
    overflow_contract["evidence_id"] = (
        f"paper_research_causal_cost_evidence_v1_{contract_material_sha256}"
    )
    overflow_cost_bytes = _canonical_bytes(overflow_contract)
    overflow_cost_address = store.put(
        overflow_cost_bytes,
        expected_sha256=hashlib.sha256(overflow_cost_bytes).hexdigest(),
        expected_byte_count=len(overflow_cost_bytes),
    )
    overflow_cost_mapping = {
        "schema_version": overflow_cost_address.schema_version,
        "payload_sha256": overflow_cost_address.payload_sha256,
        "payload_byte_count": overflow_cost_address.payload_byte_count,
        "relative_path": overflow_cost_address.relative_path,
    }
    cost_index = overflow_manifest["complete_cas_object_inventory"].index(
        overflow_manifest["cost_evidence_artifact_cas_address"]
    )
    overflow_manifest["cost_evidence_artifact_sha256"] = (
        overflow_cost_address.payload_sha256
    )
    overflow_manifest["cost_evidence_artifact_cas_address"] = (
        overflow_cost_mapping
    )
    overflow_manifest["cost_contract_material_sha256"] = (
        contract_material_sha256
    )
    overflow_manifest["complete_cas_object_inventory"][cost_index] = (
        overflow_cost_mapping
    )
    overflow_manifest["complete_cas_object_inventory_sha256"] = _sha256(
        overflow_manifest["complete_cas_object_inventory"]
    )
    overflow_address = _publish_forged_manifest(store, overflow_manifest)
    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1IntegrityError,
        match="PORTABLE_COST_CLOSURE_MARKET_SOURCE_INVALID",
    ):
        open_paper_research_causal_cost_portable_closure_v1(
            store=store,
            closure_address=overflow_address,
        )


def test_portable_notional_rejects_numeric_boolean_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cost = _cost(tmp_path / "source", monkeypatch)
    store = ImmutableSourcePayloadStore(tmp_path / "portable")
    result = publish_paper_research_causal_cost_portable_closure_v1(
        cost_evidence=cost,
        store=store,
    )
    notional = result.manifest["notional_policy_contract"]
    source_receipt = notional["source_read_receipt"]
    source_receipt["trainer_authority"] = 0
    receipt_material = {
        key: value
        for key, value in source_receipt.items()
        if key != "receipt_sha256"
    }
    source_receipt["receipt_sha256"] = _sha256(receipt_material)
    receipt_bytes = _canonical_bytes(source_receipt)
    receipt_address = store.put(
        receipt_bytes,
        expected_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
        expected_byte_count=len(receipt_bytes),
    )
    notional["source_read_receipt_cas_address"] = {
        "schema_version": receipt_address.schema_version,
        "payload_sha256": receipt_address.payload_sha256,
        "payload_byte_count": receipt_address.payload_byte_count,
        "relative_path": receipt_address.relative_path,
    }

    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1IntegrityError,
        match="PORTABLE_COST_CLOSURE_NOTIONAL_CONTRACT_INVALID",
    ):
        portable._portable_notional_contract(notional, store=store)  # noqa: SLF001


def test_result_rejects_public_binding_or_factory_seal_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cost = _cost(tmp_path / "source", monkeypatch)
    result = publish_paper_research_causal_cost_portable_closure_v1(
        cost_evidence=cost,
        store=ImmutableSourcePayloadStore(tmp_path / "portable"),
    )

    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1IntegrityError,
        match="PORTABLE_COST_CLOSURE_RESULT_BINDING_INVALID",
    ):
        _ = replace(
            result,
            complete_cas_object_count=result.complete_cas_object_count + 1,
        ).manifest
    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1IntegrityError,
        match="PORTABLE_COST_CLOSURE_FACTORY_CONSTRUCTION_REQUIRED",
    ):
        _ = replace(result, _factory_seal=None).manifest
    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1IntegrityError,
        match="PORTABLE_COST_CLOSURE_FACTORY_CONSTRUCTION_REQUIRED",
    ):
        _ = replace(result, source_cas_object_count=13.0).manifest
    with pytest.raises(
        PaperResearchCausalCostPortableClosureV1IntegrityError,
        match="PORTABLE_COST_CLOSURE_FACTORY_CONSTRUCTION_REQUIRED",
    ):
        _ = replace(
            result,
            ordered_values=(False, *result.ordered_values[1:]),
        ).manifest
