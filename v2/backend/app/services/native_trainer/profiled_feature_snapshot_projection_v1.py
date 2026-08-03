"""Unwired profile-aware projection over physical ledger-v3 evidence.

This module does not create a second persistence engine.  It freezes a
39-value physical evidence record with the existing durable feature snapshot
ledger v3 contract, then validates and projects only the 35 model features
selected by ``OHLCV_BOOTSTRAP_5M_1H_V1`` into their exact deployed 446-slot
ordinals.  Four cost inputs remain physical, receipt-bound label evidence and
are never model inputs.

Profile-disabled logical slots are encoded as zero with missing=0, stale=0,
availability=0, and no receipt root.  A separately authenticated selection
mask distinguishes that encoding from missing or unavailable observations.
Nothing here is runtime-wired or grants trainer, prediction, paper, or live
authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.adaptive_ohlcv_feature_selection_profile_v1 import (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SCHEMA_VERSION,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
    PROFILE_DISABLED,
    adaptive_ohlcv_feature_selection_profile_v1_contract,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION,
    PROVENANCE_CANONICAL_V3,
    FeatureSnapshotValidationError,
    build_feature_snapshot_record,
    build_source_read_receipt,
    validate_feature_snapshot_record,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
)

PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_SCHEMA_VERSION: Final = (
    "profiled_feature_snapshot_projection_v1"
)
PROFILED_FEATURE_SNAPSHOT_PHYSICAL_LINEAGE_V1_SCHEMA_VERSION: Final = (
    "profiled_feature_snapshot_physical_lineage_v1"
)
PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_CLASSIFICATION: Final = (
    "UNWIRED_PROFILE_BOUND_PHYSICAL_V3_TO_LOGICAL_446_PROJECTION"
)
PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_STATUS: Final = (
    "VALIDATED_PHYSICAL_EVIDENCE_LOGICAL_PROJECTION_NO_RUNTIME_AUTHORITY"
)
PROFILED_FEATURE_SNAPSHOT_UNWIRED_REASON: Final = (
    "PROFILED_PROJECTION_RUNTIME_UNWIRED_NO_TRAINER_AUTHORITY"
)

AUXILIARY_LABEL_ONLY_FEATURE_NAMES: Final = (
    "fee_bps",
    "spread_bps",
    "expected_slippage_bps",
    "expected_funding_bps",
)
PHYSICAL_ORDERED_FEATURE_NAMES: Final = (
    *ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.enabled_feature_names,
    *AUXILIARY_LABEL_ONLY_FEATURE_NAMES,
)
PHYSICAL_MODEL_FEATURE_COUNT: Final = 35
PHYSICAL_AUXILIARY_FEATURE_COUNT: Final = 4
PHYSICAL_FEATURE_COUNT: Final = 39
PHYSICAL_FEATURE_ROLE_MODEL_INPUT: Final = "MODEL_INPUT"
PHYSICAL_FEATURE_ROLE_LABEL_ONLY_AUXILIARY: Final = "LABEL_ONLY_AUXILIARY"
PHYSICAL_ORDERED_FEATURE_ROLES: Final = (
    *(PHYSICAL_FEATURE_ROLE_MODEL_INPUT for _ in range(PHYSICAL_MODEL_FEATURE_COUNT)),
    *(PHYSICAL_FEATURE_ROLE_LABEL_ONLY_AUXILIARY for _ in range(PHYSICAL_AUXILIARY_FEATURE_COUNT)),
)
LOGICAL_PROFILE_SELECTION_MASK: Final = tuple(
    1 if disposition != PROFILE_DISABLED else 0
    for disposition in (ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.ordered_slot_dispositions)
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:" r"[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_RESULT_CONSTRUCTION_TOKEN = object()
_PHYSICAL_RECORD_TIMEFRAME = "5m"
_MODEL_SCALAR_PAYLOAD_TYPE = "PROFILED_MODEL_FLOAT32_SCALAR_V1"
_AUXILIARY_SCALAR_PAYLOAD_TYPE = "PROFILED_LABEL_AUX_FLOAT32_SCALAR_V1"
_MODEL_SCALAR_SCHEMA_VERSION = "profiled_model_scalar_material_v1"
_AUXILIARY_SCALAR_SCHEMA_VERSION = "profiled_auxiliary_scalar_material_v1"
_TRANSFORM_CONTRACT_SCHEMA_VERSION = "profiled_transform_contract_v1"
_PROJECTION_RESERVED_LINEAGE_FIELDS = frozenset(
    {
        "feature_abi_sha256",
        "ordered_feature_source_labels",
        "source_availability_mask",
        "feature_source_receipt_sha256s",
        "feature_source_bindings_sha256",
        "source_read_receipt_sha256s",
        "source_receipt_graph_sha256",
        "model_vector_sha256",
    }
)


class ProfiledFeatureSnapshotProjectionV1Error(RuntimeError):
    """Physical evidence or a logical projection violates the pinned profile."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledFeatureSnapshotProjectionV1Error(*reasons) from None


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeEncodeError,
        ValueError,
    ):
        _fail("PROFILED_PROJECTION_CANONICAL_ENCODING_INVALID")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _float32(value: object, *, reason: str) -> tuple[float, str]:
    if type(value) not in {int, float}:
        _fail(reason)
    try:
        parsed = float(cast(int | float, value))
        packed = struct.pack("!f", parsed)
        runtime_value = float(struct.unpack("!f", packed)[0])
    except (OverflowError, struct.error, TypeError, ValueError):
        _fail(reason)
    if not math.isfinite(parsed) or not math.isfinite(runtime_value):
        _fail(reason)
    if parsed != 0.0 and runtime_value == 0.0:
        _fail(reason)
    return (0.0 if runtime_value == 0.0 else runtime_value), packed.hex()


def _clock(value: object, *, reason: str) -> tuple[str, datetime]:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        _fail(reason)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        _fail(reason)
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if canonical != value:
        _fail(reason)
    return canonical, parsed


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _capture_source_label(timeframe: str) -> str:
    if timeframe not in {"5m", "1h"}:
        _fail("PROFILED_PROJECTION_PHYSICAL_TIMEFRAME_INVALID")
    return f"profiled:ohlcv_bootstrap:capture:{timeframe}"


def _capture_payload_type(timeframe: str) -> str:
    if timeframe not in {"5m", "1h"}:
        _fail("PROFILED_PROJECTION_PHYSICAL_TIMEFRAME_INVALID")
    return f"CANONICAL_CLOSED_OHLCV_WINDOW_{timeframe.upper()}_V1"


def _model_source_label(feature_name: str) -> str:
    return f"profiled:ohlcv_bootstrap:model:{feature_name}"


def _auxiliary_source_label(feature_name: str) -> str:
    return f"profiled:ohlcv_bootstrap:aux:{feature_name}"


_PROFILE = ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1
_LOGICAL_ORDERED_FEATURE_NAMES = tuple(
    slot.feature_name for slot in FEATURE_SOURCE_REGISTRY_V4.slots
)
_TRANSFORM_BY_FEATURE = {
    transform.feature_name: (family, transform)
    for family in _PROFILE.timeframe_finality_transform_contracts
    for transform in family.transforms
}
_ENABLED_ORDINAL_MAPPING = tuple(
    {
        "physical_ordinal": physical_ordinal,
        "logical_base_abi_ordinal": logical_ordinal,
        "feature_name": feature_name,
    }
    for physical_ordinal, (logical_ordinal, feature_name) in enumerate(
        zip(_PROFILE.enabled_slot_ordinals, _PROFILE.enabled_feature_names, strict=True)
    )
)
_PHYSICAL_FEATURE_ROLES_MATERIAL = tuple(
    {
        "physical_ordinal": physical_ordinal,
        "feature_name": feature_name,
        "role": PHYSICAL_ORDERED_FEATURE_ROLES[physical_ordinal],
        "logical_base_abi_ordinal": (
            _PROFILE.enabled_slot_ordinals[physical_ordinal]
            if physical_ordinal < PHYSICAL_MODEL_FEATURE_COUNT
            else None
        ),
    }
    for physical_ordinal, feature_name in enumerate(PHYSICAL_ORDERED_FEATURE_NAMES)
)

_PROJECTION_IMPLEMENTATION_MATERIAL = {
    "schema_version": PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_SCHEMA_VERSION,
    "operation": "PHYSICAL_39_TO_PROFILE_SELECTED_LOGICAL_446_V1",
    "model_mapping": "EXACT_PROFILE_ENABLED_ORDINALS_ONLY",
    "auxiliary_policy": "FOUR_LABEL_ONLY_INPUTS_EXCLUDED_FROM_MODEL_PROJECTION",
    "disabled_encoding": {
        "feature_value": 0.0,
        "missing_mask": 0,
        "stale_mask": 0,
        "source_availability_mask": 0,
        "source_receipt_sha256": None,
        "selection_mask": 0,
    },
    "selected_encoding": {
        "missing_mask": 0,
        "stale_mask": 0,
        "source_availability_mask": 1,
        "selection_mask": 1,
    },
}
PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_IMPLEMENTATION_SHA256: Final = _canonical_sha256(
    _PROJECTION_IMPLEMENTATION_MATERIAL
)
_PROJECTION_CONFIGURATION_MATERIAL = {
    "schema_version": PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_SCHEMA_VERSION,
    "profile_id": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
    "profile_sha256": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
    "base_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    "logical_profile_selection_mask": list(LOGICAL_PROFILE_SELECTION_MASK),
    "enabled_ordinal_mapping": list(_ENABLED_ORDINAL_MAPPING),
    "physical_feature_roles": list(_PHYSICAL_FEATURE_ROLES_MATERIAL),
}
PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_CONFIGURATION_SHA256: Final = _canonical_sha256(
    _PROJECTION_CONFIGURATION_MATERIAL
)
PROFILED_FEATURE_SNAPSHOT_LOGICAL_SELECTION_MASK_SHA256: Final = _canonical_sha256(
    list(LOGICAL_PROFILE_SELECTION_MASK)
)


def _model_transform_contract(feature_name: str) -> dict[str, Any]:
    item = _TRANSFORM_BY_FEATURE.get(feature_name)
    if item is None:
        _fail("PROFILED_PROJECTION_MODEL_FEATURE_NOT_ENABLED")
    family, transform = item
    return {
        "schema_version": _TRANSFORM_CONTRACT_SCHEMA_VERSION,
        "profile_id": _PROFILE.profile_id,
        "profile_sha256": _PROFILE.profile_sha256,
        "base_abi_ordinal": transform.ordinal,
        "feature_name": feature_name,
        "family_id": family.family_id,
        "physical_timeframe": family.physical_timeframe,
        "transform_id": transform.transform_id,
        "input_fields": list(transform.input_fields),
        "minimum_closed_source_rows": transform.minimum_closed_source_rows,
        "family_minimum_closed_source_rows": (family.family_minimum_closed_source_rows),
        "finality_rule": family.finality_rule,
        "proxy_higher_timeframe_allowed": False,
    }


def _model_configuration_contract(
    *,
    feature_name: str,
    capture_receipt_sha256: str,
) -> dict[str, Any]:
    physical_ordinal = PHYSICAL_ORDERED_FEATURE_NAMES.index(feature_name)
    return {
        "schema_version": _TRANSFORM_CONTRACT_SCHEMA_VERSION,
        "profile_id": _PROFILE.profile_id,
        "profile_sha256": _PROFILE.profile_sha256,
        "physical_ordinal": physical_ordinal,
        "logical_base_abi_ordinal": _PROFILE.enabled_slot_ordinals[physical_ordinal],
        "feature_name": feature_name,
        "source_capture_receipt_sha256": capture_receipt_sha256,
        "output_source_label": _model_source_label(feature_name),
        "scalar_encoding": "IEEE754_BINARY32_BIG_ENDIAN_HEX",
    }


def _model_scalar_material(
    *,
    feature_name: str,
    feature_value: object,
    feature_snapshot_id: str,
    capture_receipt_sha256: str,
) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    _runtime_value, value_hex = _float32(
        feature_value,
        reason="PROFILED_PROJECTION_MODEL_VALUE_INVALID",
    )
    transform_contract = _model_transform_contract(feature_name)
    configuration_contract = _model_configuration_contract(
        feature_name=feature_name,
        capture_receipt_sha256=capture_receipt_sha256,
    )
    derivation_material = {
        "schema_version": FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION,
        "producer_id": "profiled_feature_snapshot_projection_v1",
        "producer_version": "physical_model_scalar_transform_v1",
        "transform_sha256": _canonical_sha256(transform_contract),
        "configuration_sha256": _canonical_sha256(configuration_contract),
    }
    scalar_material = {
        "schema_version": _MODEL_SCALAR_SCHEMA_VERSION,
        "profile_id": _PROFILE.profile_id,
        "profile_sha256": _PROFILE.profile_sha256,
        "feature_snapshot_id": feature_snapshot_id,
        "physical_ordinal": PHYSICAL_ORDERED_FEATURE_NAMES.index(feature_name),
        "logical_base_abi_ordinal": transform_contract["base_abi_ordinal"],
        "feature_name": feature_name,
        "physical_timeframe": transform_contract["physical_timeframe"],
        "value_float32_be_hex": value_hex,
        "capture_receipt_sha256": capture_receipt_sha256,
        "transform_sha256": derivation_material["transform_sha256"],
        "configuration_sha256": derivation_material["configuration_sha256"],
    }
    return scalar_material, _canonical_bytes(scalar_material), derivation_material


def _auxiliary_scalar_material(
    *,
    feature_name: str,
    feature_value: object,
    feature_snapshot_id: str,
) -> tuple[dict[str, Any], bytes]:
    if feature_name not in AUXILIARY_LABEL_ONLY_FEATURE_NAMES:
        _fail("PROFILED_PROJECTION_AUXILIARY_FEATURE_INVALID")
    _runtime_value, value_hex = _float32(
        feature_value,
        reason="PROFILED_PROJECTION_AUXILIARY_VALUE_INVALID",
    )
    physical_ordinal = PHYSICAL_ORDERED_FEATURE_NAMES.index(feature_name)
    material = {
        "schema_version": _AUXILIARY_SCALAR_SCHEMA_VERSION,
        "profile_id": _PROFILE.profile_id,
        "profile_sha256": _PROFILE.profile_sha256,
        "feature_snapshot_id": feature_snapshot_id,
        "physical_ordinal": physical_ordinal,
        "feature_name": feature_name,
        "role": PHYSICAL_FEATURE_ROLE_LABEL_ONLY_AUXILIARY,
        "excluded_from_model_projection": True,
        "value_float32_be_hex": value_hex,
    }
    return material, _canonical_bytes(material)


def build_profiled_ohlcv_capture_receipt_v1(
    *,
    physical_timeframe: str,
    payload_sha256: str,
    payload_byte_count: int,
    latest_finalized_close_time: str,
    available_at: str,
    consumer_observed_at: str,
    read_locator: str,
    read_locator_version: str,
) -> dict[str, Any]:
    """Build one exact physical 5m or true-1h closed-window receipt."""

    if physical_timeframe not in {"5m", "1h"}:
        _fail("PROFILED_PROJECTION_PHYSICAL_TIMEFRAME_INVALID")
    try:
        return build_source_read_receipt(
            source_label=_capture_source_label(physical_timeframe),
            payload_type=_capture_payload_type(physical_timeframe),
            payload_sha256=payload_sha256,
            payload_byte_count=payload_byte_count,
            event_time=latest_finalized_close_time,
            available_at=available_at,
            consumer_observed_at=consumer_observed_at,
            feature_cutoff=latest_finalized_close_time,
            read_locator_type="FILE_CONTENT_ADDRESS",
            read_locator=read_locator,
            read_locator_version=read_locator_version,
            finality_type="CLOSED_INTERVAL",
            finality_cutoff=latest_finalized_close_time,
            finality_verified_at=available_at,
            finality_verifier=(
                f"profiled_feature_snapshot_projection_v1_{physical_timeframe}_finality"
            ),
        )
    except FeatureSnapshotValidationError as exc:
        raise ProfiledFeatureSnapshotProjectionV1Error(
            "PROFILED_PROJECTION_CAPTURE_RECEIPT_INVALID"
        ) from exc


def build_profiled_model_feature_receipt_v1(
    *,
    feature_name: str,
    feature_value: int | float,
    feature_snapshot_id: str,
    capture_receipt: Mapping[str, Any],
    available_at: str,
    consumer_observed_at: str,
    read_locator: str,
    read_locator_version: str,
) -> dict[str, Any]:
    """Build one receipt-bound model scalar over its 5m or true-1h capture."""

    if type(capture_receipt) is not dict:
        _fail("PROFILED_PROJECTION_CAPTURE_RECEIPT_NOT_EXACT_DICT")
    capture_sha256 = capture_receipt.get("receipt_sha256")
    if not _valid_sha256(capture_sha256):
        _fail("PROFILED_PROJECTION_CAPTURE_RECEIPT_SHA256_INVALID")
    transform_contract = _model_transform_contract(feature_name)
    expected_timeframe = cast(str, transform_contract["physical_timeframe"])
    if capture_receipt.get("source_label") != _capture_source_label(
        expected_timeframe
    ) or capture_receipt.get("payload_type") != _capture_payload_type(expected_timeframe):
        _fail("PROFILED_PROJECTION_CAPTURE_TIMEFRAME_BINDING_INVALID")
    scalar_material, scalar_bytes, derivation_material = _model_scalar_material(
        feature_name=feature_name,
        feature_value=feature_value,
        feature_snapshot_id=feature_snapshot_id,
        capture_receipt_sha256=cast(str, capture_sha256),
    )
    try:
        receipt = build_source_read_receipt(
            source_label=_model_source_label(feature_name),
            payload_type=_MODEL_SCALAR_PAYLOAD_TYPE,
            payload_sha256=hashlib.sha256(scalar_bytes).hexdigest(),
            payload_byte_count=len(scalar_bytes),
            event_time=cast(str, capture_receipt["event_time"]),
            available_at=available_at,
            consumer_observed_at=consumer_observed_at,
            feature_cutoff=cast(str, capture_receipt["feature_cutoff"]),
            read_locator_type="IN_MEMORY_IMMUTABLE_OBJECT",
            read_locator=read_locator,
            read_locator_version=read_locator_version,
            finality_type="VERSIONED_SNAPSHOT",
            finality_cutoff=available_at,
            finality_verified_at=available_at,
            finality_verifier="profiled_feature_snapshot_projection_v1_transform",
            receipt_kind="COMPOSITE_DERIVATION",
            child_read_bindings=[
                {
                    "input_role": f"canonical_closed_{expected_timeframe}_capture",
                    "receipt_sha256": cast(str, capture_sha256),
                }
            ],
            derivation_material=derivation_material,
        )
    except FeatureSnapshotValidationError as exc:
        raise ProfiledFeatureSnapshotProjectionV1Error(
            "PROFILED_PROJECTION_MODEL_RECEIPT_INVALID"
        ) from exc
    if receipt.get("payload_sha256") != _canonical_sha256(scalar_material):
        _fail("PROFILED_PROJECTION_MODEL_SCALAR_BINDING_INVALID")
    return receipt


def build_profiled_auxiliary_receipt_v1(
    *,
    feature_name: str,
    feature_value: int | float,
    feature_snapshot_id: str,
    event_time: str,
    available_at: str,
    consumer_observed_at: str,
    feature_cutoff: str,
    read_locator: str,
    read_locator_version: str,
) -> dict[str, Any]:
    """Build one positive label-only auxiliary scalar receipt."""

    material, payload = _auxiliary_scalar_material(
        feature_name=feature_name,
        feature_value=feature_value,
        feature_snapshot_id=feature_snapshot_id,
    )
    try:
        receipt = build_source_read_receipt(
            source_label=_auxiliary_source_label(feature_name),
            payload_type=_AUXILIARY_SCALAR_PAYLOAD_TYPE,
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            payload_byte_count=len(payload),
            event_time=event_time,
            available_at=available_at,
            consumer_observed_at=consumer_observed_at,
            feature_cutoff=feature_cutoff,
            read_locator_type="IN_MEMORY_IMMUTABLE_OBJECT",
            read_locator=read_locator,
            read_locator_version=read_locator_version,
            finality_type="VERSIONED_SNAPSHOT",
            finality_cutoff=available_at,
            finality_verified_at=available_at,
            finality_verifier="profiled_feature_snapshot_projection_v1_auxiliary",
        )
    except FeatureSnapshotValidationError as exc:
        raise ProfiledFeatureSnapshotProjectionV1Error(
            "PROFILED_PROJECTION_AUXILIARY_RECEIPT_INVALID"
        ) from exc
    if receipt.get("payload_sha256") != _canonical_sha256(material):
        _fail("PROFILED_PROJECTION_AUXILIARY_SCALAR_BINDING_INVALID")
    return receipt


def _receipt_index(
    source_read_receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    index: dict[str, Mapping[str, Any]] = {}
    for receipt in source_read_receipts:
        if not isinstance(receipt, Mapping):
            _fail("PROFILED_PROJECTION_SOURCE_RECEIPT_NOT_OBJECT")
        receipt_sha256 = receipt.get("receipt_sha256")
        if not _valid_sha256(receipt_sha256):
            _fail("PROFILED_PROJECTION_SOURCE_RECEIPT_SHA256_INVALID")
        if receipt_sha256 in index:
            _fail("PROFILED_PROJECTION_SOURCE_RECEIPT_DUPLICATE")
        index[cast(str, receipt_sha256)] = receipt
    return index


def _capture_from_model_roots(
    *,
    feature_receipt_sha256s: Sequence[str],
    receipt_by_sha: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    capture_by_timeframe: dict[str, str] = {}
    for physical_ordinal, feature_name in enumerate(_PROFILE.enabled_feature_names):
        root_sha256 = feature_receipt_sha256s[physical_ordinal]
        root = receipt_by_sha.get(root_sha256)
        if root is None:
            _fail("PROFILED_PROJECTION_MODEL_ROOT_RECEIPT_MISSING")
        transform = _model_transform_contract(feature_name)
        timeframe = cast(str, transform["physical_timeframe"])
        children = root.get("child_read_bindings")
        if type(children) is not list or len(children) != 1:
            _fail("PROFILED_PROJECTION_MODEL_CAPTURE_EDGE_INVALID")
        child = children[0]
        expected_role = f"canonical_closed_{timeframe}_capture"
        if type(child) is not dict or child.get("input_role") != expected_role:
            _fail("PROFILED_PROJECTION_MODEL_CAPTURE_EDGE_INVALID")
        child_sha256 = child.get("receipt_sha256")
        if not _valid_sha256(child_sha256):
            _fail("PROFILED_PROJECTION_MODEL_CAPTURE_EDGE_INVALID")
        prior = capture_by_timeframe.setdefault(timeframe, cast(str, child_sha256))
        if prior != child_sha256:
            _fail("PROFILED_PROJECTION_TIMEFRAME_CAPTURE_ROOT_DRIFT")
    if set(capture_by_timeframe) != {"5m", "1h"}:
        _fail("PROFILED_PROJECTION_EXACT_5M_AND_1H_CAPTURES_REQUIRED")
    return capture_by_timeframe


def _validate_capture_receipt(
    *,
    timeframe: str,
    receipt: Mapping[str, Any],
    decision_time: str,
) -> None:
    finality = receipt.get("finality_evidence")
    if (
        receipt.get("receipt_kind") != "DIRECT_READ"
        or receipt.get("source_label") != _capture_source_label(timeframe)
        or receipt.get("payload_type") != _capture_payload_type(timeframe)
        or type(finality) is not dict
        or finality.get("finality_type") != "CLOSED_INTERVAL"
        or finality.get("event_final") is not True
        or receipt.get("event_time") != receipt.get("feature_cutoff")
        or finality.get("finality_cutoff") != receipt.get("feature_cutoff")
    ):
        _fail("PROFILED_PROJECTION_CAPTURE_FINALITY_BINDING_INVALID")
    _cutoff_text, cutoff = _clock(
        receipt.get("feature_cutoff"),
        reason="PROFILED_PROJECTION_CAPTURE_CUTOFF_INVALID",
    )
    _decision_text, decision = _clock(
        decision_time,
        reason="PROFILED_PROJECTION_DECISION_TIME_INVALID",
    )
    if not cutoff < decision:
        _fail("PROFILED_PROJECTION_CAPTURE_NOT_FINAL_BEFORE_DECISION")
    for clock_name in ("available_at", "consumer_observed_at"):
        _text, parsed = _clock(
            receipt.get(clock_name),
            reason=f"PROFILED_PROJECTION_CAPTURE_{clock_name.upper()}_INVALID",
        )
        if parsed > decision:
            _fail("PROFILED_PROJECTION_CAPTURE_AVAILABLE_AFTER_DECISION")


def _expected_evidence_lineage(
    *,
    feature_snapshot_id: str,
    physical_feature_values: Sequence[float],
    physical_feature_receipt_sha256s: Sequence[str],
    source_read_receipts: Sequence[Mapping[str, Any]],
    decision_time: str,
) -> dict[str, Any]:
    receipt_by_sha = _receipt_index(source_read_receipts)
    capture_by_timeframe = _capture_from_model_roots(
        feature_receipt_sha256s=physical_feature_receipt_sha256s,
        receipt_by_sha=receipt_by_sha,
    )
    timeframe_evidence: list[dict[str, Any]] = []
    for timeframe in ("5m", "1h"):
        capture_sha256 = capture_by_timeframe[timeframe]
        capture = receipt_by_sha.get(capture_sha256)
        if capture is None:
            _fail("PROFILED_PROJECTION_CAPTURE_RECEIPT_MISSING")
        _validate_capture_receipt(
            timeframe=timeframe,
            receipt=capture,
            decision_time=decision_time,
        )
        transform_evidence: list[dict[str, Any]] = []
        for physical_ordinal, feature_name in enumerate(_PROFILE.enabled_feature_names):
            transform_contract = _model_transform_contract(feature_name)
            if transform_contract["physical_timeframe"] != timeframe:
                continue
            root_sha256 = physical_feature_receipt_sha256s[physical_ordinal]
            root = receipt_by_sha.get(root_sha256)
            if root is None:
                _fail("PROFILED_PROJECTION_MODEL_ROOT_RECEIPT_MISSING")
            scalar_material, scalar_bytes, derivation_material = _model_scalar_material(
                feature_name=feature_name,
                feature_value=physical_feature_values[physical_ordinal],
                feature_snapshot_id=feature_snapshot_id,
                capture_receipt_sha256=capture_sha256,
            )
            configuration_contract = _model_configuration_contract(
                feature_name=feature_name,
                capture_receipt_sha256=capture_sha256,
            )
            if (
                root.get("receipt_kind") != "COMPOSITE_DERIVATION"
                or root.get("source_label") != _model_source_label(feature_name)
                or root.get("payload_type") != _MODEL_SCALAR_PAYLOAD_TYPE
                or root.get("payload_sha256") != hashlib.sha256(scalar_bytes).hexdigest()
                or root.get("read_evidence", {}).get("payload_byte_count") != len(scalar_bytes)
                or root.get("derivation_material") != derivation_material
                or root.get("feature_cutoff") != capture.get("feature_cutoff")
                or root.get("event_time") != capture.get("event_time")
                or root.get("finality_evidence", {}).get("finality_type") != "VERSIONED_SNAPSHOT"
            ):
                _fail("PROFILED_PROJECTION_MODEL_TRANSFORM_BINDING_INVALID")
            transform_evidence.append(
                {
                    "physical_ordinal": physical_ordinal,
                    "logical_base_abi_ordinal": transform_contract["base_abi_ordinal"],
                    "feature_name": feature_name,
                    "transform_id": transform_contract["transform_id"],
                    "root_receipt_sha256": root_sha256,
                    "root_source_label": root["source_label"],
                    "scalar_payload_sha256": root["payload_sha256"],
                    "root_available_at": root["available_at"],
                    "root_consumer_observed_at": root["consumer_observed_at"],
                    "root_finality_evidence": root["finality_evidence"],
                    "transform_contract": transform_contract,
                    "configuration_contract": configuration_contract,
                    "scalar_material": scalar_material,
                    "derivation_material": derivation_material,
                }
            )
        timeframe_evidence.append(
            {
                "physical_timeframe": timeframe,
                "capture_receipt_sha256": capture_sha256,
                "capture_source_label": capture["source_label"],
                "capture_payload_type": capture["payload_type"],
                "capture_payload_sha256": capture["payload_sha256"],
                "capture_feature_cutoff": capture["feature_cutoff"],
                "capture_available_at": capture["available_at"],
                "capture_consumer_observed_at": capture["consumer_observed_at"],
                "capture_finality_evidence": capture["finality_evidence"],
                "transform_evidence": transform_evidence,
            }
        )

    auxiliary_evidence: list[dict[str, Any]] = []
    for auxiliary_offset, feature_name in enumerate(AUXILIARY_LABEL_ONLY_FEATURE_NAMES):
        physical_ordinal = PHYSICAL_MODEL_FEATURE_COUNT + auxiliary_offset
        root_sha256 = physical_feature_receipt_sha256s[physical_ordinal]
        root = receipt_by_sha.get(root_sha256)
        if root is None:
            _fail("PROFILED_PROJECTION_AUXILIARY_ROOT_RECEIPT_MISSING")
        material, payload = _auxiliary_scalar_material(
            feature_name=feature_name,
            feature_value=physical_feature_values[physical_ordinal],
            feature_snapshot_id=feature_snapshot_id,
        )
        if (
            root.get("receipt_kind") != "DIRECT_READ"
            or root.get("source_label") != _auxiliary_source_label(feature_name)
            or root.get("payload_type") != _AUXILIARY_SCALAR_PAYLOAD_TYPE
            or root.get("payload_sha256") != hashlib.sha256(payload).hexdigest()
            or root.get("read_evidence", {}).get("payload_byte_count") != len(payload)
            or root.get("finality_evidence", {}).get("finality_type") != "VERSIONED_SNAPSHOT"
        ):
            _fail("PROFILED_PROJECTION_AUXILIARY_BINDING_INVALID")
        auxiliary_evidence.append(
            {
                "physical_ordinal": physical_ordinal,
                "feature_name": feature_name,
                "role": PHYSICAL_FEATURE_ROLE_LABEL_ONLY_AUXILIARY,
                "excluded_from_model_projection": True,
                "root_receipt_sha256": root_sha256,
                "root_source_label": root["source_label"],
                "scalar_payload_sha256": root["payload_sha256"],
                "root_available_at": root["available_at"],
                "root_consumer_observed_at": root["consumer_observed_at"],
                "root_finality_evidence": root["finality_evidence"],
                "scalar_material": material,
            }
        )

    return {
        "schema_version": (PROFILED_FEATURE_SNAPSHOT_PHYSICAL_LINEAGE_V1_SCHEMA_VERSION),
        "evidence_classification": (PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_CLASSIFICATION),
        "profile_schema_version": (ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SCHEMA_VERSION),
        "profile_id": _PROFILE.profile_id,
        "profile_sha256": _PROFILE.profile_sha256,
        "base_abi_schema_version": FEATURE_SOURCE_REGISTRY_V4_ABI_SCHEMA_VERSION,
        "base_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        "base_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "base_requirement_policy_id": (FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID),
        "logical_slot_count": FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
        "logical_profile_selection_mask": list(LOGICAL_PROFILE_SELECTION_MASK),
        "logical_profile_selection_mask_sha256": (
            PROFILED_FEATURE_SNAPSHOT_LOGICAL_SELECTION_MASK_SHA256
        ),
        "enabled_ordinal_mapping": list(_ENABLED_ORDINAL_MAPPING),
        "physical_feature_roles": list(_PHYSICAL_FEATURE_ROLES_MATERIAL),
        "auxiliary_label_only_feature_names": list(AUXILIARY_LABEL_ONLY_FEATURE_NAMES),
        "auxiliary_excluded_from_model_projection": True,
        "timeframe_evidence": timeframe_evidence,
        "auxiliary_evidence": auxiliary_evidence,
        "projection_implementation_sha256": (
            PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_IMPLEMENTATION_SHA256
        ),
        "projection_configuration_sha256": (
            PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_CONFIGURATION_SHA256
        ),
        "runtime_wired": False,
        "trainer_admission_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
    }


def _physical_feature_values(values: object) -> tuple[float, ...]:
    if type(values) not in {list, tuple} or len(values) != PHYSICAL_FEATURE_COUNT:
        _fail("PROFILED_PROJECTION_PHYSICAL_VALUE_COUNT_INVALID")
    return tuple(
        _float32(
            value,
            reason="PROFILED_PROJECTION_PHYSICAL_VALUE_INVALID",
        )[0]
        for value in cast(Sequence[object], values)
    )


def _physical_receipt_roots(values: object) -> tuple[str, ...]:
    if type(values) not in {list, tuple} or len(values) != PHYSICAL_FEATURE_COUNT:
        _fail("PROFILED_PROJECTION_PHYSICAL_RECEIPT_ROOT_COUNT_INVALID")
    roots = tuple(cast(Sequence[object], values))
    if any(not _valid_sha256(value) for value in roots):
        _fail("PROFILED_PROJECTION_PHYSICAL_RECEIPT_ROOT_INVALID")
    return cast(tuple[str, ...], roots)


def build_profiled_feature_snapshot_record_v1(
    *,
    symbol: str,
    feature_snapshot_id: str,
    physical_feature_values: Sequence[int | float],
    physical_feature_receipt_sha256s: Sequence[str],
    source_read_receipts: Sequence[Mapping[str, Any]],
    decision_time: str,
    generated_at: str,
) -> dict[str, Any]:
    """Build one canonical 39-value physical record with ledger v3."""

    adaptive_ohlcv_feature_selection_profile_v1_contract(_PROFILE)
    values = _physical_feature_values(physical_feature_values)
    roots = _physical_receipt_roots(physical_feature_receipt_sha256s)
    if type(source_read_receipts) not in {list, tuple}:
        _fail("PROFILED_PROJECTION_SOURCE_RECEIPTS_NOT_SEQUENCE")
    receipt_list = list(source_read_receipts)
    lineage = _expected_evidence_lineage(
        feature_snapshot_id=feature_snapshot_id,
        physical_feature_values=values,
        physical_feature_receipt_sha256s=roots,
        source_read_receipts=receipt_list,
        decision_time=decision_time,
    )
    capture_cutoffs = [item["capture_feature_cutoff"] for item in lineage["timeframe_evidence"]]
    parsed_cutoffs = [
        _clock(
            cutoff,
            reason="PROFILED_PROJECTION_CAPTURE_CUTOFF_INVALID",
        )
        for cutoff in capture_cutoffs
    ]
    feature_cutoff = max(parsed_cutoffs, key=lambda item: item[1])[0]
    physical_source_labels = (
        *(_model_source_label(name) for name in _PROFILE.enabled_feature_names),
        *(_auxiliary_source_label(name) for name in AUXILIARY_LABEL_ONLY_FEATURE_NAMES),
    )
    try:
        record = build_feature_snapshot_record(
            provenance_classification=PROVENANCE_CANONICAL_V3,
            legacy_v1_snapshot_id=None,
            symbol=symbol,
            timeframe=_PHYSICAL_RECORD_TIMEFRAME,
            feature_snapshot_id=feature_snapshot_id,
            tensor_decision_time=decision_time,
            temporal_rejection_reasons=[PROFILED_FEATURE_SNAPSHOT_UNWIRED_REASON],
            ordered_feature_names=PHYSICAL_ORDERED_FEATURE_NAMES,
            feature_values=values,
            missing_mask=[0] * PHYSICAL_FEATURE_COUNT,
            stale_mask=[0] * PHYSICAL_FEATURE_COUNT,
            source_availability_mask=[1] * PHYSICAL_FEATURE_COUNT,
            ordered_feature_source_labels=physical_source_labels,
            feature_source_receipt_sha256s=roots,
            source_read_receipts=receipt_list,
            feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
            ordered_feature_requirement_classes=["REQUIRED"] * PHYSICAL_FEATURE_COUNT,
            original_tensor_id=f"profiled_physical_{feature_snapshot_id}",
            source_lineage_material=lineage,
            feature_cutoff=feature_cutoff,
            masa_feature_cutoff=feature_cutoff,
            ppo_feature_cutoff=feature_cutoff,
            ppo_decision_time=decision_time,
            generated_at=generated_at,
        )
    except FeatureSnapshotValidationError as exc:
        raise ProfiledFeatureSnapshotProjectionV1Error(
            "PROFILED_PROJECTION_PHYSICAL_V3_RECORD_INVALID",
            *exc.reasons,
        ) from exc
    validate_profiled_feature_snapshot_projection_v1(record)
    return record


def _logical_tensor_material(
    *,
    values: Sequence[float],
    missing: Sequence[int],
    stale: Sequence[int],
    availability: Sequence[int],
    source_labels: Sequence[str | None],
    receipt_roots: Sequence[str | None],
) -> dict[str, Any]:
    return {
        "schema_version": "profiled_logical_tensor_v1",
        "profile_id": _PROFILE.profile_id,
        "profile_sha256": _PROFILE.profile_sha256,
        "base_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        "ordered_feature_names": list(_LOGICAL_ORDERED_FEATURE_NAMES),
        "feature_values": list(values),
        "missing_mask": list(missing),
        "stale_mask": list(stale),
        "source_availability_mask": list(availability),
        "profile_selection_mask": list(LOGICAL_PROFILE_SELECTION_MASK),
        "feature_source_labels": list(source_labels),
        "feature_source_receipt_sha256s": list(receipt_roots),
    }


@dataclass(frozen=True, slots=True)
class ProfiledFeatureSnapshotProjectionV1:
    """Factory-only logical projection and label-rebuild evidence."""

    schema_version: str
    classification: str
    status: str
    physical_durable_snapshot_id: str
    physical_record_sha256: str
    profile_id: str
    profile_sha256: str
    base_abi_sha256: str
    projection_implementation_sha256: str
    projection_configuration_sha256: str
    physical_ordered_feature_names: tuple[str, ...]
    physical_ordered_feature_roles: tuple[str, ...]
    physical_feature_values: tuple[float, ...]
    physical_feature_receipt_sha256s: tuple[str, ...]
    logical_ordered_feature_names: tuple[str, ...]
    logical_feature_values: tuple[float, ...]
    logical_missing_mask: tuple[int, ...]
    logical_stale_mask: tuple[int, ...]
    logical_source_availability_mask: tuple[int, ...]
    logical_profile_selection_mask: tuple[int, ...]
    logical_profile_selection_mask_sha256: str
    logical_feature_source_labels: tuple[str | None, ...]
    logical_feature_receipt_sha256s: tuple[str | None, ...]
    logical_tensor_sha256: str
    label_rebuild_physical_snapshot_json: str
    label_rebuild_physical_snapshot_sha256: str
    projection_sha256: str
    trainer_admission_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    runtime_wired: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _RESULT_CONSTRUCTION_TOKEN:
            _fail("PROFILED_PROJECTION_RESULT_FACTORY_CONSTRUCTION_REQUIRED")
        if (
            self.schema_version != PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_SCHEMA_VERSION
            or self.classification != PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_CLASSIFICATION
            or self.status != PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_STATUS
            or self.profile_id != _PROFILE.profile_id
            or self.profile_sha256 != _PROFILE.profile_sha256
            or self.base_abi_sha256 != FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256
            or self.projection_implementation_sha256
            != PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_IMPLEMENTATION_SHA256
            or self.projection_configuration_sha256
            != PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_CONFIGURATION_SHA256
            or self.logical_profile_selection_mask_sha256
            != PROFILED_FEATURE_SNAPSHOT_LOGICAL_SELECTION_MASK_SHA256
            or any(
                value is not False
                for value in (
                    self.trainer_admission_authorized,
                    self.prediction_authorized,
                    self.paper_trading_authorized,
                    self.live_execution_authorized,
                    self.runtime_wired,
                )
            )
        ):
            _fail("PROFILED_PROJECTION_RESULT_INVARIANT_INVALID")

    @property
    def label_rebuild_physical_snapshot(self) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json.loads(self.label_rebuild_physical_snapshot_json),
        )


def validate_profiled_feature_snapshot_projection_v1(
    record: Mapping[str, Any],
) -> ProfiledFeatureSnapshotProjectionV1:
    """Validate physical v3 evidence, then reconstruct the logical 446 tensor."""

    adaptive_ohlcv_feature_selection_profile_v1_contract(_PROFILE)
    try:
        validate_feature_snapshot_record(record)
    except FeatureSnapshotValidationError as exc:
        raise ProfiledFeatureSnapshotProjectionV1Error(
            "PROFILED_PROJECTION_PHYSICAL_V3_RECORD_INVALID",
            *exc.reasons,
        ) from exc
    if type(record) is not dict:
        _fail("PROFILED_PROJECTION_PHYSICAL_RECORD_NOT_EXACT_DICT")
    envelope = record.get("frozen_envelope")
    if type(envelope) is not dict:
        _fail("PROFILED_PROJECTION_PHYSICAL_ENVELOPE_INVALID")
    physical_names = envelope.get("ordered_feature_names")
    if physical_names != list(PHYSICAL_ORDERED_FEATURE_NAMES):
        _fail("PROFILED_PROJECTION_PHYSICAL_FEATURE_ORDER_INVALID")
    requirements = envelope.get("feature_abi", {}).get("ordered_feature_requirement_classes")
    if requirements != ["REQUIRED"] * PHYSICAL_FEATURE_COUNT:
        _fail("PROFILED_PROJECTION_PHYSICAL_REQUIREMENTS_INVALID")
    if (
        envelope.get("missing_mask") != [0] * PHYSICAL_FEATURE_COUNT
        or envelope.get("stale_mask") != [0] * PHYSICAL_FEATURE_COUNT
        or envelope.get("source_availability_mask") != [1] * PHYSICAL_FEATURE_COUNT
    ):
        _fail("PROFILED_PROJECTION_PHYSICAL_POSITIVE_EVIDENCE_REQUIRED")
    roots = _physical_receipt_roots(envelope.get("feature_source_receipt_sha256s"))
    values = _physical_feature_values(envelope.get("feature_values"))
    receipt_list = envelope.get("source_read_receipts")
    if type(receipt_list) is not list:
        _fail("PROFILED_PROJECTION_SOURCE_RECEIPTS_NOT_LIST")
    expected_lineage = _expected_evidence_lineage(
        feature_snapshot_id=cast(str, envelope["feature_snapshot_id"]),
        physical_feature_values=values,
        physical_feature_receipt_sha256s=roots,
        source_read_receipts=receipt_list,
        decision_time=cast(str, envelope["tensor_decision_time"]),
    )
    lineage = envelope.get("source_lineage_material")
    if type(lineage) is not dict:
        _fail("PROFILED_PROJECTION_SOURCE_LINEAGE_INVALID")
    actual_core_lineage = {
        key: value
        for key, value in lineage.items()
        if key not in _PROJECTION_RESERVED_LINEAGE_FIELDS
    }
    if actual_core_lineage != expected_lineage:
        _fail("PROFILED_PROJECTION_SOURCE_LINEAGE_BINDING_INVALID")
    if envelope.get(
        "strict_training_eligible"
    ) is not False or PROFILED_FEATURE_SNAPSHOT_UNWIRED_REASON not in envelope.get(
        "temporal_rejection_reasons", []
    ):
        _fail("PROFILED_PROJECTION_UNWIRED_QUARANTINE_INVALID")

    logical_values = [0.0] * FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
    logical_missing = [0] * FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
    logical_stale = [0] * FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
    logical_availability = [0] * FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
    logical_source_labels: list[str | None] = [None] * FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
    logical_receipt_roots: list[str | None] = [None] * FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
    physical_source_labels = envelope["ordered_feature_source_labels"]
    for physical_ordinal, logical_ordinal in enumerate(_PROFILE.enabled_slot_ordinals):
        logical_values[logical_ordinal] = values[physical_ordinal]
        logical_availability[logical_ordinal] = 1
        logical_source_labels[logical_ordinal] = physical_source_labels[physical_ordinal]
        logical_receipt_roots[logical_ordinal] = roots[physical_ordinal]
    if any(
        logical_values[ordinal] != 0.0
        or logical_missing[ordinal] != 0
        or logical_stale[ordinal] != 0
        or logical_availability[ordinal] != 0
        or logical_source_labels[ordinal] is not None
        or logical_receipt_roots[ordinal] is not None
        for ordinal, selected in enumerate(LOGICAL_PROFILE_SELECTION_MASK)
        if selected == 0
    ):
        _fail("PROFILED_PROJECTION_DISABLED_SLOT_ENCODING_INVALID")

    logical_material = _logical_tensor_material(
        values=logical_values,
        missing=logical_missing,
        stale=logical_stale,
        availability=logical_availability,
        source_labels=logical_source_labels,
        receipt_roots=logical_receipt_roots,
    )
    logical_tensor_sha256 = _canonical_sha256(logical_material)
    label_rebuild_snapshot = {
        "schema_version": "profiled_label_rebuild_physical_snapshot_v1",
        "physical_durable_snapshot_id": record["durable_snapshot_id"],
        "physical_record_sha256": record["record_sha256"],
        "symbol": envelope["symbol"],
        "timeframe": envelope["timeframe"],
        "feature_snapshot_id": envelope["feature_snapshot_id"],
        "feature_cutoff": envelope["feature_cutoff"],
        "decision_time": envelope["tensor_decision_time"],
        "generated_at": envelope["generated_at"],
        "profile_id": _PROFILE.profile_id,
        "profile_sha256": _PROFILE.profile_sha256,
        "ordered_feature_names": list(PHYSICAL_ORDERED_FEATURE_NAMES),
        "ordered_feature_roles": list(PHYSICAL_ORDERED_FEATURE_ROLES),
        "feature_values": list(values),
        "ordered_feature_source_labels": list(physical_source_labels),
        "feature_source_receipt_sha256s": list(roots),
        "auxiliary_label_values": {
            name: values[PHYSICAL_MODEL_FEATURE_COUNT + offset]
            for offset, name in enumerate(AUXILIARY_LABEL_ONLY_FEATURE_NAMES)
        },
        "auxiliary_excluded_from_model_projection": True,
    }
    label_rebuild_json = _canonical_bytes(label_rebuild_snapshot).decode("ascii")
    label_rebuild_sha256 = hashlib.sha256(label_rebuild_json.encode("ascii")).hexdigest()
    projection_material = {
        "schema_version": PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_SCHEMA_VERSION,
        "physical_durable_snapshot_id": record["durable_snapshot_id"],
        "physical_record_sha256": record["record_sha256"],
        "profile_id": _PROFILE.profile_id,
        "profile_sha256": _PROFILE.profile_sha256,
        "base_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        "projection_implementation_sha256": (
            PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_IMPLEMENTATION_SHA256
        ),
        "projection_configuration_sha256": (
            PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_CONFIGURATION_SHA256
        ),
        "logical_profile_selection_mask_sha256": (
            PROFILED_FEATURE_SNAPSHOT_LOGICAL_SELECTION_MASK_SHA256
        ),
        "logical_tensor_sha256": logical_tensor_sha256,
        "label_rebuild_physical_snapshot_sha256": label_rebuild_sha256,
    }
    return ProfiledFeatureSnapshotProjectionV1(
        schema_version=PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_SCHEMA_VERSION,
        classification=PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_CLASSIFICATION,
        status=PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_STATUS,
        physical_durable_snapshot_id=cast(str, record["durable_snapshot_id"]),
        physical_record_sha256=cast(str, record["record_sha256"]),
        profile_id=_PROFILE.profile_id,
        profile_sha256=_PROFILE.profile_sha256,
        base_abi_sha256=FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        projection_implementation_sha256=(
            PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_IMPLEMENTATION_SHA256
        ),
        projection_configuration_sha256=(
            PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_CONFIGURATION_SHA256
        ),
        physical_ordered_feature_names=PHYSICAL_ORDERED_FEATURE_NAMES,
        physical_ordered_feature_roles=PHYSICAL_ORDERED_FEATURE_ROLES,
        physical_feature_values=values,
        physical_feature_receipt_sha256s=roots,
        logical_ordered_feature_names=_LOGICAL_ORDERED_FEATURE_NAMES,
        logical_feature_values=tuple(logical_values),
        logical_missing_mask=tuple(logical_missing),
        logical_stale_mask=tuple(logical_stale),
        logical_source_availability_mask=tuple(logical_availability),
        logical_profile_selection_mask=LOGICAL_PROFILE_SELECTION_MASK,
        logical_profile_selection_mask_sha256=(
            PROFILED_FEATURE_SNAPSHOT_LOGICAL_SELECTION_MASK_SHA256
        ),
        logical_feature_source_labels=tuple(logical_source_labels),
        logical_feature_receipt_sha256s=tuple(logical_receipt_roots),
        logical_tensor_sha256=logical_tensor_sha256,
        label_rebuild_physical_snapshot_json=label_rebuild_json,
        label_rebuild_physical_snapshot_sha256=label_rebuild_sha256,
        projection_sha256=_canonical_sha256(projection_material),
        trainer_admission_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        runtime_wired=False,
        _construction_token=_RESULT_CONSTRUCTION_TOKEN,
    )


def validate_profiled_logical_tensor_claim_v1(
    projection: ProfiledFeatureSnapshotProjectionV1,
    *,
    ordered_feature_names: object,
    feature_values: object,
    missing_mask: object,
    stale_mask: object,
    source_availability_mask: object,
    profile_selection_mask: object,
) -> None:
    """Validate a claimed logical tensor against the reconstructed projection."""

    if type(projection) is not ProfiledFeatureSnapshotProjectionV1:
        _fail("PROFILED_PROJECTION_RESULT_REQUIRED")
    vectors = (
        ordered_feature_names,
        feature_values,
        missing_mask,
        stale_mask,
        source_availability_mask,
        profile_selection_mask,
    )
    if any(type(vector) not in {list, tuple} for vector in vectors):
        _fail("PROFILED_PROJECTION_LOGICAL_CLAIM_NOT_SEQUENCE")
    claimed_names = tuple(cast(Sequence[object], ordered_feature_names))
    if claimed_names != projection.logical_ordered_feature_names:
        _fail("PROFILED_PROJECTION_LOGICAL_FEATURE_ORDER_INVALID")
    claimed_values = tuple(cast(Sequence[object], feature_values))
    if len(claimed_values) != FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT:
        _fail("PROFILED_PROJECTION_LOGICAL_VALUE_COUNT_INVALID")
    canonical_values = tuple(
        _float32(
            value,
            reason="PROFILED_PROJECTION_LOGICAL_VALUE_INVALID",
        )[0]
        for value in claimed_values
    )
    if any(
        canonical_values[ordinal] != 0.0
        for ordinal, selected in enumerate(LOGICAL_PROFILE_SELECTION_MASK)
        if selected == 0
    ):
        _fail("PROFILED_PROJECTION_DISABLED_VALUE_NONZERO")
    claims = (
        (canonical_values, projection.logical_feature_values),
        (tuple(cast(Sequence[object], missing_mask)), projection.logical_missing_mask),
        (tuple(cast(Sequence[object], stale_mask)), projection.logical_stale_mask),
        (
            tuple(cast(Sequence[object], source_availability_mask)),
            projection.logical_source_availability_mask,
        ),
        (
            tuple(cast(Sequence[object], profile_selection_mask)),
            projection.logical_profile_selection_mask,
        ),
    )
    if any(actual != expected for actual, expected in claims):
        _fail("PROFILED_PROJECTION_LOGICAL_CLAIM_MISMATCH")


__all__ = [
    "AUXILIARY_LABEL_ONLY_FEATURE_NAMES",
    "LOGICAL_PROFILE_SELECTION_MASK",
    "PHYSICAL_AUXILIARY_FEATURE_COUNT",
    "PHYSICAL_FEATURE_COUNT",
    "PHYSICAL_FEATURE_ROLE_LABEL_ONLY_AUXILIARY",
    "PHYSICAL_FEATURE_ROLE_MODEL_INPUT",
    "PHYSICAL_MODEL_FEATURE_COUNT",
    "PHYSICAL_ORDERED_FEATURE_NAMES",
    "PHYSICAL_ORDERED_FEATURE_ROLES",
    "PROFILED_FEATURE_SNAPSHOT_LOGICAL_SELECTION_MASK_SHA256",
    "PROFILED_FEATURE_SNAPSHOT_PHYSICAL_LINEAGE_V1_SCHEMA_VERSION",
    "PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_CLASSIFICATION",
    "PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_CONFIGURATION_SHA256",
    "PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_IMPLEMENTATION_SHA256",
    "PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_SCHEMA_VERSION",
    "PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_STATUS",
    "PROFILED_FEATURE_SNAPSHOT_UNWIRED_REASON",
    "ProfiledFeatureSnapshotProjectionV1",
    "ProfiledFeatureSnapshotProjectionV1Error",
    "build_profiled_auxiliary_receipt_v1",
    "build_profiled_feature_snapshot_record_v1",
    "build_profiled_model_feature_receipt_v1",
    "build_profiled_ohlcv_capture_receipt_v1",
    "validate_profiled_feature_snapshot_projection_v1",
    "validate_profiled_logical_tensor_claim_v1",
]
