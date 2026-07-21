from __future__ import annotations

import copy
import hashlib
import json
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
    decode_and_validate_profiled_supervised_checkpoint_binary_v2,
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
_STATE_RESOURCE_BUDGET = 1024 * 1024
_SERIALIZATION_BYTE_BUDGET = 4 * 1024 * 1024


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
        resource_budget_bytes=_STATE_RESOURCE_BUDGET,
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
        "serialization_byte_budget": _SERIALIZATION_BYTE_BUDGET,
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


def _binary_parts(value: bytes) -> tuple[dict[str, Any], list[bytes]]:
    magic_count = len(PROFILED_SUPERVISED_CHECKPOINT_BINARY_MAGIC)
    header_count = struct.unpack(">Q", value[magic_count : magic_count + 8])[0]
    header_start = magic_count + 8
    header_end = header_start + header_count
    header = json.loads(value[header_start:header_end].decode("ascii"))
    frames: list[bytes] = []
    cursor = header_end
    while cursor < len(value):
        frame_start = cursor
        name_count = struct.unpack(">I", value[cursor : cursor + 4])[0]
        cursor += 4 + name_count
        payload_count = struct.unpack(">Q", value[cursor : cursor + 8])[0]
        cursor += 8 + payload_count
        frames.append(value[frame_start:cursor])
    return header, frames


def _reencode_binary(header: dict[str, Any], frames: list[bytes]) -> bytes:
    header_bytes = json.dumps(
        header,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return (
        PROFILED_SUPERVISED_CHECKPOINT_BINARY_MAGIC
        + struct.pack(">Q", len(header_bytes))
        + header_bytes
        + b"".join(frames)
    )


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


def test_binary_v2_is_self_describing_and_independently_replays(
    adapter_evidence: dict[str, Any],
) -> None:
    result = _build(adapter_evidence)
    replay = decode_and_validate_profiled_supervised_checkpoint_binary_v2(result.checkpoint_bytes)
    header, _frames = _binary_parts(result.checkpoint_bytes)
    first_tensor = header["payload_frames"][0]

    assert replay.semantic_replay_verified is True
    assert replay.checkpoint_bytes_sha256 == result.checkpoint_bytes_sha256
    assert replay.checkpoint_header_json_sha256 == result.checkpoint_header_json_sha256
    assert replay.model_tensor_count == result.after_state.model_tensor_count
    assert set(first_tensor) == {
        "frame_index",
        "frame_kind",
        "frame_name",
        "role",
        "name",
        "dtype",
        "shape",
        "byte_order",
        "layout",
        "coordinate_sha256",
        "tensor_state_identity_sha256",
        "byte_count",
        "payload_sha256",
    }
    independent_coordinate_material = {
        "role": first_tensor["role"],
        "name": first_tensor["name"],
        "dtype": first_tensor["dtype"],
        "shape": first_tensor["shape"],
        "byte_order": first_tensor["byte_order"],
        "layout": first_tensor["layout"],
    }
    independent_state_material = {
        "schema_version": "profiled_supervised_tensor_state_item_v1",
        **independent_coordinate_material,
        "byte_count": first_tensor["byte_count"],
        "payload_sha256": first_tensor["payload_sha256"],
        "coordinate_sha256": first_tensor["coordinate_sha256"],
    }
    assert first_tensor["coordinate_sha256"] == stable_sha256(independent_coordinate_material)
    assert first_tensor["tensor_state_identity_sha256"] == stable_sha256(independent_state_material)
    assert all(getattr(replay, name) is False for name in checkpoint_module._AUTHORITY_FALSE)


def test_binary_replay_result_cannot_be_forged_or_transferred_as_a_capability(
    adapter_evidence: dict[str, Any],
) -> None:
    result = _build(adapter_evidence)
    replay = decode_and_validate_profiled_supervised_checkpoint_binary_v2(result.checkpoint_bytes)

    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_BINARY_REPLAY_FACTORY_SEAL_INVALID",
    ):
        replace(replay)
    for operation in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(
            ProfiledSupervisedCheckpointInventoryV1Error,
            match="PROFILED_CHECKPOINT_BINARY_REPLAY_PICKLE_OR_COPY_FORBIDDEN",
        ):
            operation(replay)


def test_binary_replay_rejects_reordered_duplicate_truncated_trailing_and_tampered_frames(
    adapter_evidence: dict[str, Any],
) -> None:
    result = _build(adapter_evidence)
    header, frames = _binary_parts(result.checkpoint_bytes)
    reordered = _reencode_binary(header, [frames[1], frames[0], *frames[2:]])
    duplicated = _reencode_binary(header, [frames[0], frames[0], *frames[2:]])
    tampered = bytearray(result.checkpoint_bytes)
    tampered[-1] ^= 1

    for candidate, reason in (
        (reordered, "PROFILED_CHECKPOINT_BINARY_FRAME_DESCRIPTOR_MISMATCH"),
        (duplicated, "PROFILED_CHECKPOINT_BINARY_FRAME_DESCRIPTOR_MISMATCH"),
        (result.checkpoint_bytes[:-1], "PROFILED_CHECKPOINT_BINARY_FRAME_TRUNCATED"),
        (
            result.checkpoint_bytes + b"x",
            "PROFILED_CHECKPOINT_BINARY_TRAILING_BYTES_FORBIDDEN",
        ),
        (bytes(tampered), "PROFILED_CHECKPOINT_BINARY_FRAME_PAYLOAD_MISMATCH"),
    ):
        with pytest.raises(ProfiledSupervisedCheckpointInventoryV1Error, match=reason):
            decode_and_validate_profiled_supervised_checkpoint_binary_v2(candidate)


def test_binary_replay_rejects_ambiguous_or_mismatched_tensor_descriptors(
    adapter_evidence: dict[str, Any],
) -> None:
    result = _build(adapter_evidence)
    header, frames = _binary_parts(result.checkpoint_bytes)
    duplicate_header = copy.deepcopy(header)
    duplicate_header["payload_frames"][1] = copy.deepcopy(duplicate_header["payload_frames"][0])
    mismatched_header = copy.deepcopy(header)
    mismatched_header["payload_frames"][0]["dtype"] = "float64"

    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_BINARY_TENSOR_DESCRIPTOR_INVALID",
    ):
        decode_and_validate_profiled_supervised_checkpoint_binary_v2(
            _reencode_binary(duplicate_header, frames)
        )
    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_BINARY_TENSOR_DESCRIPTOR_INVALID",
    ):
        decode_and_validate_profiled_supervised_checkpoint_binary_v2(
            _reencode_binary(mismatched_header, frames)
        )


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
            resource_budget_bytes=_STATE_RESOURCE_BUDGET,
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
            resource_budget_bytes=_STATE_RESOURCE_BUDGET,
        )


@pytest.mark.parametrize(
    "malformed_item",
    (
        (b"weight", "float32", (1,), struct.pack("<f", 1.0)),
        ("weight", "float32", None, struct.pack("<f", 1.0)),
        ("weight", "float32", (1,)),
    ),
)
def test_malformed_tensor_input_types_are_normalized_to_checkpoint_error(
    malformed_item: object,
) -> None:
    with pytest.raises(ProfiledSupervisedCheckpointInventoryV1Error):
        capture_profiled_supervised_optimization_state_snapshot_v1(
            stage="BEFORE_OPTIMIZATION",
            captured_at=_BEFORE_CAPTURED_AT,
            model_tensors=(malformed_item,),  # type: ignore[arg-type]
            optimizer_tensors=(),
            resource_budget_bytes=_STATE_RESOURCE_BUDGET,
        )


def test_malformed_snapshot_counts_are_normalized_before_derived_operations() -> None:
    state = _state(after=False)

    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_STATE_ITEM_COUNT_INVALID",
    ):
        replace(state, model_tensor_count=None)  # type: ignore[arg-type]


def test_state_resource_budget_fails_before_any_tensor_factory_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_build(**_kwargs: Any) -> Any:
        raise AssertionError("tensor construction must not run after budget preflight fails")

    monkeypatch.setattr(checkpoint_module, "_build_tensor_item", forbidden_build)
    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_STATE_RESOURCE_BUDGET_EXCEEDED",
    ):
        capture_profiled_supervised_optimization_state_snapshot_v1(
            stage="BEFORE_OPTIMIZATION",
            captured_at=_BEFORE_CAPTURED_AT,
            model_tensors=(("weight", "float32", (1,), struct.pack("<f", 1.0)),),
            optimizer_tensors=(),
            resource_budget_bytes=1,
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
        resource_budget_bytes=state.resource_budget_bytes,
        accounted_resource_bytes=state.accounted_resource_bytes,
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

    assert tensor._factory_seal._owner is tensor
    assert state._factory_seal._owner is state
    assert result._factory_seal._owner is result


def test_checkpoint_resource_budget_fails_before_binary_frame_construction(
    adapter_evidence: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_build(**_kwargs: Any) -> bytes:
        raise AssertionError("binary frame construction must not run after preflight failure")

    monkeypatch.setattr(checkpoint_module, "_build_checkpoint_bytes", forbidden_build)
    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_CHECKPOINT_SERIALIZATION_BUDGET_EXCEEDED",
    ):
        _build(adapter_evidence, serialization_byte_budget=1)


def test_execution_authorization_cannot_transfer_to_equal_unowned_corpus_pair(
    adapter_evidence: dict[str, Any],
) -> None:
    inputs = _inputs(adapter_evidence)
    admitted = admission_support._admit(adapter_evidence)
    unrelated_before = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    unrelated_after = build_authenticated_profiled_optimizer_corpus_v1((admitted,))

    with pytest.raises(
        ProfiledSupervisedCheckpointInventoryV1Error,
        match="PROFILED_OPTIMIZER_EXECUTION_AUTHORIZATION_OWNER_PAIR_MISMATCH",
    ):
        build_authenticated_profiled_supervised_checkpoint_inventory_v1(
            **{
                **inputs,
                "before_corpus": unrelated_before,
                "after_corpus": unrelated_after,
            }
        )


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
        resource_budget_bytes=_STATE_RESOURCE_BUDGET,
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


def test_malformed_checkpoint_collection_members_fail_with_normalized_error(
    adapter_evidence: dict[str, Any],
) -> None:
    result = _build(adapter_evidence)

    for updates in (
        {"admitted_ordinals": None},
        {"logical_profile_selection_mask": None},
        {"checkpoint_byte_count": None},
    ):
        with pytest.raises(
            ProfiledSupervisedCheckpointInventoryV1Error,
            match="PROFILED_CHECKPOINT_INVENTORY_MEMBER_TYPES_INVALID",
        ):
            replace(result, **updates)


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
    source_before = inputs["before_corpus"]
    changed_before = object.__new__(type(source_before))
    for item in dataclass_fields(source_before):
        object.__setattr__(changed_before, item.name, getattr(source_before, item.name))
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
