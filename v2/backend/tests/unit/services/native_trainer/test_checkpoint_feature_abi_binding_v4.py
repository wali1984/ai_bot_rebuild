from __future__ import annotations

import json
from copy import copy, deepcopy
from types import MappingProxyType
from typing import Any, cast

import pytest

from v2.backend.app.services.native_trainer import (
    checkpoint_feature_abi_binding_v4 as binding_module,
)
from v2.backend.app.services.native_trainer.checkpoint_feature_abi_binding_v4 import (
    CHECKPOINT_FEATURE_ABI_BINDING_V4_CHANNEL_ORDER,
    CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM,
    CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256,
    CheckpointFeatureAbiBindingV4Error,
    canonical_deployed_checkpoint_feature_abi_binding_v4_json,
    deployed_checkpoint_feature_abi_binding_v4,
    verify_deployed_checkpoint_feature_abi_binding_v4,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
)


def _rehash(record: dict[str, Any]) -> None:
    material = {key: value for key, value in record.items() if key != "binding_sha256"}
    record["binding_sha256"] = binding_module._sha256_json(material)


def test_binding_pins_every_model_coordinate_not_only_width() -> None:
    binding = deployed_checkpoint_feature_abi_binding_v4()
    layout = cast(dict[str, Any], binding["tensor_layout"])

    assert binding["binding_sha256"] == CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256
    assert layout["model_input_dim"] == CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM
    assert layout["channel_order"] == list(CHECKPOINT_FEATURE_ABI_BINDING_V4_CHANNEL_ORDER)
    assert layout["channel_spans"] == [
        {
            "channel": "feature_values",
            "start_inclusive": 0,
            "end_exclusive": 446,
            "slot_count": 446,
            "model_dtype": "float32",
        },
        {
            "channel": "missing_mask",
            "start_inclusive": 446,
            "end_exclusive": 892,
            "slot_count": 446,
            "model_dtype": "float32",
        },
        {
            "channel": "stale_mask",
            "start_inclusive": 892,
            "end_exclusive": 1338,
            "slot_count": 446,
            "model_dtype": "float32",
        },
        {
            "channel": "source_availability_mask",
            "start_inclusive": 1338,
            "end_exclusive": 1784,
            "slot_count": 446,
            "model_dtype": "float32",
        },
    ]
    assert (
        len(
            {
                binding["ordered_feature_names_sha256"],
                binding["ordered_configured_source_labels_sha256"],
                binding["ordered_requirement_classes_sha256"],
                binding["ordered_model_coordinates_sha256"],
            }
        )
        == 4
    )


def test_same_width_reordered_feature_registry_fails_pinned_order() -> None:
    slots = list(FEATURE_SOURCE_REGISTRY_V4.slots)
    slots[0], slots[1] = slots[1], slots[0]
    # Simulate hostile in-memory corruption after the registry factory ran.
    # Width and the nominal pinned registry digest remain unchanged.
    same_width_reordered = copy(FEATURE_SOURCE_REGISTRY_V4)
    object.__setattr__(same_width_reordered, "slots", tuple(slots))

    with pytest.raises(
        CheckpointFeatureAbiBindingV4Error,
        match="PINNED_ORDER_MISMATCH",
    ):
        binding_module._binding_material(same_width_reordered)


def test_canonical_round_trip_verifies_but_grants_no_authority() -> None:
    canonical = canonical_deployed_checkpoint_feature_abi_binding_v4_json()
    result = verify_deployed_checkpoint_feature_abi_binding_v4(
        canonical,
        checkpoint_input_dim=1784,
    )

    assert isinstance(result, MappingProxyType)
    assert result["deployed_registry_exact_match_verified"] is True
    assert result["tensor_channel_layout_verified"] is True
    for field_name in binding_module._FALSE_AUTHORITY_FIELDS:
        assert result[field_name] is False
    assert (
        json.dumps(
            json.loads(canonical),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        == canonical
    )


@pytest.mark.parametrize("input_dim", [None, True, 0, 446, 1783, 1785, "1784"])
def test_width_alone_never_proves_compatibility(input_dim: object) -> None:
    with pytest.raises(
        CheckpointFeatureAbiBindingV4Error,
        match="CHECKPOINT_INPUT_DIM_MISMATCH",
    ):
        verify_deployed_checkpoint_feature_abi_binding_v4(
            deployed_checkpoint_feature_abi_binding_v4(),
            checkpoint_input_dim=input_dim,
        )


def test_missing_binding_fails_closed() -> None:
    with pytest.raises(
        CheckpointFeatureAbiBindingV4Error,
        match="FIELD_SET_MISMATCH",
    ):
        verify_deployed_checkpoint_feature_abi_binding_v4(
            {},
            checkpoint_input_dim=1784,
        )


@pytest.mark.parametrize(
    "ordered_digest_field",
    [
        "ordered_feature_names_sha256",
        "ordered_configured_source_labels_sha256",
        "ordered_requirement_classes_sha256",
    ],
)
def test_same_width_name_source_or_requirement_migration_changes_binding(
    ordered_digest_field: str,
) -> None:
    changed = deepcopy(deployed_checkpoint_feature_abi_binding_v4())
    changed[ordered_digest_field] = "0" * 64
    _rehash(changed)
    with pytest.raises(
        CheckpointFeatureAbiBindingV4Error,
        match="DEPLOYED_ABI_MISMATCH",
    ):
        verify_deployed_checkpoint_feature_abi_binding_v4(
            changed,
            checkpoint_input_dim=1784,
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "checkpoint_manifest_bound",
        "checkpoint_weight_blob_bound",
        "checkpoint_load_authorized",
        "trainer_admission_authorized",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
        "runtime_tensor_identity_or_admission_wired",
    ],
)
def test_coherently_rehashed_authority_claim_is_rejected(field_name: str) -> None:
    forged = deepcopy(deployed_checkpoint_feature_abi_binding_v4())
    forged[field_name] = True
    _rehash(forged)

    with pytest.raises(
        CheckpointFeatureAbiBindingV4Error,
        match="DEPLOYED_ABI_MISMATCH",
    ):
        verify_deployed_checkpoint_feature_abi_binding_v4(
            forged,
            checkpoint_input_dim=1784,
        )


def test_noncanonical_duplicate_float_and_non_builtin_inputs_are_rejected() -> None:
    canonical = canonical_deployed_checkpoint_feature_abi_binding_v4_json()
    noncanonical = canonical.replace(",", ", ", 1)
    with pytest.raises(
        CheckpointFeatureAbiBindingV4Error,
        match="JSON_NOT_CANONICAL",
    ):
        verify_deployed_checkpoint_feature_abi_binding_v4(
            noncanonical,
            checkpoint_input_dim=1784,
        )

    duplicate = canonical.replace(
        '"audit_only":true',
        '"audit_only":true,"audit_only":true',
        1,
    )
    with pytest.raises(
        CheckpointFeatureAbiBindingV4Error,
        match="DUPLICATE_JSON_KEY",
    ):
        verify_deployed_checkpoint_feature_abi_binding_v4(
            duplicate,
            checkpoint_input_dim=1784,
        )

    floating = canonical.replace('"channel_count":4', '"channel_count":4.0', 1)
    with pytest.raises(
        CheckpointFeatureAbiBindingV4Error,
        match="JSON_FLOAT_FORBIDDEN",
    ):
        verify_deployed_checkpoint_feature_abi_binding_v4(
            floating,
            checkpoint_input_dim=1784,
        )

    class DictSubclass(dict[str, object]):
        pass

    with pytest.raises(
        CheckpointFeatureAbiBindingV4Error,
        match="INPUT_TYPE_INVALID",
    ):
        verify_deployed_checkpoint_feature_abi_binding_v4(
            DictSubclass(deployed_checkpoint_feature_abi_binding_v4()),
            checkpoint_input_dim=1784,
        )


def test_verifier_result_is_scalar_only_and_detached() -> None:
    supplied = deployed_checkpoint_feature_abi_binding_v4()
    result = verify_deployed_checkpoint_feature_abi_binding_v4(
        supplied,
        checkpoint_input_dim=1784,
    )
    supplied["binding_sha256"] = "0" * 64

    assert result["binding_sha256"] == CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256
    assert all(item is None or type(item) in {str, int, bool} for item in result.values())


def test_binding_explicitly_denies_tensor_provenance_and_runtime_authority() -> None:
    binding = deployed_checkpoint_feature_abi_binding_v4()
    denied = {
        "training_tensor_values_bound",
        "training_tensor_digest_bound",
        "configured_sources_resolved",
        "per_slot_receipts_bound",
        "temporal_clocks_bound",
        "trainer_admission_authorized",
        "prediction_authorized",
        "runtime_tensor_identity_or_admission_wired",
    }

    assert binding["audit_only"] is True
    assert all(binding[field_name] is False for field_name in denied)
    assert not hasattr(
        binding_module,
        "verified_checkpoint_feature_abi_identity_v4_from_tensor_semantics",
    )
