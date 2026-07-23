from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    CAUSAL_COST_ORDERED_FEATURE_NAMES,
)
from v2.backend.app.services.native_trainer.causal_expected_notional_policy_v1 import (
    build_causal_expected_notional_policy_v1,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.paper_research_causal_cost_evidence_v1 import (  # noqa: E501
    build_paper_research_causal_cost_evidence_v1,
)
from v2.backend.app.services.native_trainer.profiled_research_shadow_hypothesis_v1 import (  # noqa: E501
    PROFILED_RESEARCH_DECISION_REFERENCE_SOURCE,
    PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1_CLASSIFICATION,
    PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1_SCHEMA_VERSION,
    ProfiledResearchShadowHypothesisV1IntegrityError,
    ProfiledResearchShadowHypothesisV1ValidationError,
    build_profiled_research_shadow_hypothesis_v1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_locally_authenticated_profiled_research_inference_v1 as inference_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_paper_research_causal_cost_evidence_v1 as cost_support,
)


@pytest.fixture(autouse=True)
def _clear_inference_order_registry():  # noqa: ANN201
    inference = inference_support.inference
    with inference._PROCESS_SOURCE_ORDER_LOCK:  # noqa: SLF001
        inference._PROCESS_LAST_SOURCE_DECISION_BY_CANDIDATE_PAIR.clear()  # noqa: SLF001
    yield
    with inference._PROCESS_SOURCE_ORDER_LOCK:  # noqa: SLF001
        inference._PROCESS_LAST_SOURCE_DECISION_BY_CANDIDATE_PAIR.clear()  # noqa: SLF001


def _raw_v2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):  # noqa: ANN202
    handle = inference_support._open_handle(  # noqa: SLF001
        monkeypatch,
        tmp_path / "handle",
    )
    evidence = inference_support._build_evidence(  # noqa: SLF001
        monkeypatch,
        tmp_path / "evidence",
    )
    clocks = iter(
        (
            "2026-07-21T13:00:00.000000Z",
            "2026-07-21T13:00:01.000000Z",
        )
    )
    monkeypatch.setattr(
        inference_support.inference,
        "_utc_iso",
        lambda: next(clocks),
    )
    return handle.infer_profiled_record_v2(
        record=evidence.record,
        transform_result=evidence.transformed,
        capture_set_contract=evidence.contract,
        capture_set_store=evidence.capture_store,
        artifact_store=evidence.artifact_store,
        source_provenance_ledger=evidence.source_ledger,
        source_provenance_entries=evidence.source_entries,
    )


def _cost_for_raw(
    raw,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):  # noqa: ANN001, ANN202
    values = cost_support._inputs(tmp_path, monkeypatch)  # noqa: SLF001
    notional_support = cost_support._notional_support  # noqa: SLF001
    token = build_causal_expected_notional_policy_v1(
        atomic_capture=notional_support._batch(  # noqa: SLF001
            notional_support._raw_status(  # noqa: SLF001
                notional_support._status()  # noqa: SLF001
            )
        ),
        source_payload_store=values["source_payload_store"],
        symbol=raw.symbol,
        feature_snapshot_identity=raw.durable_snapshot_id,
        feature_snapshot_decision_time=datetime.fromisoformat(
            raw.source_decision_time.replace("Z", "+00:00")
        ),
    )
    values.update(
        expected_notional_policy=token,
        symbol=raw.symbol,
        feature_snapshot_identity=raw.durable_snapshot_id,
        decision_time=raw.source_decision_time,
    )
    return build_paper_research_causal_cost_evidence_v1(**values)


def _stored_objects(store: ImmutableSourcePayloadStore) -> tuple[Path, ...]:
    return tuple(
        path
        for path in (store.root_path / "sha256").glob("*/*")
        if path.is_file()
    )


def test_builds_exact_cost_bound_shadow_hypothesis_without_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _raw_v2(tmp_path / "raw", monkeypatch)
    cost = _cost_for_raw(raw, tmp_path / "cost", monkeypatch)
    store = ImmutableSourcePayloadStore(tmp_path / "hypothesis-cas")

    result = build_profiled_research_shadow_hypothesis_v1(
        raw_inference=raw,
        cost_evidence=cost,
        store=store,
    )
    contract = result.contract

    assert contract["schema_version"] == (
        PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1_SCHEMA_VERSION
    )
    assert contract["classification"] == (
        PROFILED_RESEARCH_SHADOW_HYPOTHESIS_V1_CLASSIFICATION
    )
    assert len(contract) == 11
    assert len(contract["raw_inference_payload"]) == 64
    assert contract["raw_inference_binding_sha256"] == raw.hypothesis_binding_sha256
    assert contract["cost_evidence_binding"]["artifact_sha256"] == (
        cost.artifact_sha256
    )
    assert contract["cost_evidence_binding"]["ordered_values"] == list(
        cost.ordered_values
    )
    assert contract["decision_reference_binding"]["source"] == (
        PROFILED_RESEARCH_DECISION_REFERENCE_SOURCE
    )
    spread_receipt = cost.ordered_receipts[1]
    exact_rederivation = spread_receipt["derivation_material"][
        "exact_rederivation"
    ]
    assert contract["decision_reference_binding"]["mid"] == (
        exact_rederivation["mid"]
    )
    assert contract["decision_reference_binding"][
        "orderbook_child_read_bindings"
    ] == spread_receipt["child_read_bindings"]
    assert contract["decision_reference_binding"]["caller_supplied_price_used"] is False
    assert contract["decision_reference_binding"]["unfinished_candle_price_used"] is False
    assert contract["counterfactual_holding_horizon_seconds"] == 900
    assert contract["local_research_non_promotable"] is True
    assert len(contract["authorization"]) == 18
    assert set(contract["authorization"].values()) == {False}
    assert contract["durability_status"] == {
        "status": (
            "QUARANTINED_DURABLE_COMMITMENT_AND_PORTABLE_SOURCE_CLOSURE_REQUIRED"
        ),
        "durable_ex_ante_commit_receipt_present": False,
        "pending_hypothesis_index_registered": False,
        "portable_cost_source_closure_complete": False,
        "restart_reopen_supported": False,
        "outcome_maturation_authorized": False,
        "calibration_input_authorized": False,
    }
    assert contract["cost_evidence_binding"]["ordered_feature_names"] == list(
        CAUSAL_COST_ORDERED_FEATURE_NAMES
    )
    assert contract["cost_evidence_binding"]["ordered_receipt_sha256s"] == list(
        cost.ordered_receipt_sha256s
    )

    address = store.verify(
        result.artifact_sha256,
        expected_byte_count=result.artifact_byte_count,
    )
    assert address == result.artifact_address
    exact_bytes = store.get(
        result.artifact_sha256,
        expected_byte_count=result.artifact_byte_count,
    )
    assert exact_bytes == result.artifact_json.encode("ascii")
    assert hashlib.sha256(exact_bytes).hexdigest() == result.artifact_sha256
    copied_cost = contract["cost_evidence_binding"]["artifact_cas_address"]
    assert store.get(
        copied_cost["payload_sha256"],
        expected_byte_count=copied_cost["payload_byte_count"],
    ) == cost.artifact_json.encode("ascii")
    parsed = json.loads(exact_bytes)
    material = {
        key: value
        for key, value in parsed.items()
        if key != "hypothesis_material_sha256"
    }
    expected_material_sha256 = hashlib.sha256(
        json.dumps(
            material,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()
    assert parsed["hypothesis_material_sha256"] == expected_material_sha256


def test_rejects_cost_snapshot_or_decision_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _raw_v2(tmp_path / "raw", monkeypatch)
    mismatched_cost = build_paper_research_causal_cost_evidence_v1(
        **cost_support._inputs(tmp_path / "cost", monkeypatch)  # noqa: SLF001
    )

    store = ImmutableSourcePayloadStore(tmp_path / "hypothesis-cas")
    with pytest.raises(
        ProfiledResearchShadowHypothesisV1ValidationError,
        match="PROFILED_RESEARCH_HYPOTHESIS_COST_SCOPE_OR_IDENTITY_INVALID",
    ):
        build_profiled_research_shadow_hypothesis_v1(
            raw_inference=raw,
            cost_evidence=mismatched_cost,
            store=store,
        )
    assert _stored_objects(store) == ()


def test_rejects_nonfactory_inputs_without_writing_artifact(
    tmp_path: Path,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "hypothesis-cas")

    with pytest.raises(
        ProfiledResearchShadowHypothesisV1ValidationError,
        match="PROFILED_RESEARCH_HYPOTHESIS_RAW_INFERENCE_V2_REQUIRED",
    ):
        build_profiled_research_shadow_hypothesis_v1(
            raw_inference={},
            cost_evidence={},
            store=store,
        )
    assert _stored_objects(store) == ()


def test_result_public_field_replacement_fails_fresh_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _raw_v2(tmp_path / "raw", monkeypatch)
    cost = _cost_for_raw(raw, tmp_path / "cost", monkeypatch)
    result = build_profiled_research_shadow_hypothesis_v1(
        raw_inference=raw,
        cost_evidence=cost,
        store=ImmutableSourcePayloadStore(tmp_path / "hypothesis-cas"),
    )
    tampered = replace(
        result,
        hypothesis_material_sha256="0" * 64,
    )

    with pytest.raises(
        ProfiledResearchShadowHypothesisV1IntegrityError,
        match="PROFILED_RESEARCH_HYPOTHESIS_CONTRACT_BINDING_INVALID",
    ):
        _ = tampered.contract


def test_public_raw_v2_revalidator_wraps_malformed_exact_type_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _raw_v2(tmp_path / "raw", monkeypatch)
    object.__setattr__(raw, "checkpoint_weight_sha256", None)

    with pytest.raises(
        inference_support.inference.LocallyAuthenticatedProfiledResearchInferenceV1Error,
        match=(
            "LOCAL_PROFILED_RAW_INFERENCE_V2_REVALIDATION_FAILED:TypeError"
        ),
    ):
        inference_support.inference.revalidate_locally_authenticated_profiled_research_raw_inference_v2(
            raw
        )


def test_result_malformed_factory_seal_raises_stable_integrity_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _raw_v2(tmp_path / "raw", monkeypatch)
    cost = _cost_for_raw(raw, tmp_path / "cost", monkeypatch)
    result = build_profiled_research_shadow_hypothesis_v1(
        raw_inference=raw,
        cost_evidence=cost,
        store=ImmutableSourcePayloadStore(tmp_path / "hypothesis-cas"),
    )

    with pytest.raises(
        ProfiledResearchShadowHypothesisV1IntegrityError,
        match="PROFILED_RESEARCH_HYPOTHESIS_FACTORY_CONSTRUCTION_REQUIRED",
    ):
        _ = replace(result, _factory_seal=None).contract
