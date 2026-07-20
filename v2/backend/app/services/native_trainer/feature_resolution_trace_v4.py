"""Unwired binder for caller-supplied TensorBuilder resolution observations.

The artifact proves internal shape, hash, float32-byte, and declared-clock
consistency only.  It does not prove that a resolver captured an observation,
that a supplied source/root is authentic, or that raw context exists in CAS.
Every downstream authorization remains frozen false.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NoReturn, cast

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    FeatureSnapshotValidationError,
    feature_abi_contract,
    feature_requirement_classes_for_names,
    stable_sha256,
)
from v2.backend.app.services.native_trainer.feature_resolution_observation_v4 import (
    FEATURE_RESOLUTION_OBSERVATION_V4_SCHEMA_VERSION,
    NEGATIVE_SOURCE_STALE,
    RESOLUTION_STATUS_RESOLVED,
    RESOLUTION_STATUS_TYPED_NEGATIVE,
    FeatureResolutionObservationV4ValidationError,
    FeatureSlotResolutionObservationV4,
    build_feature_slot_resolution_observation_v4,
    canonical_float32_v4,
)
from v2.backend.app.services.native_trainer.ordered_feature_tensor_spec_v3 import (
    FEATURE_SPEC,
)

if TYPE_CHECKING:
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
        FeatureTensorRecord,
    )

FEATURE_RESOLUTION_TRACE_V4_SCHEMA_VERSION = "trainer_feature_resolution_trace_v4"
FEATURE_RESOLUTION_TRACE_V4_EVIDENCE_CLASSIFICATION = (
    "AUDIT_ONLY_VALIDATED_CALLER_SUPPLIED_OBSERVATIONS_UNAUTHENTICATED_UNWIRED"
)
FEATURE_RESOLUTION_TRACE_V4_DOWNSTREAM_STATUS = (
    "NON_CONSUMABLE_NO_FEATURE_PUBLICATION_TRAINER_PREDICTION_PAPER_OR_LIVE_AUTHORIZATION"
)
FEATURE_RESOLUTION_TRACE_V4_ABI_SHA256 = (
    "e81b6dd95bfba930d67e694941f21a6d4ab5432142c25595848148c8bb42ddf9"
)
FEATURE_RESOLUTION_TRACE_V4_SLOT_COUNT = 446
FEATURE_RESOLUTION_TRACE_V4_REQUIRED_SLOT_COUNT = 384
FEATURE_RESOLUTION_TRACE_V4_OPTIONAL_SLOT_COUNT = 62
MAX_FEATURE_RESOLUTION_TRACE_V4_BYTES = 2 * 1024 * 1024

_FALSE_FIELDS = (
    "resolver_branch_capture_authenticated",
    "raw_context_cas_verified",
    "source_receipts_authenticated",
    "source_scope_complete",
    "per_field_receipts_complete",
    "resolved_source_mapping_verified",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)
_OBSERVATION_FIELDS = frozenset(
    {
        "schema_version",
        "abi_index",
        "feature_name",
        "requirement_class",
        "configured_source_label",
        "resolved_source_label",
        "resolution_status",
        "selected_payload",
        "selected_key",
        "selected_path",
        "selected_alias",
        "resolver_version",
        "resolver_code_sha256",
        "resolver_config_sha256",
        "transform_id",
        "transform_version",
        "transform_code_sha256",
        "transform_config_sha256",
        "tensor_value",
        "resolved_value",
        "missing_mask",
        "stale_mask",
        "source_availability_mask",
        "negative_reason",
        "source_root_sha256",
        "dependency_root_sha256s",
        "negative_evidence_sha256",
        "event_time",
        "ingested_at",
        "available_at",
        "generated_at",
        "feature_cutoff",
        "decision_time",
        "masa_feature_cutoff",
        "execution_time",
        "consumer_observed_at",
        "candle_close_time",
        "candle_final",
        "slot_observation_sha256",
    }
)
_TENSOR_BINDING_FIELDS = frozenset(
    {
        "tensor_id",
        "symbol",
        "timeframe",
        "feature_snapshot_id",
        "source_lineage_sha256",
        "decision_time",
        "ordered_feature_names_sha256",
        "ordered_source_labels_sha256",
        "missing_mask_sha256",
        "stale_mask_sha256",
        "source_availability_mask_sha256",
        "model_vector_float32_be_sha256",
        "model_vector_float32_be_byte_count",
    }
)
_TRACE_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "feature_abi_sha256",
        "feature_requirement_policy_id",
        "feature_slot_count",
        "required_slot_count",
        "optional_slot_count",
        "raw_context_sha256",
        "tensor_binding",
        "slot_observations",
        "slot_observation_graph_sha256",
        "resolved_slot_count",
        "typed_negative_slot_count",
        "required_typed_negative_feature_names",
        "optional_typed_negative_feature_names",
        "complete_slot_observation_set",
        "structural_integrity_valid",
        "declared_point_in_time_order_valid",
        "required_value_contract_valid",
        "audit_trace_only",
        *_FALSE_FIELDS,
        "trace_sha256",
    }
)
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@-]{0,255}$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CONSTRUCTION_TOKEN = object()


class FeatureResolutionTraceV4ValidationError(ValueError):
    """Trace structure, tensor binding, or declared PIT order is invalid."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise FeatureResolutionTraceV4ValidationError(*reasons) from None


@dataclass(frozen=True, slots=True)
class FeatureResolutionTraceArtifactV4:
    """Factory-only, canonical, explicitly non-consumable trace artifact."""

    schema_version: str
    trace_sha256: str
    trace_json: str = field(repr=False)
    _construction_token: object = field(repr=False, compare=False)
    audit_trace_only: bool = field(default=True, init=False)
    resolver_branch_capture_authenticated: bool = field(default=False, init=False)
    raw_context_cas_verified: bool = field(default=False, init=False)
    source_receipts_authenticated: bool = field(default=False, init=False)
    source_scope_complete: bool = field(default=False, init=False)
    per_field_receipts_complete: bool = field(default=False, init=False)
    resolved_source_mapping_verified: bool = field(default=False, init=False)
    feature_publication_receipt_emitted: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("FEATURE_RESOLUTION_TRACE_V4_FACTORY_CONSTRUCTION_REQUIRED")
        validated = _validate_trace_mapping(_parse_json(self.trace_json))
        if (
            self.schema_version != FEATURE_RESOLUTION_TRACE_V4_SCHEMA_VERSION
            or self.trace_sha256 != validated["trace_sha256"]
            or self.trace_json != _canonical_json(validated)
        ):
            _fail("FEATURE_RESOLUTION_TRACE_V4_ARTIFACT_BINDING_MISMATCH")

    @property
    def trace(self) -> dict[str, Any]:
        """Return a fresh parsed and fully revalidated mapping."""

        return _validate_trace_mapping(_parse_json(self.trace_json))


def _valid_label(value: object) -> bool:
    return type(value) is str and value.isascii() and _LABEL_RE.fullmatch(value) is not None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _canonical_artifact_float32(value: object, *, field_name: str) -> float:
    """Require the one JSON scalar accepted for one finite float32 value."""

    if type(value) is not float or not math.isfinite(value):
        _fail(f"FEATURE_RESOLUTION_TRACE_V4_{field_name}_NOT_EXACT_FLOAT")
    if value == 0.0 and math.copysign(1.0, value) < 0.0:
        _fail(f"FEATURE_RESOLUTION_TRACE_V4_{field_name}_NEGATIVE_ZERO_FORBIDDEN")
    try:
        runtime = float(struct.unpack("!f", struct.pack("!f", value))[0])
    except (OverflowError, struct.error, TypeError, ValueError):
        _fail(f"FEATURE_RESOLUTION_TRACE_V4_{field_name}_NOT_CANONICAL_FLOAT32")
    if not math.isfinite(runtime) or runtime != value:
        _fail(f"FEATURE_RESOLUTION_TRACE_V4_{field_name}_NOT_CANONICAL_FLOAT32")
    return value


def _canonical_json(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        _fail("FEATURE_RESOLUTION_TRACE_V4_NOT_STRICT_JSON")
    if len(encoded.encode("ascii")) > MAX_FEATURE_RESOLUTION_TRACE_V4_BYTES:
        _fail("FEATURE_RESOLUTION_TRACE_V4_SIZE_LIMIT_EXCEEDED")
    return encoded


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def _parse_json(value: object) -> dict[str, Any]:
    if type(value) is not str or not value:
        _fail("FEATURE_RESOLUTION_TRACE_V4_JSON_INVALID")
    try:
        if len(value.encode("ascii", errors="strict")) > MAX_FEATURE_RESOLUTION_TRACE_V4_BYTES:
            _fail("FEATURE_RESOLUTION_TRACE_V4_JSON_INVALID")

        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, item in pairs:
                if key in result:
                    _fail("FEATURE_RESOLUTION_TRACE_V4_DUPLICATE_JSON_KEY")
                result[key] = item
            return result

        parsed = json.loads(
            value,
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _: _fail("FEATURE_RESOLUTION_TRACE_V4_JSON_CONSTANT_FORBIDDEN"),
        )
    except FeatureResolutionTraceV4ValidationError:
        raise
    except (
        UnicodeEncodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
    ):
        _fail("FEATURE_RESOLUTION_TRACE_V4_JSON_INVALID")
    if type(parsed) is not dict:
        _fail("FEATURE_RESOLUTION_TRACE_V4_NOT_EXACT_OBJECT")
    return cast(dict[str, Any], parsed)


def _exact_dict(value: object, fields: frozenset[str], reason: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(reason)
    result = cast(dict[object, object], value)
    if any(type(key) is not str for key in result) or frozenset(result) != fields:
        _fail(reason)
    return cast(dict[str, Any], dict(result))


def _model_contract() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if type(FEATURE_SPEC) is not tuple:
        _fail("FEATURE_RESOLUTION_TRACE_V4_FEATURE_SPEC_INVALID")
    names: list[str] = []
    sources: list[str] = []
    for item in FEATURE_SPEC:
        if type(item) is not tuple or len(item) != 2:
            _fail("FEATURE_RESOLUTION_TRACE_V4_FEATURE_SPEC_INVALID")
        name, source = item
        if not _valid_label(name) or not _valid_label(source):
            _fail("FEATURE_RESOLUTION_TRACE_V4_FEATURE_SPEC_INVALID")
        names.append(name)
        sources.append(source)
    if len(names) != FEATURE_RESOLUTION_TRACE_V4_SLOT_COUNT or len(names) != len(set(names)):
        _fail("FEATURE_RESOLUTION_TRACE_V4_FEATURE_SPEC_INVALID")
    try:
        requirements = feature_requirement_classes_for_names(names)
        abi_sha256 = stable_sha256(feature_abi_contract(names))
    except FeatureSnapshotValidationError as exc:
        raise FeatureResolutionTraceV4ValidationError(
            "FEATURE_RESOLUTION_TRACE_V4_ABI_CONTRACT_INVALID"
        ) from exc
    if abi_sha256 != FEATURE_RESOLUTION_TRACE_V4_ABI_SHA256:
        _fail("FEATURE_RESOLUTION_TRACE_V4_ABI_SHA256_MISMATCH")
    if requirements.count("REQUIRED") != FEATURE_RESOLUTION_TRACE_V4_REQUIRED_SLOT_COUNT:
        _fail("FEATURE_RESOLUTION_TRACE_V4_REQUIRED_SLOT_COUNT_MISMATCH")
    if (
        requirements.count("OPTIONAL_EVENT_DEPENDENT")
        != FEATURE_RESOLUTION_TRACE_V4_OPTIONAL_SLOT_COUNT
    ):
        _fail("FEATURE_RESOLUTION_TRACE_V4_OPTIONAL_SLOT_COUNT_MISMATCH")
    return tuple(names), tuple(sources), requirements


def _model_bytes(
    values: Sequence[object], missing: Sequence[int], stale: Sequence[int], available: Sequence[int]
) -> bytes:
    runtime = [canonical_float32_v4(value) for value in values]
    vector = (
        runtime
        + [float(v) for v in missing]
        + [float(v) for v in stale]
        + [float(v) for v in available]
    )
    try:
        return struct.pack(f"!{len(vector)}f", *vector)
    except (OverflowError, struct.error, TypeError, ValueError):
        _fail("FEATURE_RESOLUTION_TRACE_V4_MODEL_VECTOR_ENCODING_FAILED")


def _validate_tensor(
    tensor: FeatureTensorRecord, names: tuple[str, ...]
) -> tuple[list[float], bytes]:
    # Keep trace validation and the audit-only capture import-safe.  The concrete
    # runtime record is needed only when a caller explicitly builds a trace.
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
        FeatureTensorRecord,
    )

    if type(tensor) is not FeatureTensorRecord:
        _fail("FEATURE_RESOLUTION_TRACE_V4_EXACT_TENSOR_RECORD_REQUIRED")
    count = len(names)
    vectors = (
        tensor.values,
        tensor.missing_mask,
        tensor.stale_mask,
        tensor.source_availability,
        tensor.feature_names,
        tensor.source_labels,
        tensor.source_availability_vector,
    )
    if any(type(vector) is not tuple or len(vector) != count for vector in vectors):
        _fail("FEATURE_RESOLUTION_TRACE_V4_TENSOR_DIMENSION_MISMATCH")
    if tensor.feature_names != names:
        _fail("FEATURE_RESOLUTION_TRACE_V4_TENSOR_FEATURE_ORDER_MISMATCH")
    for mask in (
        tensor.missing_mask,
        tensor.stale_mask,
        tensor.source_availability,
        tensor.source_availability_vector,
    ):
        if any(type(value) is not int or value not in (0, 1) for value in mask):
            _fail("FEATURE_RESOLUTION_TRACE_V4_TENSOR_MASK_INVALID")
    if any(
        source_available != 1 - missing
        for missing, source_available in zip(
            tensor.missing_mask,
            tensor.source_availability,
            strict=True,
        )
    ):
        _fail("FEATURE_RESOLUTION_TRACE_V4_TENSOR_MISSING_AVAILABILITY_MISMATCH")
    if tensor.source_availability_vector != tensor.source_availability:
        _fail("FEATURE_RESOLUTION_TRACE_V4_TENSOR_AVAILABILITY_VECTOR_MISMATCH")
    if (
        type(tensor.temporal_rejection_reasons) is not tuple
        or tensor.temporal_rejection_reasons != ()
    ):
        _fail("FEATURE_RESOLUTION_TRACE_V4_TENSOR_TEMPORAL_REJECTION_PRESENT")
    if not _valid_sha256(tensor.source_lineage_hash) or any(
        not _valid_label(value)
        for value in (
            tensor.tensor_id,
            tensor.symbol,
            tensor.timeframe,
            tensor.feature_snapshot_id,
            tensor.decision_time,
            *tensor.source_labels,
        )
    ):
        _fail("FEATURE_RESOLUTION_TRACE_V4_TENSOR_IDENTITY_INVALID")
    expected_missing = tuple(
        name for name, mask in zip(names, tensor.missing_mask, strict=True) if mask == 1
    )
    expected_stale = tuple(
        name for name, mask in zip(names, tensor.stale_mask, strict=True) if mask == 1
    )
    if (
        tensor.missing_feature_names != expected_missing
        or tensor.stale_feature_names != expected_stale
    ):
        _fail("FEATURE_RESOLUTION_TRACE_V4_TENSOR_MASK_NAMES_MISMATCH")
    expected_coverage = 100.0 * (count - sum(tensor.missing_mask)) / count
    if (
        type(tensor.data_coverage_percent) is not float
        or not math.isfinite(tensor.data_coverage_percent)
        or tensor.data_coverage_percent != expected_coverage
    ):
        _fail("FEATURE_RESOLUTION_TRACE_V4_TENSOR_COVERAGE_MISMATCH")
    values = [canonical_float32_v4(value) for value in tensor.values]
    if any(
        missing == 1 and value != 0.0
        for value, missing in zip(values, tensor.missing_mask, strict=True)
    ):
        _fail("FEATURE_RESOLUTION_TRACE_V4_TENSOR_MISSING_VALUE_NOT_ZERO")
    return values, _model_bytes(
        values,
        tensor.missing_mask,
        tensor.stale_mask,
        tensor.source_availability,
    )


def _observation_mapping(
    observation: FeatureSlotResolutionObservationV4,
    *,
    requirement: str,
    configured_source: str,
    resolved_source: str,
    tensor_value: float,
    missing: int,
    stale: int,
    available: int,
) -> dict[str, Any]:
    positive = observation.resolution_status == RESOLUTION_STATUS_RESOLVED
    if positive:
        if (missing, stale, available) != (0, 0, 1):
            _fail("FEATURE_RESOLUTION_TRACE_V4_RESOLVED_MASK_BINDING_MISMATCH")
        if canonical_float32_v4(observation.resolved_value) != tensor_value:
            _fail("FEATURE_RESOLUTION_TRACE_V4_RESOLVED_VALUE_BINDING_MISMATCH")
    else:
        if not (missing == 1 or stale == 1 or available == 0):
            _fail("FEATURE_RESOLUTION_TRACE_V4_NEGATIVE_MASK_BINDING_MISMATCH")
        if (stale == 1) is not (observation.negative_reason == NEGATIVE_SOURCE_STALE):
            _fail("FEATURE_RESOLUTION_TRACE_V4_STALE_REASON_MASK_MISMATCH")
    mapping: dict[str, Any] = {
        "schema_version": FEATURE_RESOLUTION_OBSERVATION_V4_SCHEMA_VERSION,
        "abi_index": observation.abi_index,
        "feature_name": observation.feature_name,
        "requirement_class": requirement,
        "configured_source_label": configured_source,
        "resolved_source_label": resolved_source,
        "resolution_status": observation.resolution_status,
        "selected_payload": observation.selected_payload,
        "selected_key": observation.selected_key,
        "selected_path": None
        if observation.selected_path is None
        else list(observation.selected_path),
        "selected_alias": observation.selected_alias,
        "resolver_version": observation.resolver_version,
        "resolver_code_sha256": observation.resolver_code_sha256,
        "resolver_config_sha256": observation.resolver_config_sha256,
        "transform_id": observation.transform_id,
        "transform_version": observation.transform_version,
        "transform_code_sha256": observation.transform_code_sha256,
        "transform_config_sha256": observation.transform_config_sha256,
        "tensor_value": tensor_value,
        "resolved_value": tensor_value if positive else None,
        "missing_mask": missing,
        "stale_mask": stale,
        "source_availability_mask": available,
        "negative_reason": observation.negative_reason,
        "source_root_sha256": observation.source_root_sha256,
        "dependency_root_sha256s": list(observation.dependency_root_sha256s),
        "negative_evidence_sha256": observation.negative_evidence_sha256,
        "event_time": observation.event_time,
        "ingested_at": observation.ingested_at,
        "available_at": observation.available_at,
        "generated_at": observation.generated_at,
        "feature_cutoff": observation.feature_cutoff,
        "decision_time": observation.decision_time,
        "masa_feature_cutoff": observation.masa_feature_cutoff,
        "execution_time": observation.execution_time,
        "consumer_observed_at": observation.consumer_observed_at,
        "candle_close_time": observation.candle_close_time,
        "candle_final": observation.candle_final,
    }
    mapping["slot_observation_sha256"] = _sha256(mapping)
    return mapping


def _observation_from_mapping(mapping: dict[str, Any]) -> FeatureSlotResolutionObservationV4:
    path = mapping["selected_path"]
    dependencies = mapping["dependency_root_sha256s"]
    if path is not None and type(path) is not list:
        _fail("FEATURE_RESOLUTION_TRACE_V4_SELECTED_PATH_INVALID")
    if type(dependencies) is not list:
        _fail("FEATURE_RESOLUTION_TRACE_V4_DEPENDENCY_ROOTS_INVALID")
    try:
        return build_feature_slot_resolution_observation_v4(
            abi_index=mapping["abi_index"],
            feature_name=mapping["feature_name"],
            resolution_status=mapping["resolution_status"],
            selected_payload=mapping["selected_payload"],
            selected_key=mapping["selected_key"],
            selected_path=None if path is None else tuple(path),
            selected_alias=mapping["selected_alias"],
            resolver_version=mapping["resolver_version"],
            resolver_code_sha256=mapping["resolver_code_sha256"],
            resolver_config_sha256=mapping["resolver_config_sha256"],
            transform_id=mapping["transform_id"],
            transform_version=mapping["transform_version"],
            transform_code_sha256=mapping["transform_code_sha256"],
            transform_config_sha256=mapping["transform_config_sha256"],
            resolved_value=mapping["resolved_value"],
            negative_reason=mapping["negative_reason"],
            source_root_sha256=mapping["source_root_sha256"],
            dependency_root_sha256s=tuple(dependencies),
            negative_evidence_sha256=mapping["negative_evidence_sha256"],
            event_time=mapping["event_time"],
            ingested_at=mapping["ingested_at"],
            available_at=mapping["available_at"],
            generated_at=mapping["generated_at"],
            feature_cutoff=mapping["feature_cutoff"],
            decision_time=mapping["decision_time"],
            masa_feature_cutoff=mapping["masa_feature_cutoff"],
            execution_time=mapping["execution_time"],
            consumer_observed_at=mapping["consumer_observed_at"],
            candle_close_time=mapping["candle_close_time"],
            candle_final=mapping["candle_final"],
        )
    except FeatureResolutionObservationV4ValidationError as exc:
        raise FeatureResolutionTraceV4ValidationError(*exc.reasons) from exc


def build_feature_resolution_trace_v4(
    *,
    tensor: FeatureTensorRecord,
    raw_context_sha256: str,
    observations: Sequence[FeatureSlotResolutionObservationV4],
) -> FeatureResolutionTraceArtifactV4:
    """Bind exactly 446 explicit observations without changing tensor bytes."""

    if not _valid_sha256(raw_context_sha256):
        _fail("FEATURE_RESOLUTION_TRACE_V4_RAW_CONTEXT_SHA256_INVALID")
    names, configured_sources, requirements = _model_contract()
    values, model_bytes = _validate_tensor(tensor, names)
    if type(observations) not in (tuple, list) or len(observations) != len(names):
        _fail("FEATURE_RESOLUTION_TRACE_V4_OBSERVATION_COUNT_MISMATCH")
    slots: list[dict[str, Any]] = []
    required_negative: list[str] = []
    optional_negative: list[str] = []
    for index, (name, source, requirement, observation) in enumerate(
        zip(names, configured_sources, requirements, observations, strict=True)
    ):
        if type(observation) is not FeatureSlotResolutionObservationV4:
            _fail("FEATURE_RESOLUTION_TRACE_V4_EXACT_OBSERVATION_TYPE_REQUIRED")
        if (
            observation.abi_index != index
            or observation.feature_name != name
            or observation.decision_time != tensor.decision_time
        ):
            _fail("FEATURE_RESOLUTION_TRACE_V4_OBSERVATION_ORDER_OR_CLOCK_MISMATCH")
        slot = _observation_mapping(
            observation,
            requirement=requirement,
            configured_source=source,
            resolved_source=tensor.source_labels[index],
            tensor_value=values[index],
            missing=tensor.missing_mask[index],
            stale=tensor.stale_mask[index],
            available=tensor.source_availability[index],
        )
        slots.append(slot)
        if observation.resolution_status == RESOLUTION_STATUS_TYPED_NEGATIVE:
            (required_negative if requirement == "REQUIRED" else optional_negative).append(name)
    binding = {
        "tensor_id": tensor.tensor_id,
        "symbol": tensor.symbol,
        "timeframe": tensor.timeframe,
        "feature_snapshot_id": tensor.feature_snapshot_id,
        "source_lineage_sha256": tensor.source_lineage_hash,
        "decision_time": tensor.decision_time,
        "ordered_feature_names_sha256": stable_sha256(list(names)),
        "ordered_source_labels_sha256": stable_sha256(list(tensor.source_labels)),
        "missing_mask_sha256": stable_sha256(list(tensor.missing_mask)),
        "stale_mask_sha256": stable_sha256(list(tensor.stale_mask)),
        "source_availability_mask_sha256": stable_sha256(list(tensor.source_availability)),
        "model_vector_float32_be_sha256": hashlib.sha256(model_bytes).hexdigest(),
        "model_vector_float32_be_byte_count": len(model_bytes),
    }
    resolved_count = sum(slot["resolution_status"] == RESOLUTION_STATUS_RESOLVED for slot in slots)
    trace: dict[str, Any] = {
        "schema_version": FEATURE_RESOLUTION_TRACE_V4_SCHEMA_VERSION,
        "evidence_classification": FEATURE_RESOLUTION_TRACE_V4_EVIDENCE_CLASSIFICATION,
        "downstream_status": FEATURE_RESOLUTION_TRACE_V4_DOWNSTREAM_STATUS,
        "feature_abi_sha256": FEATURE_RESOLUTION_TRACE_V4_ABI_SHA256,
        "feature_requirement_policy_id": FEATURE_REQUIREMENT_POLICY_ID,
        "feature_slot_count": len(names),
        "required_slot_count": requirements.count("REQUIRED"),
        "optional_slot_count": requirements.count("OPTIONAL_EVENT_DEPENDENT"),
        "raw_context_sha256": raw_context_sha256,
        "tensor_binding": binding,
        "slot_observations": slots,
        "slot_observation_graph_sha256": stable_sha256(
            [slot["slot_observation_sha256"] for slot in slots]
        ),
        "resolved_slot_count": resolved_count,
        "typed_negative_slot_count": len(slots) - resolved_count,
        "required_typed_negative_feature_names": required_negative,
        "optional_typed_negative_feature_names": optional_negative,
        "complete_slot_observation_set": True,
        "structural_integrity_valid": True,
        "declared_point_in_time_order_valid": True,
        "required_value_contract_valid": not required_negative,
        "audit_trace_only": True,
        **{name: False for name in _FALSE_FIELDS},
    }
    trace["trace_sha256"] = _sha256(trace)
    return validate_feature_resolution_trace_v4(trace)


def _validate_trace_mapping(value: object) -> dict[str, Any]:
    trace = _exact_dict(value, _TRACE_FIELDS, "FEATURE_RESOLUTION_TRACE_V4_FIELDS_INVALID")
    expected = {
        "schema_version": FEATURE_RESOLUTION_TRACE_V4_SCHEMA_VERSION,
        "evidence_classification": FEATURE_RESOLUTION_TRACE_V4_EVIDENCE_CLASSIFICATION,
        "downstream_status": FEATURE_RESOLUTION_TRACE_V4_DOWNSTREAM_STATUS,
        "feature_abi_sha256": FEATURE_RESOLUTION_TRACE_V4_ABI_SHA256,
        "feature_requirement_policy_id": FEATURE_REQUIREMENT_POLICY_ID,
        "feature_slot_count": FEATURE_RESOLUTION_TRACE_V4_SLOT_COUNT,
        "required_slot_count": FEATURE_RESOLUTION_TRACE_V4_REQUIRED_SLOT_COUNT,
        "optional_slot_count": FEATURE_RESOLUTION_TRACE_V4_OPTIONAL_SLOT_COUNT,
        "complete_slot_observation_set": True,
        "structural_integrity_valid": True,
        "declared_point_in_time_order_valid": True,
        "audit_trace_only": True,
        **{name: False for name in _FALSE_FIELDS},
    }
    if any(
        type(trace.get(key)) is not type(expected_value) or trace.get(key) != expected_value
        for key, expected_value in expected.items()
    ):
        _fail("FEATURE_RESOLUTION_TRACE_V4_CONSTANT_OR_FLAG_MISMATCH")
    if not _valid_sha256(trace["raw_context_sha256"]):
        _fail("FEATURE_RESOLUTION_TRACE_V4_RAW_CONTEXT_SHA256_INVALID")
    names, configured_sources, requirements = _model_contract()
    binding = _exact_dict(
        trace["tensor_binding"],
        _TENSOR_BINDING_FIELDS,
        "FEATURE_RESOLUTION_TRACE_V4_TENSOR_BINDING_INVALID",
    )
    if any(
        not _valid_label(binding[field])
        for field in ("tensor_id", "symbol", "timeframe", "feature_snapshot_id", "decision_time")
    ):
        _fail("FEATURE_RESOLUTION_TRACE_V4_TENSOR_BINDING_IDENTITY_INVALID")
    if any(
        not _valid_sha256(binding[field])
        for field in _TENSOR_BINDING_FIELDS
        if field.endswith("sha256")
    ):
        _fail("FEATURE_RESOLUTION_TRACE_V4_TENSOR_BINDING_SHA256_INVALID")
    expected_model_byte_count = FEATURE_RESOLUTION_TRACE_V4_SLOT_COUNT * 4 * 4
    if (
        type(binding["model_vector_float32_be_byte_count"]) is not int
        or binding["model_vector_float32_be_byte_count"] != expected_model_byte_count
    ):
        _fail("FEATURE_RESOLUTION_TRACE_V4_MODEL_VECTOR_BYTE_COUNT_INVALID")

    raw_slots = trace["slot_observations"]
    if type(raw_slots) is not list or len(raw_slots) != len(names):
        _fail("FEATURE_RESOLUTION_TRACE_V4_OBSERVATION_SET_INCOMPLETE")
    slots: list[dict[str, Any]] = []
    values: list[float] = []
    missing: list[int] = []
    stale: list[int] = []
    available: list[int] = []
    resolved_sources: list[str] = []
    for index, (name, configured_source, requirement, raw_slot) in enumerate(
        zip(names, configured_sources, requirements, raw_slots, strict=True)
    ):
        slot = _exact_dict(
            raw_slot,
            _OBSERVATION_FIELDS,
            "FEATURE_RESOLUTION_TRACE_V4_SLOT_FIELDS_INVALID",
        )
        tensor_value = _canonical_artifact_float32(
            slot["tensor_value"],
            field_name="TENSOR_VALUE",
        )
        if slot["resolution_status"] == RESOLUTION_STATUS_RESOLVED:
            resolved_value = _canonical_artifact_float32(
                slot["resolved_value"],
                field_name="RESOLVED_VALUE",
            )
            if resolved_value != tensor_value:
                _fail("FEATURE_RESOLUTION_TRACE_V4_RESOLVED_RAW_SCALAR_MISMATCH")
        observation = _observation_from_mapping(slot)
        if (
            slot["schema_version"] != FEATURE_RESOLUTION_OBSERVATION_V4_SCHEMA_VERSION
            or observation.abi_index != index
            or observation.feature_name != name
            or slot["requirement_class"] != requirement
            or slot["configured_source_label"] != configured_source
            or not _valid_label(slot["resolved_source_label"])
            or observation.decision_time != binding["decision_time"]
        ):
            _fail("FEATURE_RESOLUTION_TRACE_V4_SLOT_BINDING_MISMATCH")
        for mask_name in ("missing_mask", "stale_mask", "source_availability_mask"):
            if type(slot[mask_name]) is not int or slot[mask_name] not in (0, 1):
                _fail("FEATURE_RESOLUTION_TRACE_V4_SLOT_MASK_INVALID")
        if slot["source_availability_mask"] != 1 - slot["missing_mask"]:
            _fail("FEATURE_RESOLUTION_TRACE_V4_SLOT_MISSING_AVAILABILITY_MISMATCH")
        if slot["missing_mask"] == 1 and tensor_value != 0.0:
            _fail("FEATURE_RESOLUTION_TRACE_V4_SLOT_MISSING_VALUE_NOT_ZERO")
        if observation.resolution_status == RESOLUTION_STATUS_RESOLVED:
            if (slot["missing_mask"], slot["stale_mask"], slot["source_availability_mask"]) != (
                0,
                0,
                1,
            ):
                _fail("FEATURE_RESOLUTION_TRACE_V4_RESOLVED_MASK_BINDING_MISMATCH")
            if canonical_float32_v4(observation.resolved_value) != tensor_value:
                _fail("FEATURE_RESOLUTION_TRACE_V4_RESOLVED_VALUE_BINDING_MISMATCH")
        else:
            if not (
                slot["missing_mask"] == 1
                or slot["stale_mask"] == 1
                or slot["source_availability_mask"] == 0
            ):
                _fail("FEATURE_RESOLUTION_TRACE_V4_NEGATIVE_MASK_BINDING_MISMATCH")
            if (slot["stale_mask"] == 1) is not (
                observation.negative_reason == NEGATIVE_SOURCE_STALE
            ):
                _fail("FEATURE_RESOLUTION_TRACE_V4_STALE_REASON_MASK_MISMATCH")
        material = {key: item for key, item in slot.items() if key != "slot_observation_sha256"}
        if not _valid_sha256(slot["slot_observation_sha256"]) or slot[
            "slot_observation_sha256"
        ] != _sha256(material):
            _fail("FEATURE_RESOLUTION_TRACE_V4_SLOT_SHA256_MISMATCH")
        slots.append(slot)
        values.append(tensor_value)
        missing.append(slot["missing_mask"])
        stale.append(slot["stale_mask"])
        available.append(slot["source_availability_mask"])
        resolved_sources.append(slot["resolved_source_label"])

    model_bytes = _model_bytes(values, missing, stale, available)
    reconstructed = {
        "ordered_feature_names_sha256": stable_sha256(list(names)),
        "ordered_source_labels_sha256": stable_sha256(resolved_sources),
        "missing_mask_sha256": stable_sha256(missing),
        "stale_mask_sha256": stable_sha256(stale),
        "source_availability_mask_sha256": stable_sha256(available),
        "model_vector_float32_be_sha256": hashlib.sha256(model_bytes).hexdigest(),
        "model_vector_float32_be_byte_count": len(model_bytes),
    }
    if any(binding[key] != expected_value for key, expected_value in reconstructed.items()):
        _fail("FEATURE_RESOLUTION_TRACE_V4_TENSOR_BINDING_RECONSTRUCTION_MISMATCH")
    slot_hashes = [slot["slot_observation_sha256"] for slot in slots]
    if trace["slot_observation_graph_sha256"] != stable_sha256(slot_hashes):
        _fail("FEATURE_RESOLUTION_TRACE_V4_OBSERVATION_GRAPH_MISMATCH")
    negatives = [
        slot for slot in slots if slot["resolution_status"] == RESOLUTION_STATUS_TYPED_NEGATIVE
    ]
    required_negative = [
        slot["feature_name"] for slot in negatives if slot["requirement_class"] == "REQUIRED"
    ]
    optional_negative = [
        slot["feature_name"]
        for slot in negatives
        if slot["requirement_class"] == "OPTIONAL_EVENT_DEPENDENT"
    ]
    if (
        type(trace["resolved_slot_count"]) is not int
        or trace["resolved_slot_count"] != len(slots) - len(negatives)
        or type(trace["typed_negative_slot_count"]) is not int
        or trace["typed_negative_slot_count"] != len(negatives)
        or trace["required_typed_negative_feature_names"] != required_negative
        or trace["optional_typed_negative_feature_names"] != optional_negative
        or trace["required_value_contract_valid"] is not (not required_negative)
    ):
        _fail("FEATURE_RESOLUTION_TRACE_V4_SUMMARY_BINDING_MISMATCH")
    normalized = {**trace, "tensor_binding": binding, "slot_observations": slots}
    material = {key: item for key, item in normalized.items() if key != "trace_sha256"}
    if not _valid_sha256(trace["trace_sha256"]) or trace["trace_sha256"] != _sha256(material):
        _fail("FEATURE_RESOLUTION_TRACE_V4_SHA256_MISMATCH")
    return normalized


def validate_feature_resolution_trace_v4(value: object) -> FeatureResolutionTraceArtifactV4:
    """Validate and freeze one exact caller-supplied trace mapping."""

    validated = _validate_trace_mapping(value)
    return FeatureResolutionTraceArtifactV4(
        schema_version=FEATURE_RESOLUTION_TRACE_V4_SCHEMA_VERSION,
        trace_sha256=cast(str, validated["trace_sha256"]),
        trace_json=_canonical_json(validated),
        _construction_token=_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "FEATURE_RESOLUTION_TRACE_V4_ABI_SHA256",
    "FEATURE_RESOLUTION_TRACE_V4_DOWNSTREAM_STATUS",
    "FEATURE_RESOLUTION_TRACE_V4_EVIDENCE_CLASSIFICATION",
    "FEATURE_RESOLUTION_TRACE_V4_SCHEMA_VERSION",
    "FEATURE_RESOLUTION_TRACE_V4_SLOT_COUNT",
    "FeatureResolutionTraceArtifactV4",
    "FeatureResolutionTraceV4ValidationError",
    "build_feature_resolution_trace_v4",
    "validate_feature_resolution_trace_v4",
]
