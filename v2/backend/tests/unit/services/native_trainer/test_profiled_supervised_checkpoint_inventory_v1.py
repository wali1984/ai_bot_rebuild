from __future__ import annotations

import copy
import hashlib
import pickle
import struct
from dataclasses import fields as dataclass_fields
from dataclasses import replace
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    profiled_supervised_checkpoint_inventory_v1 as checkpoint_module,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_corpus_v1 import (
    build_authenticated_profiled_optimizer_corpus_v1,
    validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    stable_sha256,
)
from v2.backend.app.services.native_trainer.profiled_supervised_checkpoint_inventory_v1 import (
    PROFILED_SUPERVISED_CHECKPOINT_BINARY_MAGIC,
    PROFILED_SUPERVISED_CHECKPOINT_STATUS,
    ProfiledSupervisedCheckpointInventoryV1,
    ProfiledSupervisedCheckpointInventoryV1Error,
    build_authenticated_profiled_supervised_checkpoint_inventory_v1,
    capture_profiled_supervised_optimization_state_snapshot_v1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_authenticated_profiled_optimizer_admission_v1 as admission_support,
)

adapter_evidence = admission_support.adapter_evidence

_BEFORE_VERIFIED_AT = "2026-07-27T00:00:01.000000Z"
_BEFORE_CAPTURED_AT = "2026-07-27T00:00:02.000000Z"
_OPTIMIZER_STARTED_AT = "2026-07-27T00:00:03.000000Z"
_OPTIMIZER_COMPLETED_AT = "2026-07-27T00:00:04.000000Z"
_AFTER_CAPTURED_AT = "2026-07-27T00:00:05.000000Z"
_AFTER_VERIFIED_AT = "2026-07-27T00:00:06.000000Z"
_CHECKPOINT_CREATED_AT = "2026-07-27T00:00:07.000000Z"
_IMPLEMENTATION = b"unit-supervised-optimizer-implementation-v1"
_CONFIGURATION = b'{"learning_rate_mode":"adaptive","optimizer":"unit_adam"}'
_ENVIRONMENT = b'{"cuda":"none","device":"cpu","python":"3.11"}'


def _state(*, after: bool, changed_shape: bool = False) -> Any:
    stage = "AFTER_OPTIMIZATION" if after else "BEFORE_OPTIMIZATION"
    captured_at = _AFTER_CAPTURED_AT if after else _BEFORE_CAPTURED_AT
    weight_shape = (1, 2) if changed_shape else (2,)
    weight_values = (1.5, 2.5) if after else (1.0, 2.0)
    return capture_profiled_supervised_optimization_state_snapshot_v1(
        stage=stage,
        captured_at=captured_at,
        model_tensors=(
            ("layer.bias", "float32", (1,), struct.pack("<f", 0.25 if after else 0.0)),
            ("layer.weight", "float32", weight_shape, struct.pack("<2f", *weight_values)),
        ),
        optimizer_tensors=(
            (
                "state.moment",
                "float32",
                (2,),
                struct.pack("<2f", *(0.1, 0.2) if after else (0.0, 0.0)),
            ),
            ("state.step", "int64", (), struct.pack("<q", 1 if after else 0)),
        ),
    )


def _inputs(evidence: dict[str, Any]) -> dict[str, Any]:
    admitted = admission_support._admit(evidence)
    before = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    after = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    authorization = validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1(
        before=before,
        after=after,
    )
    return {
        "before_corpus": before,
        "after_corpus": after,
        "execution_authorization": authorization,
        "before_state": _state(after=False),
        "after_state": _state(after=True),
        "before_input_inventory_verified_at": _BEFORE_VERIFIED_AT,
        "optimizer_started_at": _OPTIMIZER_STARTED_AT,
        "optimizer_completed_at": _OPTIMIZER_COMPLETED_AT,
        "after_input_inventory_verified_at": _AFTER_VERIFIED_AT,
        "checkpoint_created_at": _CHECKPOINT_CREATED_AT,
        "optimizer_implementation_artifact_bytes": _IMPLEMENTATION,
        "optimizer_configuration_artifact_json_bytes": _CONFIGURATION,
        "execution_environment_artifact_json_bytes": _ENVIRONMENT,
    }


def _build(evidence: dict[str, Any], **updates: Any) -> ProfiledSupervisedCheckpointInventoryV1:
    return build_authenticated_profiled_supervised_checkpoint_inventory_v1(
        **{**_inputs(evidence), **updates}
    )


def _unchecked_copy(value: ProfiledSupervisedCheckpointInventoryV1, **updates: Any) -> Any:
    copied = object.__new__(ProfiledSupervisedCheckpointInventoryV1)
    for item in dataclass_fields(value):
        object.__setattr__(copied, item.name, updates.get(item.name, getattr(value, item.name)))
    return copied


def test_builds_deterministic_exact_checkpoint_inventory_without_downstream_authority(
    adapter_evidence: dict[str, Any],
) -> None:
    first = _build(adapter_evidence)
    second = _build(adapter_evidence)

    assert first.status == PROFILED_SUPERVISED_CHECKPOINT_STATUS
    assert first.checkpoint_bytes.startswith(PROFILED_SUPERVISED_CHECKPOINT_BINARY_MAGIC)
    assert first.checkpoint_bytes == second.checkpoint_bytes
    assert first.checkpoint_bytes_sha256 == hashlib.sha256(first.checkpoint_bytes).hexdigest()
    assert first.checkpoint_inventory_sha256 == second.checkpoint_inventory_sha256
    assert first.before_optimizer_input_inventory_sha256 == (
        first.after_optimizer_input_inventory_sha256
    )
    assert first.corpus_inventory_equal_before_after_optimization is True
    assert first.model_coordinates_equal_before_after_optimization is True
    assert first.before_model_state_identity_sha256 != first.after_model_state_identity_sha256
    assert first.model_state_changed is True
    assert first.optimizer_execution_independently_observed is False
    assert first.in_memory_checkpoint_candidate_created is True
    assert first.outcome_supervised_objective_only is True
    assert first.behavior_receipt_bound is False
    assert first.ppo_behavior_policy_terms_enabled is False
    assert all(getattr(first, name) is False for name in checkpoint_module._AUTHORITY_FALSE)


def test_manifest_witness_projection_rows_targets_and_artifacts_are_bound(
    adapter_evidence: dict[str, Any],
) -> None:
    result = _build(adapter_evidence)
    corpus = result.before_corpus
    row = corpus.rows[0]

    assert result.manifest_id == corpus.manifest_id
    assert result.manifest_entry_chain_head_sha256 == corpus.manifest_entry_chain_head_sha256
    assert result.completion_event_sha256 == corpus.completion_event_sha256
    assert result.completion_ordered_page_root_sha256 == corpus.completion_ordered_page_root_sha256
    assert result.external_authorization_envelope_sha256 == (
        corpus.external_authorization_envelope_sha256
    )
    assert result.witness_public_key_sha256 == corpus.witness_public_key_sha256
    assert result.logical_profile_selection_mask == corpus.logical_profile_selection_mask
    assert result.projection_implementation_sha256 == corpus.projection_implementation_sha256
    assert result.admitted_ordinals == (row.ordinal,)
    assert (
        result.optimizer_implementation_artifact_sha256
        == hashlib.sha256(_IMPLEMENTATION).hexdigest()
    )
    assert (
        result.optimizer_configuration_artifact_sha256 == hashlib.sha256(_CONFIGURATION).hexdigest()
    )
    assert result.execution_environment_artifact_sha256 == hashlib.sha256(_ENVIRONMENT).hexdigest()
    assert row.sample_identity_sha256.encode() in result.checkpoint_bytes
    assert row.supervised_target.target_sha256.encode() in result.checkpoint_bytes


def test_state_capture_rejects_unordered_duplicate_or_malformed_tensor_bytes() -> None:
    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_STATE_ITEM_ORDER_OR_UNIQUENESS_INVALID",
    ):
        capture_profiled_supervised_optimization_state_snapshot_v1(
            stage="BEFORE_OPTIMIZATION",
            captured_at=_BEFORE_CAPTURED_AT,
            model_tensors=(
                ("z", "float32", (1,), struct.pack("<f", 1.0)),
                ("a", "float32", (1,), struct.pack("<f", 2.0)),
            ),
            optimizer_tensors=(),
        )

    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_TENSOR_STATE_ITEM_INVALID",
    ):
        capture_profiled_supervised_optimization_state_snapshot_v1(
            stage="BEFORE_OPTIMIZATION",
            captured_at=_BEFORE_CAPTURED_AT,
            model_tensors=(("weight", "float32", (2,), struct.pack("<f", 1.0)),),
            optimizer_tensors=(),
        )


def test_coherent_tensor_replace_cannot_reuse_private_factory_seal() -> None:
    tensor = _state(after=False).model_tensors[0]
    changed_payload = struct.pack("<f", 99.0)
    changed_payload_sha256 = hashlib.sha256(changed_payload).hexdigest()
    material = checkpoint_module._tensor_item_material(
        role=tensor.role,
        name=tensor.name,
        dtype=tensor.dtype,
        shape=tensor.shape,
        byte_count=len(changed_payload),
        payload_sha256=changed_payload_sha256,
        coordinate_sha256=tensor.coordinate_sha256,
    )

    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_TENSOR_STATE_ITEM_FACTORY_SEAL_INVALID",
    ):
        replace(
            tensor,
            payload=changed_payload,
            payload_sha256=changed_payload_sha256,
            tensor_state_identity_sha256=stable_sha256(material),
        )


def test_coherent_state_snapshot_replace_cannot_reuse_private_factory_seal() -> None:
    state = _state(after=False)
    changed_clock = "2026-07-27T00:00:02.500000Z"
    material = checkpoint_module._state_snapshot_material(
        stage=state.stage,
        captured_at=changed_clock,
        model_coordinate_inventory_sha256=state.model_coordinate_inventory_sha256,
        model_state_content_inventory_sha256=state.model_state_content_inventory_sha256,
        optimizer_coordinate_inventory_sha256=state.optimizer_coordinate_inventory_sha256,
        optimizer_state_content_inventory_sha256=state.optimizer_state_content_inventory_sha256,
        model_tensor_count=state.model_tensor_count,
        optimizer_tensor_count=state.optimizer_tensor_count,
    )

    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_STATE_SNAPSHOT_FACTORY_SEAL_INVALID",
    ):
        replace(
            state,
            captured_at=changed_clock,
            state_snapshot_sha256=stable_sha256(material),
        )


def test_even_unchanged_dataclass_replace_cannot_duplicate_one_time_capabilities(
    adapter_evidence: dict[str, Any],
) -> None:
    state = _state(after=False)
    tensor = state.model_tensors[0]
    result = _build(adapter_evidence)

    for value, reason in (
        (tensor, "PROFILED_CHECKPOINT_TENSOR_STATE_ITEM_FACTORY_SEAL_INVALID"),
        (state, "PROFILED_CHECKPOINT_STATE_SNAPSHOT_FACTORY_SEAL_INVALID"),
        (result, "PROFILED_CHECKPOINT_INVENTORY_FACTORY_SEAL_INVALID"),
    ):
        with pytest.raises(ProfiledSupervisedCheckpointInventoryV1Error, match=reason):
            replace(value)


def test_coherent_checkpoint_artifact_replace_cannot_reuse_private_factory_seal(
    adapter_evidence: dict[str, Any],
) -> None:
    result = _build(adapter_evidence)
    changed_artifact = b"coherently-substituted-optimizer-implementation"
    changed_sha256 = hashlib.sha256(changed_artifact).hexdigest()
    tampered = _unchecked_copy(
        result,
        optimizer_implementation_artifact_bytes=changed_artifact,
        optimizer_implementation_artifact_sha256=changed_sha256,
        optimizer_implementation_artifact_byte_count=len(changed_artifact),
    )
    header = checkpoint_module._canonical_bytes(
        checkpoint_module._checkpoint_header_material(tampered),
        reason="TEST_HEADER_INVALID",
    )
    checkpoint_bytes = checkpoint_module._build_checkpoint_bytes(
        value=tampered,
        header_bytes=header,
    )
    tampered = _unchecked_copy(
        tampered,
        checkpoint_header_json_sha256=hashlib.sha256(header).hexdigest(),
        checkpoint_bytes=checkpoint_bytes,
        checkpoint_bytes_sha256=hashlib.sha256(checkpoint_bytes).hexdigest(),
        checkpoint_byte_count=len(checkpoint_bytes),
    )
    tampered = _unchecked_copy(
        tampered,
        checkpoint_inventory_sha256=stable_sha256(
            checkpoint_module._checkpoint_inventory_material(tampered)
        ),
    )

    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_INVENTORY_FACTORY_SEAL_INVALID",
    ):
        replace(
            result,
            optimizer_implementation_artifact_bytes=changed_artifact,
            optimizer_implementation_artifact_sha256=changed_sha256,
            optimizer_implementation_artifact_byte_count=len(changed_artifact),
            checkpoint_header_json_sha256=tampered.checkpoint_header_json_sha256,
            checkpoint_bytes=tampered.checkpoint_bytes,
            checkpoint_bytes_sha256=tampered.checkpoint_bytes_sha256,
            checkpoint_byte_count=tampered.checkpoint_byte_count,
            checkpoint_inventory_sha256=tampered.checkpoint_inventory_sha256,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("optimizer_started_at", _BEFORE_CAPTURED_AT),
        ("optimizer_completed_at", _OPTIMIZER_STARTED_AT),
        ("after_input_inventory_verified_at", _AFTER_CAPTURED_AT),
        ("checkpoint_created_at", _AFTER_VERIFIED_AT),
        ("optimizer_started_at", "2026-07-27T00:00:03Z"),
    ),
)
def test_non_strict_or_noncanonical_optimizer_clocks_fail_closed(
    adapter_evidence: dict[str, Any],
    field_name: str,
    value: str,
) -> None:
    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_(?:CLOCK|INVENTORY)_INVALID",
    ):
        _build(adapter_evidence, **{field_name: value})


def test_model_coordinate_drift_and_unchanged_model_state_fail_closed(
    adapter_evidence: dict[str, Any],
) -> None:
    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_INVENTORY_INVALID",
    ):
        _build(adapter_evidence, after_state=_state(after=True, changed_shape=True))

    before = _state(after=False)
    unchanged_after = capture_profiled_supervised_optimization_state_snapshot_v1(
        stage="AFTER_OPTIMIZATION",
        captured_at=_AFTER_CAPTURED_AT,
        model_tensors=tuple(
            (item.name, item.dtype, item.shape, item.payload) for item in before.model_tensors
        ),
        optimizer_tensors=tuple(
            (item.name, item.dtype, item.shape, item.payload) for item in before.optimizer_tensors
        ),
    )
    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_INVENTORY_INVALID",
    ):
        _build(adapter_evidence, before_state=before, after_state=unchanged_after)


@pytest.mark.parametrize(
    "field_name,value",
    (
        (
            "optimizer_configuration_artifact_json_bytes",
            b'{"optimizer":"unit","optimizer":"forged"}',
        ),
        ("optimizer_configuration_artifact_json_bytes", b'{"z":1,"a":2}'),
        ("execution_environment_artifact_json_bytes", b'{"nan":NaN}'),
    ),
)
def test_configuration_and_environment_require_exact_canonical_json(
    adapter_evidence: dict[str, Any], field_name: str, value: bytes
) -> None:
    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_(?:CONFIGURATION|ENVIRONMENT)_ARTIFACT_INVALID",
    ):
        _build(adapter_evidence, **{field_name: value})


def test_checkpoint_bytes_or_authority_cannot_be_changed_after_factory(
    adapter_evidence: dict[str, Any],
) -> None:
    result = _build(adapter_evidence)

    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_INVENTORY_INVALID",
    ):
        replace(result, checkpoint_bytes=result.checkpoint_bytes + b"x")

    for field_name in checkpoint_module._AUTHORITY_FALSE:
        with pytest.raises(
            ProfiledSupervisedCheckpointInventoryV1Error,
            match="PROFILED_CHECKPOINT_INVENTORY_INVALID",
        ):
            replace(result, **{field_name: True})


@pytest.mark.parametrize("operation", (copy.copy, copy.deepcopy, pickle.dumps))
def test_checkpoint_inventory_copy_or_pickle_capability_transfer_fails_closed(
    adapter_evidence: dict[str, Any], operation: Any
) -> None:
    result = _build(adapter_evidence)

    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_INVENTORY_PICKLE_OR_COPY_FORBIDDEN",
    ):
        operation(result)


@pytest.mark.parametrize("operation", (copy.copy, copy.deepcopy, pickle.dumps))
def test_nested_state_results_copy_or_pickle_capability_transfer_fails_closed(
    operation: Any,
) -> None:
    state = _state(after=False)
    tensor = state.model_tensors[0]

    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_STATE_SNAPSHOT_PICKLE_OR_COPY_FORBIDDEN",
    ):
        operation(state)
    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_TENSOR_STATE_ITEM_PICKLE_OR_COPY_FORBIDDEN",
    ):
        operation(tensor)


def test_mutated_or_shallow_corpus_is_reauthenticated_before_checkpoint(
    adapter_evidence: dict[str, Any],
) -> None:
    inputs = _inputs(adapter_evidence)
    changed_before = replace(inputs["before_corpus"])
    object.__setattr__(changed_before, "completion_event_sha256", "0" * 64)

    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_CORPUS_REAUTHENTICATION_FAILED",
    ):
        build_authenticated_profiled_supervised_checkpoint_inventory_v1(
            **{**inputs, "before_corpus": changed_before}
        )


def test_builder_has_no_path_argument_and_does_not_write_files(
    adapter_evidence: dict[str, Any], tmp_path: Any
) -> None:
    before = tuple(tmp_path.iterdir())
    result = _build(adapter_evidence)

    assert result.checkpoint_byte_count > 0
    assert tuple(tmp_path.iterdir()) == before == ()
