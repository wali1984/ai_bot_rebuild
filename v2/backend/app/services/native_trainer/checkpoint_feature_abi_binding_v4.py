"""Exact code-owned binding for the deployed checkpoint input ABI.

An input width is not a feature schema.  In particular, two different
446-feature orders both produce a 1,784-value model vector when the four
channels have the same width.  This module binds the deployed checkpoint input
to the exact feature order, configured source order, requirement classes, and
channel layout recorded by :mod:`feature_source_registry_v4`.

The binding is intentionally narrower than checkpoint admission. Building or
verifying it does not authenticate a manifest or weight blob and grants no
trainer, prediction, paper-trading, or live-execution authority. A model may
explicitly declare this expected layout in both checkpoint artifacts, but
width alone never activates that declaration. Genuine runtime enforcement is
deferred until an admitted-tensor capability binds actual tensor bytes,
resolved and configured source labels, per-slot receipts, and temporal clocks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT,
    FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT,
    FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID,
    FEATURE_SOURCE_REGISTRY_V4_SCHEMA_VERSION,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
    FEATURE_SOURCE_REGISTRY_V4_SOURCE_LABEL_COUNT,
    FeatureSourceRegistryV4,
)

CHECKPOINT_FEATURE_ABI_BINDING_V4_SCHEMA_VERSION: Final = (
    "trainer_checkpoint_feature_abi_binding_v4"
)
CHECKPOINT_FEATURE_ABI_BINDING_V4_EVIDENCE_CLASSIFICATION: Final = (
    "CODE_OWNED_EXACT_DEPLOYED_MODEL_INPUT_ABI_BINDING_NO_CHECKPOINT_AUTHORITY"
)
CHECKPOINT_FEATURE_ABI_BINDING_V4_CHANNEL_ORDER: Final = (
    "feature_values",
    "missing_mask",
    "stale_mask",
    "source_availability_mask",
)
CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_DTYPE: Final = "float32"
CHECKPOINT_FEATURE_ABI_BINDING_V4_COORDINATE_ORDER: Final = (
    "CHANNEL_MAJOR_THEN_FEATURE_SLOT_ASCENDING"
)
CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM: Final = 1784
CHECKPOINT_FEATURE_ABI_BINDING_V4_ORDERED_FEATURE_NAMES_SHA256: Final = (
    "7a042357d35c8858885ac09a38e397a446276f758cfd1dca6527422eb2e84a2a"
)
CHECKPOINT_FEATURE_ABI_BINDING_V4_ORDERED_SOURCE_LABELS_SHA256: Final = (
    "a68fb5f7b135bf727f68dd6a947b640f6b10c329df54890c84f2aae7813e90ec"
)
CHECKPOINT_FEATURE_ABI_BINDING_V4_ORDERED_REQUIREMENTS_SHA256: Final = (
    "b99bb94612b19becfeca6cf5a91c9b4f30c39d7a9ce6ee4bee49e693c84ee2ee"
)
CHECKPOINT_FEATURE_ABI_BINDING_V4_ORDERED_COORDINATES_SHA256: Final = (
    "81e5ea22d8143b46bf94b0792ac6e05ed5bb3af5f285777ddfd52c75026a9ef7"
)
CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256: Final = (
    "1a2e089360c42e240fedcba9aef3b82ab6ef2041cd4ab5ddda8b6273f0ad55aa"
)

# Parser/allocation bounds are immutable security invariants, not market,
# strategy, risk, leverage, margin, or admission thresholds.
MAX_CHECKPOINT_FEATURE_ABI_BINDING_V4_BYTES: Final = 32 * 1024
MAX_CHECKPOINT_FEATURE_ABI_BINDING_V4_DEPTH: Final = 5
MAX_CHECKPOINT_FEATURE_ABI_BINDING_V4_NODES: Final = 256

_FALSE_AUTHORITY_FIELDS = (
    "checkpoint_manifest_bound",
    "checkpoint_weight_blob_bound",
    "checkpoint_bytes_authenticated",
    "training_tensor_values_bound",
    "training_tensor_digest_bound",
    "configured_sources_resolved",
    "per_slot_receipts_bound",
    "temporal_clocks_bound",
    "checkpoint_load_authorized",
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "runtime_tensor_identity_or_admission_wired",
)
_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "feature_abi",
        "source_registry",
        "tensor_layout",
        "ordered_feature_names_sha256",
        "ordered_configured_source_labels_sha256",
        "ordered_requirement_classes_sha256",
        "ordered_model_coordinates_sha256",
        "audit_only",
        *_FALSE_AUTHORITY_FIELDS,
        "binding_sha256",
    }
)
class CheckpointFeatureAbiBindingV4Error(ValueError):
    """The supplied input does not equal the exact deployed checkpoint ABI."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise CheckpointFeatureAbiBindingV4Error(*reasons) from None


def _reject_json_constant(_value: str) -> NoReturn:
    _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_CONSTANT_FORBIDDEN")


def _reject_json_float(_value: str) -> NoReturn:
    _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_FLOAT_FORBIDDEN")


def _parse_json_int(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 10:
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_INTEGER_INVALID")
    try:
        return int(value)
    except ValueError:
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_INTEGER_INVALID")


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _snapshot_json_tree(value: object) -> object:
    nodes = 0

    def snapshot(item: object, *, depth: int) -> object:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_CHECKPOINT_FEATURE_ABI_BINDING_V4_NODES:
            _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_NODE_LIMIT_EXCEEDED")
        if depth > MAX_CHECKPOINT_FEATURE_ABI_BINDING_V4_DEPTH:
            _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_DEPTH_LIMIT_EXCEEDED")
        if type(item) is dict:
            mapping = cast(dict[object, object], item)
            try:
                pairs = tuple(mapping.items())
            except RuntimeError:
                _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_MUTATED")
            if len(pairs) != len(mapping):
                _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_MUTATED")
            result: dict[str, object] = {}
            for key, child in pairs:
                if type(key) is not str or not key.isascii():
                    _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_KEY_INVALID")
                result[key] = snapshot(child, depth=depth + 1)
            return result
        if type(item) is list:
            sequence = cast(list[object], item)
            try:
                children = tuple(sequence)
            except RuntimeError:
                _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_MUTATED")
            if len(children) != len(sequence):
                _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_MUTATED")
            return [snapshot(child, depth=depth + 1) for child in children]
        if type(item) is str:
            if not item.isascii():
                _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_TEXT_INVALID")
            return item
        if item is None or type(item) is bool or type(item) is int:
            return item
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_VALUE_TYPE_INVALID")

    return snapshot(value, depth=1)


def _canonical_json_bytes(value: object) -> bytes:
    snapshot = _snapshot_json_tree(value)
    try:
        encoded = json.dumps(
            snapshot,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_CANONICALIZATION_FAILED")
    if not encoded or len(encoded) > MAX_CHECKPOINT_FEATURE_ABI_BINDING_V4_BYTES:
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_SIZE_INVALID")
    return encoded


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _code_owned_sha256(value: object) -> str:
    """Hash large, code-derived inventories not accepted from a caller."""

    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_CODE_INVENTORY_INVALID")
    return hashlib.sha256(encoded).hexdigest()


def _ordered_digest(field_name: str, values: list[str]) -> str:
    return _code_owned_sha256(
        {
            "schema_version": CHECKPOINT_FEATURE_ABI_BINDING_V4_SCHEMA_VERSION,
            field_name: values,
        }
    )


def _coordinate_digest(registry: FeatureSourceRegistryV4) -> str:
    coordinates: list[dict[str, object]] = []
    for channel_index, channel in enumerate(CHECKPOINT_FEATURE_ABI_BINDING_V4_CHANNEL_ORDER):
        for slot in registry.slots:
            coordinates.append(
                {
                    "model_input_ordinal": (channel_index * registry.slot_count + slot.ordinal),
                    "channel": channel,
                    "feature_ordinal": slot.ordinal,
                    "feature_name": slot.feature_name,
                    "configured_source_label": slot.configured_source_label,
                    "requirement_class": slot.requirement_class,
                }
            )
    return _code_owned_sha256(
        {
            "schema_version": CHECKPOINT_FEATURE_ABI_BINDING_V4_SCHEMA_VERSION,
            "coordinate_order": (CHECKPOINT_FEATURE_ABI_BINDING_V4_COORDINATE_ORDER),
            "coordinates": coordinates,
        }
    )


def _binding_material(registry: FeatureSourceRegistryV4) -> dict[str, object]:
    if type(registry) is not FeatureSourceRegistryV4:
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_REGISTRY_TYPE_INVALID")
    if (
        registry.schema_version != FEATURE_SOURCE_REGISTRY_V4_SCHEMA_VERSION
        or registry.registry_sha256 != FEATURE_SOURCE_REGISTRY_V4_SHA256
        or registry.abi_schema_version != FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION
        or registry.abi_sha256 != FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256
        or registry.feature_requirement_policy_id
        != FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID
        or registry.slot_count != FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
        or registry.required_slot_count != FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT
        or registry.optional_event_dependent_slot_count
        != FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT
        or registry.source_label_count != FEATURE_SOURCE_REGISTRY_V4_SOURCE_LABEL_COUNT
    ):
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_REGISTRY_MISMATCH")

    feature_names = [slot.feature_name for slot in registry.slots]
    source_labels = [slot.configured_source_label for slot in registry.slots]
    requirements = [slot.requirement_class for slot in registry.slots]
    feature_names_sha256 = _ordered_digest("ordered_feature_names", feature_names)
    source_labels_sha256 = _ordered_digest("ordered_configured_source_labels", source_labels)
    requirements_sha256 = _ordered_digest("ordered_requirement_classes", requirements)
    coordinates_sha256 = _coordinate_digest(registry)
    if (
        feature_names_sha256 != CHECKPOINT_FEATURE_ABI_BINDING_V4_ORDERED_FEATURE_NAMES_SHA256
        or source_labels_sha256 != CHECKPOINT_FEATURE_ABI_BINDING_V4_ORDERED_SOURCE_LABELS_SHA256
        or requirements_sha256 != CHECKPOINT_FEATURE_ABI_BINDING_V4_ORDERED_REQUIREMENTS_SHA256
        or coordinates_sha256 != CHECKPOINT_FEATURE_ABI_BINDING_V4_ORDERED_COORDINATES_SHA256
    ):
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_PINNED_ORDER_MISMATCH")

    channel_spans = [
        {
            "channel": channel,
            "start_inclusive": channel_index * registry.slot_count,
            "end_exclusive": (channel_index + 1) * registry.slot_count,
            "slot_count": registry.slot_count,
            "model_dtype": CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_DTYPE,
        }
        for channel_index, channel in enumerate(CHECKPOINT_FEATURE_ABI_BINDING_V4_CHANNEL_ORDER)
    ]
    model_input_dim = len(CHECKPOINT_FEATURE_ABI_BINDING_V4_CHANNEL_ORDER) * registry.slot_count
    if model_input_dim != CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM:
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM_MISMATCH")
    return {
        "schema_version": CHECKPOINT_FEATURE_ABI_BINDING_V4_SCHEMA_VERSION,
        "evidence_classification": (CHECKPOINT_FEATURE_ABI_BINDING_V4_EVIDENCE_CLASSIFICATION),
        "feature_abi": {
            "schema_version": registry.abi_schema_version,
            "sha256": registry.abi_sha256,
            "feature_requirement_policy_id": (registry.feature_requirement_policy_id),
            "slot_count": registry.slot_count,
            "required_slot_count": registry.required_slot_count,
            "optional_event_dependent_slot_count": (registry.optional_event_dependent_slot_count),
        },
        "source_registry": {
            "schema_version": registry.schema_version,
            "sha256": registry.registry_sha256,
            "source_label_count": registry.source_label_count,
        },
        "tensor_layout": {
            "channel_order": list(CHECKPOINT_FEATURE_ABI_BINDING_V4_CHANNEL_ORDER),
            "channel_count": len(CHECKPOINT_FEATURE_ABI_BINDING_V4_CHANNEL_ORDER),
            "per_channel_slot_count": registry.slot_count,
            "model_input_dim": model_input_dim,
            "model_dtype": CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_DTYPE,
            "coordinate_order": (CHECKPOINT_FEATURE_ABI_BINDING_V4_COORDINATE_ORDER),
            "channel_spans": channel_spans,
        },
        "ordered_feature_names_sha256": feature_names_sha256,
        "ordered_configured_source_labels_sha256": source_labels_sha256,
        "ordered_requirement_classes_sha256": requirements_sha256,
        "ordered_model_coordinates_sha256": coordinates_sha256,
        "audit_only": True,
        **{field_name: False for field_name in _FALSE_AUTHORITY_FIELDS},
    }


def deployed_checkpoint_feature_abi_binding_v4() -> dict[str, object]:
    """Return a detached exact binding for the deployed 446 x 4 input ABI."""

    material = _binding_material(FEATURE_SOURCE_REGISTRY_V4)
    binding_sha256 = _sha256_json(material)
    if binding_sha256 != CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256:
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256_MISMATCH")
    return {**material, "binding_sha256": binding_sha256}


def canonical_deployed_checkpoint_feature_abi_binding_v4_json() -> str:
    """Return the binding as strict, canonical ASCII JSON."""

    return _canonical_json_bytes(deployed_checkpoint_feature_abi_binding_v4()).decode("ascii")


def _parse_binding(value: object) -> dict[str, object]:
    if type(value) is dict:
        return cast(dict[str, object], _snapshot_json_tree(value))
    if type(value) is str:
        try:
            raw = value.encode("ascii", errors="strict")
        except UnicodeEncodeError:
            _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_INVALID")
    elif type(value) is bytes:
        raw = bytes(value)
    else:
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_INPUT_TYPE_INVALID")
    if not raw or len(raw) > MAX_CHECKPOINT_FEATURE_ABI_BINDING_V4_BYTES:
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_INVALID")
    try:
        text = raw.decode("ascii", errors="strict")
        parsed = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_json_constant,
            parse_float=_reject_json_float,
            parse_int=_parse_json_int,
        )
    except CheckpointFeatureAbiBindingV4Error:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, OverflowError, RecursionError, ValueError):
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_INVALID")
    if type(parsed) is not dict:
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_ROOT_NOT_EXACT_OBJECT")
    detached = cast(dict[str, object], _snapshot_json_tree(parsed))
    if not hmac.compare_digest(_canonical_json_bytes(detached), raw):
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_JSON_NOT_CANONICAL")
    return detached


def verify_deployed_checkpoint_feature_abi_binding_v4(
    value: object,
    *,
    checkpoint_input_dim: object,
) -> Mapping[str, object]:
    """Verify exact deployed layout without authorizing a checkpoint load."""

    if (
        type(checkpoint_input_dim) is not int
        or checkpoint_input_dim != CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM
    ):
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_CHECKPOINT_INPUT_DIM_MISMATCH")
    supplied = _parse_binding(value)
    if frozenset(supplied) != _ROOT_FIELDS:
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_FIELD_SET_MISMATCH")
    supplied_digest = supplied.get("binding_sha256")
    material = {key: item for key, item in supplied.items() if key != "binding_sha256"}
    if type(supplied_digest) is not str or not hmac.compare_digest(
        _sha256_json(material), supplied_digest
    ):
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_DIGEST_INVALID")
    expected = deployed_checkpoint_feature_abi_binding_v4()
    if not hmac.compare_digest(
        _canonical_json_bytes(supplied),
        _canonical_json_bytes(expected),
    ):
        _fail("CHECKPOINT_FEATURE_ABI_BINDING_V4_DEPLOYED_ABI_MISMATCH")
    return MappingProxyType(
        {
            "schema_version": CHECKPOINT_FEATURE_ABI_BINDING_V4_SCHEMA_VERSION,
            "binding_sha256": supplied_digest,
            "checkpoint_input_dim": checkpoint_input_dim,
            "checkpoint_input_dim_verified": True,
            "feature_order_verified": True,
            "configured_source_order_verified": True,
            "requirement_order_verified": True,
            "tensor_channel_layout_verified": True,
            "deployed_registry_exact_match_verified": True,
            "audit_only": True,
            **{field_name: False for field_name in _FALSE_AUTHORITY_FIELDS},
        }
    )


__all__ = [
    "CHECKPOINT_FEATURE_ABI_BINDING_V4_CHANNEL_ORDER",
    "CHECKPOINT_FEATURE_ABI_BINDING_V4_COORDINATE_ORDER",
    "CHECKPOINT_FEATURE_ABI_BINDING_V4_EVIDENCE_CLASSIFICATION",
    "CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_DTYPE",
    "CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM",
    "CHECKPOINT_FEATURE_ABI_BINDING_V4_ORDERED_COORDINATES_SHA256",
    "CHECKPOINT_FEATURE_ABI_BINDING_V4_ORDERED_FEATURE_NAMES_SHA256",
    "CHECKPOINT_FEATURE_ABI_BINDING_V4_ORDERED_REQUIREMENTS_SHA256",
    "CHECKPOINT_FEATURE_ABI_BINDING_V4_ORDERED_SOURCE_LABELS_SHA256",
    "CHECKPOINT_FEATURE_ABI_BINDING_V4_SCHEMA_VERSION",
    "CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256",
    "CheckpointFeatureAbiBindingV4Error",
    "canonical_deployed_checkpoint_feature_abi_binding_v4_json",
    "deployed_checkpoint_feature_abi_binding_v4",
    "verify_deployed_checkpoint_feature_abi_binding_v4",
]
