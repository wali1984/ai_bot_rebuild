from __future__ import annotations

import copy
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    authenticated_ohlcv_profile_transform_v1 as transform_module,
)
from v2.backend.app.services.native_trainer import (
    locally_authenticated_profiled_research_inference_v1 as inference,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (  # noqa: E501
    LOGICAL_MODEL_INPUT_COUNT,
    PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_locally_authenticated_profiled_research_service_v1 as service_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_model_feature_snapshot_record_v1 as record_support,
)


class _FakeModel:
    last_tensor: Any = None

    def __init__(
        self,
        *,
        input_dim: int,
        checkpoint_feature_abi_binding: object,
    ) -> None:
        assert checkpoint_feature_abi_binding is not None
        self.input_dim = input_dim
        self.model_id = "local-profiled-inference-test-model"
        self.fingerprint = "2" * 64

    def forward(self, tensor):  # noqa: ANN001
        type(self).last_tensor = tensor
        return SimpleNamespace(
            model_id=self.model_id,
            action_logits=(0.0, 2.0, 1.0, 0.0, -1.0, -2.0, -3.0),
            selected_action_index=1,
            selected_action="long",
            device="cpu",
            cuda_active=False,
            model_tensors_device_verified=True,
        )


@pytest.fixture(autouse=True)
def _clear_process_source_order_registry():  # noqa: ANN201
    with inference._PROCESS_SOURCE_ORDER_LOCK:  # noqa: SLF001
        inference._PROCESS_LAST_SOURCE_DECISION_BY_CANDIDATE_PAIR.clear()  # noqa: SLF001
    yield
    with inference._PROCESS_SOURCE_ORDER_LOCK:  # noqa: SLF001
        inference._PROCESS_LAST_SOURCE_DECISION_BY_CANDIDATE_PAIR.clear()  # noqa: SLF001


def _contract() -> dict[str, object]:
    return {
        "candidate_policy_fingerprint": "2" * 64,
        "authorization_receipt_sha256": "3" * 64,
        "code_release_sha": "a" * 40,
        "manifest_observation_time": "2026-07-19T00:00:00.000000Z",
        "optimizer_implementation_artifact_sha256": "4" * 64,
        "local_research_non_promotable": True,
        "external_witness_verified": False,
        "prediction_authorized": False,
        "serving_authorized": False,
        "serving_activation_authorized": False,
        "serving_promotion_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "exchange_access_authorized": False,
        "deployment_authorized": False,
        "order_submission_authorized": False,
        "execution_authorized": False,
        "runtime_wired": False,
    }


def _open_handle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    checkpoint_generated_at: str = "2026-07-20T00:00:00.000000Z",
    load_status: str = "LOADED",
    manager_init_error: bool = False,
) -> inference.LocallyAuthenticatedProfiledResearchInferenceHandleV1:
    tmp_path.mkdir(parents=True, exist_ok=True)
    checkpoint_id = "v2_hybrid_ckpt_local_profiled_test"
    manifest = SimpleNamespace(
        checkpoint_id=checkpoint_id,
        checkpoint_generation=7,
        generated_utc=checkpoint_generated_at,
        weight_file_sha256="1" * 64,
        weight_file_size_bytes=4096,
        checkpoint_evidence_digest="5" * 64,
        checkpoint_semantic_digest="6" * 64,
        checkpoint_causal_record_digest="7" * 64,
        model_id="local-profiled-inference-test-model",
        input_dim=LOGICAL_MODEL_INPUT_COUNT,
        model_parameter_fingerprint="2" * 64,
    )

    class FakeManager:
        def __init__(self, model_dir) -> None:  # noqa: ANN001
            if manager_init_error:
                raise OSError("manager unavailable")
            self.model_dir = model_dir

        def manifests(self, **kwargs):  # noqa: ANN003
            assert kwargs["verify_lineage_artifacts"] is False
            return (manifest,)

        def load_latest_weights(self, model, **kwargs):  # noqa: ANN001, ANN003
            assert kwargs["expected_checkpoint_id"] == checkpoint_id
            assert model.model_id == manifest.model_id
            return {
                "checkpoint_id": checkpoint_id,
                "load_status": load_status,
                "latest_checkpoint_loadable": True,
                "model_state_restored": True,
                "checkpoint_evidence_verified": True,
                "checkpoint_identity_verified": True,
                "model_parameter_fingerprint_verified": True,
                "weight_file_sha256_verified": True,
                "private_checkpoint_copy_verified": True,
                "private_checkpoint_source_open_count": 1,
                "private_checkpoint_copy_sha256": manifest.weight_file_sha256,
                "private_checkpoint_copy_size_bytes": manifest.weight_file_size_bytes,
                "lineage_kind": inference.LOCAL_PROFILED_RESEARCH_CANDIDATE_LINEAGE,
                "checkpoint_causal_store": (
                    service_support.service.LOCAL_PROFILED_RESEARCH_CANDIDATE_DIRECTORY
                ),
                "checkpoint_generation": manifest.checkpoint_generation,
                "checkpoint_semantic_digest": manifest.checkpoint_semantic_digest,
                "checkpoint_causal_record_digest": (manifest.checkpoint_causal_record_digest),
                "checkpoint_evidence_digest": manifest.checkpoint_evidence_digest,
                "model_parameter_fingerprint": manifest.model_parameter_fingerprint,
            }

    @contextmanager
    def lease(*_args, **_kwargs):
        yield object()

    verified_release: dict[str, object] = {}

    def verify_release(**kwargs):  # noqa: ANN003
        verified_release.update(kwargs)

    monkeypatch.setattr(inference, "V2HybridCheckpointManager", FakeManager)
    monkeypatch.setattr(inference, "V2HybridPolicyModel", _FakeModel)
    monkeypatch.setattr(
        inference,
        "model_parameter_fingerprint",
        lambda model: model.fingerprint,
    )
    monkeypatch.setattr(inference, "checkpoint_lifecycle_lease", lease)
    monkeypatch.setattr(
        inference,
        "_verify_local_candidate_manifest",
        lambda **_kwargs: _contract(),
    )
    monkeypatch.setattr(
        inference,
        "verify_current_profiled_optimizer_release_source_closure_v1",
        verify_release,
    )
    handle = inference.open_locally_authenticated_profiled_research_inference_v1(
        config=service_support._config(tmp_path),  # noqa: SLF001
        credentials=service_support._credentials(),  # noqa: SLF001
        expected_checkpoint_id=checkpoint_id,
    )
    assert verified_release == {
        "expected_code_release_sha": "a" * 40,
        "expected_optimizer_implementation_artifact_sha256": "4" * 64,
    }
    return handle


def _build_evidence(monkeypatch: pytest.MonkeyPatch, tmp_path):  # noqa: ANN201
    # The isolated worktree intentionally reuses the repository venv through
    # an absolute path, so the environment's repository-path identity cannot
    # match this temporary checkout. The transform itself remains real here.
    monkeypatch.setattr(
        transform_module,
        "_validate_active_talib_environment",
        lambda: None,
    )
    return record_support._build_evidence(tmp_path)  # noqa: SLF001


def test_exact_candidate_open_enforces_authority_free_postconditions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    handle = _open_handle(monkeypatch, tmp_path)

    assert handle.checkpoint_generation == 7
    assert handle.current_release_verified is True
    assert handle.current_source_closure_verified is True
    assert all(
        getattr(handle, field_name) is False
        for field_name in inference._FALSE_AUTHORITY_FIELDS  # noqa: SLF001
    )


def test_handle_seal_binds_checkpoint_time_and_all_public_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    handle = _open_handle(monkeypatch, tmp_path)

    with pytest.raises(
        inference.LocallyAuthenticatedProfiledResearchInferenceV1Error,
        match="LOCAL_PROFILED_INFERENCE_HANDLE_INVALID",
    ):
        replace(
            handle,
            checkpoint_generated_at="2026-07-19T12:00:00.000000Z",
            _factory_token=inference._HANDLE_FACTORY_TOKEN,  # noqa: SLF001
        )


def test_checkpoint_open_wraps_manager_initialization_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    with pytest.raises(
        inference.LocallyAuthenticatedProfiledResearchInferenceV1Error,
        match="LOCAL_PROFILED_INFERENCE_CHECKPOINT_OPEN_FAILED:OSError",
    ):
        _open_handle(monkeypatch, tmp_path, manager_init_error=True)


def test_checkpoint_open_rejects_failed_exact_load_postcondition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    with pytest.raises(
        inference.LocallyAuthenticatedProfiledResearchInferenceV1Error,
        match="LOCAL_PROFILED_INFERENCE_CHECKPOINT_LOAD_POSTCONDITIONS_FAILED",
    ):
        _open_handle(monkeypatch, tmp_path, load_status="FAILED")


def test_fresh_record_revalidation_preserves_real_coverage_and_quarantine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    handle = _open_handle(monkeypatch, tmp_path / "handle")
    evidence = _build_evidence(monkeypatch, tmp_path / "evidence")
    clocks = iter(
        (
            "2026-07-21T13:00:00.000000Z",
            "2026-07-21T13:00:01.000000Z",
            "2026-07-21T13:00:02.000000Z",
        )
    )
    monkeypatch.setattr(inference, "_utc_iso", lambda: next(clocks))

    result = handle.infer_profiled_record_v1(
        record=evidence.record,
        transform_result=evidence.transformed,
        capture_set_contract=evidence.contract,
        capture_set_store=evidence.capture_store,
        artifact_store=evidence.artifact_store,
        source_provenance_ledger=evidence.source_ledger,
        source_provenance_entries=evidence.source_entries,
    )

    tensor = _FakeModel.last_tensor
    assert tensor is not None
    assert len(tensor.model_vector) == 1784
    assert sum(tensor.source_availability) == 35
    assert tensor.data_coverage_percent == pytest.approx(100.0 * 35 / 446)
    assert tensor.temporal_rejection_reasons == (
        PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON,
    )
    assert result.available_feature_count == 35
    assert result.data_coverage_percent == pytest.approx(100.0 * 35 / 446)
    assert result.selected_action == "long"
    assert result.hypothesis_generated_at == "2026-07-21T13:00:01.000000Z"
    assert result.confidence_calibrated is None
    assert result.profitability_probability is None
    payload = result.to_payload()
    binding = payload.pop("hypothesis_binding_sha256")
    assert type(payload["temporal_rejection_reasons"]) is list
    assert type(payload["raw_action_logits"]) is list
    assert binding == inference.stable_sha256(payload)
    assert all(
        payload[field_name] is False
        for field_name in inference._FALSE_AUTHORITY_FIELDS  # noqa: SLF001
    )

    with pytest.raises(
        inference.LocallyAuthenticatedProfiledResearchInferenceV1Error,
        match="LOCAL_PROFILED_INFERENCE_SOURCE_ORDER_NOT_MONOTONIC",
    ):
        handle.infer_profiled_record_v1(
            record=evidence.record,
            transform_result=evidence.transformed,
            capture_set_contract=evidence.contract,
            capture_set_store=evidence.capture_store,
            artifact_store=evidence.artifact_store,
            source_provenance_ledger=evidence.source_ledger,
            source_provenance_entries=evidence.source_entries,
        )


def test_reopened_handle_cannot_replay_same_candidate_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    first = _open_handle(monkeypatch, tmp_path / "first")
    second = _open_handle(monkeypatch, tmp_path / "second")
    evidence = _build_evidence(monkeypatch, tmp_path / "evidence")
    monkeypatch.setattr(
        inference,
        "_utc_iso",
        lambda: "2026-07-21T13:00:00.000000Z",
    )
    kwargs = {
        "record": evidence.record,
        "transform_result": evidence.transformed,
        "capture_set_contract": evidence.contract,
        "capture_set_store": evidence.capture_store,
        "artifact_store": evidence.artifact_store,
        "source_provenance_ledger": evidence.source_ledger,
        "source_provenance_entries": evidence.source_entries,
    }

    first.infer_profiled_record_v1(**kwargs)
    with pytest.raises(
        inference.LocallyAuthenticatedProfiledResearchInferenceV1Error,
        match="LOCAL_PROFILED_INFERENCE_SOURCE_ORDER_NOT_MONOTONIC",
    ):
        second.infer_profiled_record_v1(**kwargs)


def test_inference_revalidates_current_release_before_forward(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    handle = _open_handle(monkeypatch, tmp_path / "handle")
    evidence = _build_evidence(monkeypatch, tmp_path / "evidence")
    monkeypatch.setattr(
        inference,
        "_utc_iso",
        lambda: "2026-07-21T13:00:00.000000Z",
    )

    def drifted_release(**_kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("source drift")

    monkeypatch.setattr(
        inference,
        "verify_current_profiled_optimizer_release_source_closure_v1",
        drifted_release,
    )

    with pytest.raises(
        inference.LocallyAuthenticatedProfiledResearchInferenceV1Error,
        match="LOCAL_PROFILED_INFERENCE_RELEASE_SOURCE_CLOSURE_REVALIDATION_FAILED",
    ):
        handle.infer_profiled_record_v1(
            record=evidence.record,
            transform_result=evidence.transformed,
            capture_set_contract=evidence.contract,
            capture_set_store=evidence.capture_store,
            artifact_store=evidence.artifact_store,
            source_provenance_ledger=evidence.source_ledger,
            source_provenance_entries=evidence.source_entries,
        )


def test_malformed_model_output_is_stably_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    handle = _open_handle(monkeypatch, tmp_path / "handle")
    evidence = _build_evidence(monkeypatch, tmp_path / "evidence")
    monkeypatch.setattr(
        inference,
        "_utc_iso",
        lambda: "2026-07-21T13:00:00.000000Z",
    )
    monkeypatch.setattr(
        _FakeModel,
        "forward",
        lambda _self, _tensor: SimpleNamespace(model_id=_self.model_id),
    )

    with pytest.raises(
        inference.LocallyAuthenticatedProfiledResearchInferenceV1Error,
        match="LOCAL_PROFILED_INFERENCE_MODEL_OUTPUT_INVALID:AttributeError",
    ):
        handle.infer_profiled_record_v1(
            record=evidence.record,
            transform_result=evidence.transformed,
            capture_set_contract=evidence.contract,
            capture_set_store=evidence.capture_store,
            artifact_store=evidence.artifact_store,
            source_provenance_ledger=evidence.source_ledger,
            source_provenance_entries=evidence.source_entries,
        )


def test_caller_record_tamper_is_recomputed_and_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    handle = _open_handle(monkeypatch, tmp_path / "handle")
    evidence = _build_evidence(monkeypatch, tmp_path / "evidence")
    tampered = copy.deepcopy(evidence.record)
    tampered["frozen_envelope"]["feature_values"][0] += 1.0
    monkeypatch.setattr(
        inference,
        "_utc_iso",
        lambda: "2026-07-21T13:00:00.000000Z",
    )

    with pytest.raises(
        inference.LocallyAuthenticatedProfiledResearchInferenceV1Error,
        match="LOCAL_PROFILED_INFERENCE_RECORD_REVALIDATION_FAILED",
    ):
        handle.infer_profiled_record_v1(
            record=tampered,
            transform_result=evidence.transformed,
            capture_set_contract=evidence.contract,
            capture_set_store=evidence.capture_store,
            artifact_store=evidence.artifact_store,
            source_provenance_ledger=evidence.source_ledger,
            source_provenance_entries=evidence.source_entries,
        )


def test_pre_checkpoint_feature_record_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    handle = _open_handle(
        monkeypatch,
        tmp_path / "handle",
        checkpoint_generated_at="2026-07-22T00:00:00.000000Z",
    )
    evidence = _build_evidence(monkeypatch, tmp_path / "evidence")
    monkeypatch.setattr(
        inference,
        "_utc_iso",
        lambda: "2026-07-22T13:00:00.000000Z",
    )

    with pytest.raises(
        inference.LocallyAuthenticatedProfiledResearchInferenceV1Error,
        match="LOCAL_PROFILED_INFERENCE_NOT_STRICTLY_POST_CHECKPOINT_PIT",
    ):
        handle.infer_profiled_record_v1(
            record=evidence.record,
            transform_result=evidence.transformed,
            capture_set_contract=evidence.contract,
            capture_set_store=evidence.capture_store,
            artifact_store=evidence.artifact_store,
            source_provenance_ledger=evidence.source_ledger,
            source_provenance_entries=evidence.source_entries,
        )
