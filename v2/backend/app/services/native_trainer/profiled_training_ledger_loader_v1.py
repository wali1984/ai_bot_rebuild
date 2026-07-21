"""Unwired, fail-closed loader for authenticated profiled training rows.

The durable feature ledger is a mixed audit namespace.  Width alone therefore
never identifies a training sample: a legacy or generic 39-slot record is not
the authenticated ``35 model + 4 causal cost`` profile.  This module admits
only a strict ledger-v3 row carrying the exact enrichment lineage declared
below, reopens its quarantined 35-slot parent, and independently reconstructs
the deployed 446-slot/1784-value model input.

The loader is deliberately not connected to the persistent trainer.  It grants
no prediction, paper, live, or execution authority.  Its fixed-observation
scan is bounded by independently reproduced append/postcommit high-water
receipts before and after the read; movement of that authenticated prefix fails
the whole load closed.

Pagination removes the bounded-page hard stop, not the cost of authentication:
every page still performs full-ledger streaming integrity and fixed-observation
high-water reproduction twice.  This factory path is therefore O(total ledger)
per page and is explicitly not ready for trainer-cadence runtime wiring.  A
future runtime path needs a separately authenticated observation manifest that
later pages can reopen without trusting cursor state or weakening integrity.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.adaptive_ohlcv_feature_selection_profile_v1 import (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
)
from v2.backend.app.services.native_trainer.authenticated_ohlcv_profile_transform_v1 import (
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256,
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_ID,
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256,
)
from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS,
    CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID,
    CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256,
    CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION,
    CAUSAL_COST_ORDERED_FEATURE_NAMES,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    MAX_QUERY_ROWS,
    PROVENANCE_CANONICAL_V3,
    DurableFeatureSnapshotLedger,
    FeatureSnapshotLedgerError,
    FixedCutoffFeatureSnapshot,
    stable_sha256,
    validate_feature_snapshot_record,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.training_sample_identity import (
    FEATURE_HIGH_WATER_SCHEMA_VERSION,
    TrainingSampleIdentityError,
    feature_ledger_fixed_observation_high_water,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    LOGICAL_ENABLED_SLOT_ORDINALS,
    LOGICAL_ENABLED_SLOT_ORDINALS_SHA256,
    LOGICAL_MODEL_FEATURE_COUNT,
    LOGICAL_MODEL_INPUT_COUNT,
    LOGICAL_ORDERED_FEATURE_NAMES,
    LOGICAL_PROFILE_SELECTION_MASK,
    LOGICAL_PROFILE_SELECTION_MASK_SHA256,
    PHYSICAL_MODEL_FEATURE_COUNT,
    PHYSICAL_ORDERED_FEATURE_NAMES,
    PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_CLASSIFICATION,
    PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_IMPLEMENTATION_SHA256,
    PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_SCHEMA_VERSION,
    PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_STATUS,
    PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON,
    PROFILED_MODEL_LOGICAL_PROJECTION_V1_SCHEMA_VERSION,
    PROFILED_MODEL_RECORD_LINEAGE_BINDING_V1_SCHEMA_VERSION,
    PROFILED_MODEL_SOURCE_PROVENANCE_BINDING_V1_SCHEMA_VERSION,
)
from v2.backend.app.services.native_trainer.source_provenance_ledger_v4 import (
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_NAMESPACE,
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION,
    TrainerSourceProvenanceLedgerV4,
    TrainerSourceProvenanceLedgerV4Error,
)

PROFILED_TRAINING_LEDGER_LOADER_V1_SCHEMA_VERSION: Final = "profiled_training_ledger_loader_v1"
PROFILED_TRAINING_PAGE_CURSOR_V1_SCHEMA_VERSION: Final = "profiled_training_ledger_page_cursor_v1"
PROFILED_TRAINING_PAGE_INTEGRITY_SEMANTICS: Final = (
    "FULL_LEDGER_STREAMING_AND_FIXED_OBSERVATION_HIGH_WATER_BEFORE_AND_AFTER_EVERY_PAGE"
)
PROFILED_TRAINING_RUNTIME_SCALABILITY_STATUS: Final = (
    "FACTORY_ONLY_O_TOTAL_LEDGER_PER_PAGE_AUTHENTICATED_OBSERVATION_MANIFEST_REQUIRED"
)
PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_SCHEMA_VERSION: Final = (
    "authenticated_profiled_training_enrichment_lineage_v1"
)
PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY: Final = "authenticated_profiled_training_enrichment_v1"
PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_CLASSIFICATION: Final = (
    "AUTHENTICATED_PARENT_35_PLUS_CAUSAL_COST_4_TRAINING_EVIDENCE"
)
PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_STATUS: Final = (
    "STRICT_TRAINING_CANDIDATE_NO_SERVING_OR_EXECUTION_AUTHORITY"
)
PROFILED_TRAINING_COST_BINDING_V1_SCHEMA_VERSION: Final = "causal_cost_capture_training_binding_v1"
PROFILED_TRAINING_COST_CAPTURE_RECEIPT_CHILD_ROLES: Final = (
    "authoritative_fee_schedule",
    "expected_notional_policy",
    "mark_price",
    "orderbook_depth",
    "orderbook_features",
)
AUXILIARY_LABEL_ONLY_FEATURE_NAMES: Final = CAUSAL_COST_ORDERED_FEATURE_NAMES
PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT: Final = 39
PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES: Final = (
    *PHYSICAL_ORDERED_FEATURE_NAMES,
    *AUXILIARY_LABEL_ONLY_FEATURE_NAMES,
)
PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES_SHA256: Final = stable_sha256(
    list(PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES)
)
PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION: Final = (
    "authenticated_profiled_training_projection_v1"
)
_PROFILED_TRAINING_PROJECTION_IMPLEMENTATION_MATERIAL = {
    "schema_version": PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION,
    "operation": "PHYSICAL_39_PARENT_BOUND_TO_LOGICAL_446_MODEL_INPUT_1784",
    "model_feature_policy": ("FIRST_35_BIT_IDENTICAL_TO_REOPENED_SAME_TRANSACTION_PARENT"),
    "auxiliary_policy": ("FINAL_4_CAUSAL_COST_VALUES_LABEL_ONLY_EXCLUDED_FROM_MODEL_VECTOR"),
    "parent_append_policy": "SAME_APPEND_TRANSACTION_AND_POSTCOMMIT_RECEIPT_REQUIRED",
    "disabled_slot_encoding": {
        "feature_value": 0.0,
        "missing_mask": 0,
        "stale_mask": 0,
        "source_availability_mask": 0,
        "selection_mask": 0,
    },
    "selected_slot_encoding": {
        "missing_mask": 0,
        "stale_mask": 0,
        "source_availability_mask": 1,
        "selection_mask": 1,
    },
    "model_vector_layout": ("VALUES_446_THEN_MISSING_446_THEN_STALE_446_THEN_AVAILABILITY_446"),
    "runtime_wired": False,
}
PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256: Final = stable_sha256(
    _PROFILED_TRAINING_PROJECTION_IMPLEMENTATION_MATERIAL
)
_PROFILED_TRAINING_PROJECTION_CONFIGURATION_MATERIAL = {
    "schema_version": PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION,
    "profile_id": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
    "profile_sha256": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
    "base_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
    "base_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    "physical_ordered_feature_names": list(PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES),
    "physical_ordered_feature_names_sha256": (
        PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES_SHA256
    ),
    "physical_model_feature_count": PHYSICAL_MODEL_FEATURE_COUNT,
    "physical_auxiliary_feature_count": len(AUXILIARY_LABEL_ONLY_FEATURE_NAMES),
    "logical_model_feature_count": LOGICAL_MODEL_FEATURE_COUNT,
    "logical_model_input_count": LOGICAL_MODEL_INPUT_COUNT,
    "logical_enabled_slot_ordinals": list(LOGICAL_ENABLED_SLOT_ORDINALS),
    "logical_enabled_slot_ordinals_sha256": LOGICAL_ENABLED_SLOT_ORDINALS_SHA256,
    "logical_profile_selection_mask_sha256": LOGICAL_PROFILE_SELECTION_MASK_SHA256,
    "auxiliary_label_only_feature_names": list(AUXILIARY_LABEL_ONLY_FEATURE_NAMES),
}
PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256: Final = stable_sha256(
    _PROFILED_TRAINING_PROJECTION_CONFIGURATION_MATERIAL
)

MAX_PROFILED_TRAINING_SCAN_ROWS: Final = 250_000
_MODEL_VECTOR_HASH_DOMAIN = b"canonical_feature_model_vector_v3\0"
_AUXILIARY_VECTOR_HASH_DOMAIN = b"profiled_training_auxiliary_float32_v1\0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_RESULT_TOKEN = object()
_BATCH_TOKEN = object()
_LEDGER_RESERVED_LINEAGE_FIELDS = frozenset(
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
_AUTHORIZATION_FIELDS = frozenset(
    {
        "trainer_admission_authorized",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
        "runtime_wired",
    }
)
_PAGE_CURSOR_FIELDS = frozenset(
    {
        "schema_version",
        "training_observed_at",
        "high_water_sha256",
        "requested_after_sequence",
        "scanned_start_sequence",
        "scanned_end_sequence",
        "scanned_record_count",
        "scan_limit",
        "next_after_sequence",
        "has_remaining_strict_rows",
        "cursor_sha256",
    }
)
_REMAINING_PRESENT = "AT_LEAST_ONE_STRICT_FIXED_OBSERVATION_ROW_AFTER_PAGE"
_REMAINING_ABSENT = "NO_STRICT_FIXED_OBSERVATION_ROW_AFTER_PAGE"
_EXPECTED_AUTHORIZATION = {
    "trainer_admission_authorized": True,
    "prediction_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "runtime_wired": False,
}
_PARENT_FALSE_AUTHORIZATION = {
    "feature_snapshot_published": False,
    "consumer_eligible": False,
    "trainer_admission_authorized": False,
    "prediction_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "runtime_wired": False,
}
_TRAINING_LINEAGE_FIELDS = frozenset(
    {
        "schema_version",
        "classification",
        "status",
        "profile_id",
        "profile_sha256",
        "base_registry_sha256",
        "base_abi_sha256",
        "logical_profile_selection_mask_sha256",
        "logical_enabled_slot_ordinals_sha256",
        "transform_implementation_id",
        "transform_implementation_sha256",
        "transform_configuration_sha256",
        "projection_schema_version",
        "projection_implementation_sha256",
        "projection_configuration_sha256",
        "physical_feature_count",
        "physical_ordered_feature_names_sha256",
        "parent_model_record_binding",
        "cost_capture_binding",
        "authorization",
    }
)
_PARENT_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "durable_snapshot_id",
        "record_sha256",
        "frozen_envelope_sha256",
        "source_lineage_sha256",
        "physical_model_vector_sha256",
        "feature_snapshot_id",
        "profile_id",
        "profile_sha256",
        "capture_set_sha256",
        "transform_artifact_sha256",
        "source_provenance_binding_sha256",
        "logical_profile_selection_mask_sha256",
        "logical_enabled_slot_ordinals",
        "logical_enabled_slot_ordinals_sha256",
        "logical_model_vector_sha256",
        "logical_projection_sha256",
        "feature_cutoff",
        "decision_time",
        "generated_at",
        "authorization",
    }
)
_COST_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "cost_capture_schema_version",
        "cost_capture_implementation_id",
        "cost_capture_implementation_sha256",
        "symbol",
        "decision_time",
        "feature_cutoff",
        "available_at",
        "expected_holding_horizon_seconds",
        "cost_capture_artifact_sha256",
        "cost_capture_artifact_byte_count",
        "cost_capture_receipt_sha256",
        "authoritative_fee_schedule_sha256",
        "expected_notional_policy_sha256",
        "fee_schedule_receipt_sha256",
        "notional_policy_receipt_sha256",
        "orderbook_depth_receipt_sha256",
        "orderbook_features_receipt_sha256",
        "mark_price_receipt_sha256",
        "auxiliary_feature_names",
        "auxiliary_source_labels",
        "auxiliary_feature_receipt_sha256s",
        "auxiliary_values_float32_sha256",
    }
)
_SOURCE_PROVENANCE_FIELDS = frozenset(
    {
        "schema_version",
        "source_ledger_schema_version",
        "source_ledger_namespace",
        "source_ledger_root",
        "source_ledger_root_sha256",
        "timeframe_bindings",
        "provenance_recorded_before_transform",
        "source_provenance_binding_sha256",
    }
)
_SOURCE_TIMEFRAME_BINDING_FIELDS = frozenset(
    {
        "physical_timeframe",
        "source_ledger_sequence",
        "source_ledger_entry_sha256",
        "source_ledger_entry_json_sha256",
        "source_replay_identity_sha256",
        "source_cycle_identity_sha256",
        "trainer_run_id",
        "trainer_cycle_id",
        "source_ledger_recorded_at",
        "source_key",
        "source_key_version",
        "atomic_batch_id",
        "atomic_batch_material_sha256",
        "atomic_consumer_observed_at",
        "suffix_manifest_sha256",
        "suffix_manifest_cas_address",
        "suffix_digest_sha256",
        "capture_selected_start_ordinal",
        "capture_selected_row_count",
        "capture_ordered_row_identity_sha256s",
        "capture_ordered_source_receipt_sha256s",
        "capture_timeframe_sha256",
        "timeframe_source_provenance_binding_sha256",
    }
)
_IMMUTABLE_COST_LOCATORS = frozenset({"FILE_CONTENT_ADDRESS", "SQLITE_IMMUTABLE_ROW"})


class ProfiledTrainingLedgerLoaderV1Error(RuntimeError):
    """A fixed-observation profiled training inventory failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledTrainingLedgerLoaderV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _exact_dict(
    value: object,
    fields: frozenset[str],
    *,
    reason: str,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        _fail(reason)
    return cast(dict[str, Any], value)


def _clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or not value or value != value.strip():
        _fail(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    normalized = parsed.astimezone(UTC)
    canonical = normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if canonical != value:
        _fail(reason)
    return normalized


def _canonical_clock(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (OverflowError, RecursionError, TypeError, ValueError):
        _fail("PROFILED_TRAINING_PAGE_CURSOR_JSON_INVALID")


def _parse_page_cursor(value: object) -> dict[str, Any]:
    if type(value) is not str or not value or len(value) > 16_384:
        _fail("PROFILED_TRAINING_PAGE_CURSOR_INVALID")
    try:
        parsed = json.loads(cast(str, value))
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
        _fail("PROFILED_TRAINING_PAGE_CURSOR_INVALID")
    cursor = _exact_dict(
        parsed,
        _PAGE_CURSOR_FIELDS,
        reason="PROFILED_TRAINING_PAGE_CURSOR_FIELDS_INVALID",
    )
    if _canonical_json(cursor) != value:
        _fail("PROFILED_TRAINING_PAGE_CURSOR_NOT_CANONICAL")
    unsigned = {key: item for key, item in cursor.items() if key != "cursor_sha256"}
    requested = cursor.get("requested_after_sequence")
    start = cursor.get("scanned_start_sequence")
    end = cursor.get("scanned_end_sequence")
    count = cursor.get("scanned_record_count")
    limit = cursor.get("scan_limit")
    following = cursor.get("next_after_sequence")
    if (
        cursor.get("schema_version") != PROFILED_TRAINING_PAGE_CURSOR_V1_SCHEMA_VERSION
        or not _valid_sha256(cursor.get("high_water_sha256"))
        or not _valid_sha256(cursor.get("cursor_sha256"))
        or cursor.get("cursor_sha256") != stable_sha256(unsigned)
        or type(requested) is not int
        or requested < 0
        or type(start) is not int
        or start <= requested
        or type(end) is not int
        or end < start
        or type(count) is not int
        or count <= 0
        or type(limit) is not int
        or limit <= 0
        or count > limit
        or type(following) is not int
        or following != end
        or cursor.get("has_remaining_strict_rows") is not True
    ):
        _fail("PROFILED_TRAINING_PAGE_CURSOR_BINDING_INVALID")
    _clock(
        cursor.get("training_observed_at"),
        reason="PROFILED_TRAINING_PAGE_CURSOR_OBSERVATION_INVALID",
    )
    return cursor


def _build_page_cursor(
    *,
    training_observed_at: str,
    high_water_sha256: str,
    requested_after_sequence: int,
    scanned_start_sequence: int,
    scanned_end_sequence: int,
    scanned_record_count: int,
    scan_limit: int,
) -> str:
    material = {
        "schema_version": PROFILED_TRAINING_PAGE_CURSOR_V1_SCHEMA_VERSION,
        "training_observed_at": training_observed_at,
        "high_water_sha256": high_water_sha256,
        "requested_after_sequence": requested_after_sequence,
        "scanned_start_sequence": scanned_start_sequence,
        "scanned_end_sequence": scanned_end_sequence,
        "scanned_record_count": scanned_record_count,
        "scan_limit": scan_limit,
        "next_after_sequence": scanned_end_sequence,
        "has_remaining_strict_rows": True,
    }
    cursor = {**material, "cursor_sha256": stable_sha256(material)}
    encoded = _canonical_json(cursor)
    _parse_page_cursor(encoded)
    return encoded


def _float32(value: object, *, reason: str) -> float:
    if type(value) not in {int, float}:
        _fail(reason)
    try:
        numeric = float(cast(int | float, value))
        canonical = struct.unpack(">f", struct.pack(">f", numeric))[0]
    except (OverflowError, struct.error, TypeError, ValueError):
        _fail(reason)
    if not math.isfinite(numeric) or not math.isfinite(canonical):
        _fail(reason)
    if numeric != 0.0 and canonical == 0.0:
        _fail(reason)
    return 0.0 if canonical == 0.0 else canonical


def _float32_vector(values: object, *, expected: int, reason: str) -> tuple[float, ...]:
    if type(values) not in {list, tuple} or len(cast(Sequence[object], values)) != expected:
        _fail(reason)
    return tuple(_float32(item, reason=reason) for item in cast(Sequence[object], values))


def _model_vector_sha256(model_vector: Sequence[float]) -> str:
    if len(model_vector) != LOGICAL_MODEL_INPUT_COUNT:
        _fail("PROFILED_TRAINING_LOGICAL_MODEL_VECTOR_DIMENSION_INVALID")
    digest = hashlib.sha256()
    digest.update(_MODEL_VECTOR_HASH_DOMAIN)
    digest.update(bytes.fromhex(FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256))
    digest.update(struct.pack(">I", LOGICAL_MODEL_FEATURE_COUNT))
    for value in model_vector:
        digest.update(
            struct.pack(
                ">f",
                _float32(
                    value,
                    reason="PROFILED_TRAINING_MODEL_VECTOR_VALUE_INVALID",
                ),
            )
        )
    return digest.hexdigest()


def _auxiliary_values_sha256(values: Sequence[float]) -> str:
    if len(values) != len(AUXILIARY_LABEL_ONLY_FEATURE_NAMES):
        _fail("PROFILED_TRAINING_AUXILIARY_VALUE_COUNT_INVALID")
    digest = hashlib.sha256()
    digest.update(_AUXILIARY_VECTOR_HASH_DOMAIN)
    for name, value in zip(AUXILIARY_LABEL_ONLY_FEATURE_NAMES, values, strict=True):
        encoded_name = name.encode("ascii", errors="strict")
        digest.update(struct.pack(">H", len(encoded_name)))
        digest.update(encoded_name)
        digest.update(
            struct.pack(
                ">f",
                _float32(
                    value,
                    reason="PROFILED_TRAINING_AUXILIARY_VALUE_INVALID",
                ),
            )
        )
    return digest.hexdigest()


def _logical_projection(
    *,
    physical_model_values: Sequence[float],
    source_labels: Sequence[str],
    receipt_roots: Sequence[str],
) -> tuple[dict[str, Any], tuple[float, ...]]:
    if not (
        len(physical_model_values)
        == len(source_labels)
        == len(receipt_roots)
        == PHYSICAL_MODEL_FEATURE_COUNT
    ):
        _fail("PROFILED_TRAINING_PARENT_MODEL_DIMENSION_INVALID")
    values = [0.0] * LOGICAL_MODEL_FEATURE_COUNT
    missing = [0] * LOGICAL_MODEL_FEATURE_COUNT
    stale = [0] * LOGICAL_MODEL_FEATURE_COUNT
    availability = [0] * LOGICAL_MODEL_FEATURE_COUNT
    logical_labels: list[str | None] = [None] * LOGICAL_MODEL_FEATURE_COUNT
    logical_roots: list[str | None] = [None] * LOGICAL_MODEL_FEATURE_COUNT
    for physical_ordinal, logical_ordinal in enumerate(
        ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.enabled_slot_ordinals
    ):
        values[logical_ordinal] = physical_model_values[physical_ordinal]
        availability[logical_ordinal] = 1
        logical_labels[logical_ordinal] = source_labels[physical_ordinal]
        logical_roots[logical_ordinal] = receipt_roots[physical_ordinal]
    if tuple(availability) != LOGICAL_PROFILE_SELECTION_MASK:
        _fail("PROFILED_TRAINING_SELECTION_MASK_RECONSTRUCTION_INVALID")
    model_vector = (
        *values,
        *(float(item) for item in missing),
        *(float(item) for item in stale),
        *(float(item) for item in availability),
    )
    model_vector_sha256 = _model_vector_sha256(model_vector)
    material: dict[str, Any] = {
        "schema_version": PROFILED_MODEL_LOGICAL_PROJECTION_V1_SCHEMA_VERSION,
        "profile_id": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
        "profile_sha256": ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
        "base_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "base_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        "ordered_feature_names": list(LOGICAL_ORDERED_FEATURE_NAMES),
        "feature_values": values,
        "missing_mask": missing,
        "stale_mask": stale,
        "source_availability_mask": availability,
        "profile_selection_mask": list(LOGICAL_PROFILE_SELECTION_MASK),
        "profile_selection_mask_sha256": LOGICAL_PROFILE_SELECTION_MASK_SHA256,
        "enabled_slot_ordinals": list(LOGICAL_ENABLED_SLOT_ORDINALS),
        "enabled_slot_ordinals_sha256": LOGICAL_ENABLED_SLOT_ORDINALS_SHA256,
        "feature_source_labels": logical_labels,
        "feature_source_receipt_sha256s": logical_roots,
        "model_vector_length": LOGICAL_MODEL_INPUT_COUNT,
        "model_vector_sha256": model_vector_sha256,
    }
    material["logical_projection_sha256"] = stable_sha256(material)
    return material, tuple(model_vector)


def _core_lineage(envelope: Mapping[str, Any]) -> dict[str, Any]:
    lineage = envelope.get("source_lineage_material")
    if type(lineage) is not dict:
        _fail("PROFILED_TRAINING_SOURCE_LINEAGE_INVALID")
    return {
        key: value
        for key, value in cast(dict[str, Any], lineage).items()
        if key not in _LEDGER_RESERVED_LINEAGE_FIELDS
    }


def _validate_source_provenance_binding(
    binding_value: object,
    *,
    transform_available_at: datetime,
    decision_time: datetime,
) -> str:
    binding = _exact_dict(
        binding_value,
        _SOURCE_PROVENANCE_FIELDS,
        reason="PROFILED_TRAINING_PARENT_SOURCE_PROVENANCE_FIELDS_INVALID",
    )
    root = binding.get("source_ledger_root")
    if (
        binding.get("schema_version") != PROFILED_MODEL_SOURCE_PROVENANCE_BINDING_V1_SCHEMA_VERSION
        or binding.get("source_ledger_schema_version")
        != TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION
        or binding.get("source_ledger_namespace") != TRAINER_SOURCE_PROVENANCE_LEDGER_V4_NAMESPACE
        or type(root) is not str
        or not root.startswith("/")
        or "\x00" in root
        or binding.get("source_ledger_root_sha256")
        != hashlib.sha256(cast(str, root).encode("utf-8")).hexdigest()
        or binding.get("provenance_recorded_before_transform") is not True
    ):
        _fail("PROFILED_TRAINING_PARENT_SOURCE_PROVENANCE_IDENTITY_INVALID")
    claimed_sha = binding.get("source_provenance_binding_sha256")
    unsigned = {
        key: value for key, value in binding.items() if key != "source_provenance_binding_sha256"
    }
    if not _valid_sha256(claimed_sha) or claimed_sha != stable_sha256(unsigned):
        _fail("PROFILED_TRAINING_PARENT_SOURCE_PROVENANCE_SHA256_INVALID")
    root_path = Path(cast(str, root))
    if not root_path.is_dir():
        _fail("PROFILED_TRAINING_PARENT_SOURCE_LEDGER_ROOT_MISSING")
    try:
        fresh_entries = TrainerSourceProvenanceLedgerV4(root_path).read_entries()
    except TrainerSourceProvenanceLedgerV4Error as exc:
        raise ProfiledTrainingLedgerLoaderV1Error(
            "PROFILED_TRAINING_PARENT_SOURCE_LEDGER_FRESH_READ_FAILED"
        ) from exc
    raw_timeframes = binding.get("timeframe_bindings")
    if type(raw_timeframes) is not list or len(raw_timeframes) != 2:
        _fail("PROFILED_TRAINING_PARENT_SOURCE_PROVENANCE_TIMEFRAMES_INVALID")
    timeframes = cast(list[object], raw_timeframes)
    sequences: list[int] = []
    for expected_timeframe, raw_item in zip(("5m", "1h"), timeframes, strict=True):
        item = _exact_dict(
            raw_item,
            _SOURCE_TIMEFRAME_BINDING_FIELDS,
            reason="PROFILED_TRAINING_PARENT_SOURCE_TIMEFRAME_FIELDS_INVALID",
        )
        item_sha = item.get("timeframe_source_provenance_binding_sha256")
        item_unsigned = {
            key: value
            for key, value in item.items()
            if key != "timeframe_source_provenance_binding_sha256"
        }
        sequence = item.get("source_ledger_sequence")
        row_count = item.get("capture_selected_row_count")
        rows = item.get("capture_ordered_row_identity_sha256s")
        receipts = item.get("capture_ordered_source_receipt_sha256s")
        recorded = _clock(
            item.get("source_ledger_recorded_at"),
            reason="PROFILED_TRAINING_PARENT_SOURCE_RECORDED_AT_INVALID",
        )
        observed = _clock(
            item.get("atomic_consumer_observed_at"),
            reason="PROFILED_TRAINING_PARENT_SOURCE_OBSERVED_AT_INVALID",
        )
        if (
            item.get("physical_timeframe") != expected_timeframe
            or type(sequence) is not int
            or sequence <= 0
            or type(row_count) is not int
            or row_count <= 0
            or type(rows) is not list
            or type(receipts) is not list
            or len(rows) != row_count
            or len(receipts) != row_count
            or any(not _valid_sha256(value) for value in (*rows, *receipts))
            or any(
                not _valid_sha256(item.get(name))
                for name in (
                    "source_ledger_entry_sha256",
                    "source_ledger_entry_json_sha256",
                    "source_replay_identity_sha256",
                    "source_cycle_identity_sha256",
                    "atomic_batch_material_sha256",
                    "suffix_manifest_sha256",
                    "suffix_digest_sha256",
                    "capture_timeframe_sha256",
                )
            )
            or not _valid_sha256(item_sha)
            or item_sha != stable_sha256(item_unsigned)
            or recorded > transform_available_at
            or observed > transform_available_at
            or transform_available_at > decision_time
        ):
            _fail("PROFILED_TRAINING_PARENT_SOURCE_TIMEFRAME_BINDING_INVALID")
        if sequence > len(fresh_entries):
            _fail("PROFILED_TRAINING_PARENT_SOURCE_LEDGER_ENTRY_MISSING")
        fresh_entry = fresh_entries[sequence - 1]
        fresh_record = fresh_entry.record
        fresh_source = fresh_record.get("source_capture")
        fresh_manifest = fresh_record.get("suffix_manifest")
        fresh_rows = fresh_record.get("ordered_rows")
        start = item.get("capture_selected_start_ordinal")
        if (
            type(fresh_source) is not dict
            or type(fresh_manifest) is not dict
            or type(fresh_rows) is not list
            or type(start) is not int
            or start < 0
            or start + row_count > len(fresh_rows)
            or fresh_entry.entry_sha256 != item["source_ledger_entry_sha256"]
            or hashlib.sha256(fresh_entry.entry_json.encode("ascii")).hexdigest()
            != item["source_ledger_entry_json_sha256"]
            or fresh_entry.replay_identity_sha256 != item["source_replay_identity_sha256"]
            or fresh_entry.cycle_identity_sha256 != item["source_cycle_identity_sha256"]
            or fresh_entry.trainer_run_id != item["trainer_run_id"]
            or fresh_entry.trainer_cycle_id != item["trainer_cycle_id"]
            or fresh_record.get("ledger_recorded_at") != item["source_ledger_recorded_at"]
            or fresh_source.get("source_key") != item["source_key"]
            or fresh_source.get("source_key_version") != item["source_key_version"]
            or fresh_source.get("atomic_batch_id") != item["atomic_batch_id"]
            or fresh_source.get("atomic_batch_material_sha256")
            != item["atomic_batch_material_sha256"]
            or fresh_source.get("consumer_observed_at") != item["atomic_consumer_observed_at"]
            or fresh_manifest.get("exact_manifest_sha256") != item["suffix_manifest_sha256"]
            or fresh_manifest.get("manifest_cas_address") != item["suffix_manifest_cas_address"]
            or fresh_manifest.get("suffix_digest_sha256") != item["suffix_digest_sha256"]
            or [
                row.get("source_read_receipt_sha256")
                for row in fresh_rows[start : start + row_count]
            ]
            != item["capture_ordered_source_receipt_sha256s"]
        ):
            _fail("PROFILED_TRAINING_PARENT_SOURCE_LEDGER_ENTRY_BINDING_INVALID")
        sequences.append(sequence)
    if len(set(sequences)) != 2:
        _fail("PROFILED_TRAINING_PARENT_SOURCE_SEQUENCE_DUPLICATE")
    return cast(str, claimed_sha)


def _validate_parent_model_record(parent: FixedCutoffFeatureSnapshot) -> dict[str, Any]:
    record = parent.record
    try:
        validated = validate_feature_snapshot_record(record)
    except Exception as exc:
        raise ProfiledTrainingLedgerLoaderV1Error(
            "PROFILED_TRAINING_PARENT_LEDGER_RECORD_INVALID"
        ) from exc
    if type(record) is not dict or validated.get("record") != record:
        _fail("PROFILED_TRAINING_PARENT_LEDGER_RECORD_NOT_CANONICAL")
    envelope = record.get("frozen_envelope")
    if type(envelope) is not dict:
        _fail("PROFILED_TRAINING_PARENT_ENVELOPE_INVALID")
    typed_envelope = cast(dict[str, Any], envelope)
    core = _core_lineage(typed_envelope)
    decision = _clock(
        typed_envelope.get("tensor_decision_time"),
        reason="PROFILED_TRAINING_PARENT_DECISION_TIME_INVALID",
    )
    transform_available = _clock(
        core.get("transform_available_at"),
        reason="PROFILED_TRAINING_PARENT_TRANSFORM_AVAILABLE_AT_INVALID",
    )
    if (
        core.get("schema_version") != PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_SCHEMA_VERSION
        or core.get("classification") != PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_CLASSIFICATION
        or core.get("status") != PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_STATUS
        or core.get("implementation_sha256")
        != PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_IMPLEMENTATION_SHA256
        or core.get("unwired_reason") != PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON
        or core.get("profile_id") != ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID
        or core.get("profile_sha256") != ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256
        or core.get("physical_model_feature_count") != PHYSICAL_MODEL_FEATURE_COUNT
        or core.get("transform_implementation_id")
        != AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_ID
        or core.get("transform_implementation_sha256")
        != AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256
        or core.get("transform_configuration_sha256")
        != AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
        or core.get("authorization") != _PARENT_FALSE_AUTHORIZATION
        or typed_envelope.get("strict_training_eligible") is not False
        or typed_envelope.get("temporal_rejection_reasons")
        != [PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON]
        or typed_envelope.get("ordered_feature_names") != list(PHYSICAL_ORDERED_FEATURE_NAMES)
        or typed_envelope.get("missing_mask") != [0] * PHYSICAL_MODEL_FEATURE_COUNT
        or typed_envelope.get("stale_mask") != [0] * PHYSICAL_MODEL_FEATURE_COUNT
        or typed_envelope.get("source_availability_mask") != [1] * PHYSICAL_MODEL_FEATURE_COUNT
    ):
        _fail("PROFILED_TRAINING_PARENT_MODEL_CONTRACT_INVALID")
    source_binding_sha = _validate_source_provenance_binding(
        core.get("source_provenance_binding"),
        transform_available_at=transform_available,
        decision_time=decision,
    )
    values = _float32_vector(
        typed_envelope.get("feature_values"),
        expected=PHYSICAL_MODEL_FEATURE_COUNT,
        reason="PROFILED_TRAINING_PARENT_MODEL_VALUES_INVALID",
    )
    labels_raw = typed_envelope.get("ordered_feature_source_labels")
    roots_raw = typed_envelope.get("feature_source_receipt_sha256s")
    if (
        type(labels_raw) is not list
        or len(labels_raw) != PHYSICAL_MODEL_FEATURE_COUNT
        or any(type(value) is not str or not value for value in labels_raw)
        or type(roots_raw) is not list
        or len(roots_raw) != PHYSICAL_MODEL_FEATURE_COUNT
        or any(not _valid_sha256(value) for value in roots_raw)
    ):
        _fail("PROFILED_TRAINING_PARENT_SOURCE_VECTOR_INVALID")
    parent_receipts = _receipt_index(typed_envelope)
    transform_by_feature = {
        transform.feature_name: family.physical_timeframe
        for family in (
            ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.timeframe_finality_transform_contracts
        )
        for transform in family.transforms
    }
    transform_roots: dict[str, str] = {}
    for name, value, label, root_sha in zip(
        PHYSICAL_ORDERED_FEATURE_NAMES,
        values,
        cast(list[str], labels_raw),
        cast(list[str], roots_raw),
        strict=True,
    ):
        timeframe = transform_by_feature.get(name)
        root = parent_receipts.get(root_sha)
        expected_payload = struct.pack(">f", value)
        if timeframe not in {"5m", "1h"} or root is None:
            _fail("PROFILED_TRAINING_PARENT_FEATURE_RECEIPT_MISSING")
        _validate_causal_immutable_receipt(
            root,
            decision_time=decision,
            reason="PROFILED_TRAINING_PARENT_FEATURE_RECEIPT_NOT_CAUSAL_IMMUTABLE",
        )
        children = root.get("child_read_bindings")
        if (
            root.get("receipt_kind") != "COMPOSITE_DERIVATION"
            or root.get("source_label") != label
            or root.get("payload_type") != "IEEE754_BINARY32_MODEL_SCALAR"
            or root.get("payload_sha256") != hashlib.sha256(expected_payload).hexdigest()
            or root.get("read_evidence", {}).get("payload_byte_count") != 4
            or type(children) is not list
            or len(children) != 1
            or children[0].get("input_role") != f"authenticated_transform_{timeframe}"
            or not _valid_sha256(children[0].get("receipt_sha256"))
        ):
            _fail("PROFILED_TRAINING_PARENT_FEATURE_SCALAR_BINDING_INVALID")
        transform_sha = cast(str, children[0]["receipt_sha256"])
        prior = transform_roots.setdefault(timeframe, transform_sha)
        if prior != transform_sha:
            _fail("PROFILED_TRAINING_PARENT_TRANSFORM_ROOT_DRIFT")
    if set(transform_roots) != {"5m", "1h"}:
        _fail("PROFILED_TRAINING_PARENT_EXACT_5M_1H_TRANSFORMS_REQUIRED")
    for timeframe, transform_sha in transform_roots.items():
        transform_receipt = parent_receipts.get(transform_sha)
        if transform_receipt is None:
            _fail("PROFILED_TRAINING_PARENT_TRANSFORM_RECEIPT_MISSING")
        _validate_causal_immutable_receipt(
            transform_receipt,
            decision_time=decision,
            reason="PROFILED_TRAINING_PARENT_TRANSFORM_RECEIPT_NOT_CAUSAL_IMMUTABLE",
        )
        children = transform_receipt.get("child_read_bindings")
        if (
            transform_receipt.get("receipt_kind") != "COMPOSITE_DERIVATION"
            or transform_receipt.get("payload_type")
            != "AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_ARTIFACT"
            or transform_receipt.get("payload_sha256") != core.get("transform_artifact_sha256")
            or type(children) is not list
            or len(children) != 1
            or children[0].get("input_role") != f"canonical_closed_{timeframe}_capture"
            or not _valid_sha256(children[0].get("receipt_sha256"))
        ):
            _fail("PROFILED_TRAINING_PARENT_TRANSFORM_ARTIFACT_BINDING_INVALID")
        capture_receipt = parent_receipts.get(cast(str, children[0]["receipt_sha256"]))
        if capture_receipt is None:
            _fail("PROFILED_TRAINING_PARENT_CAPTURE_RECEIPT_MISSING")
        _validate_causal_immutable_receipt(
            capture_receipt,
            decision_time=decision,
            reason="PROFILED_TRAINING_PARENT_CAPTURE_RECEIPT_NOT_CAUSAL_IMMUTABLE",
        )
        if (
            capture_receipt.get("receipt_kind") != "DIRECT_READ"
            or capture_receipt.get("payload_type") != "CANONICAL_OHLCV_TIMEFRAME_CAPTURE_V1"
            or capture_receipt.get("finality_evidence", {}).get("finality_type")
            != "CLOSED_INTERVAL"
            or _clock(
                capture_receipt.get("feature_cutoff"),
                reason="PROFILED_TRAINING_PARENT_CAPTURE_CUTOFF_INVALID",
            )
            >= decision
        ):
            _fail("PROFILED_TRAINING_PARENT_CAPTURE_FINALITY_INVALID")
    logical, model_vector = _logical_projection(
        physical_model_values=values,
        source_labels=cast(list[str], labels_raw),
        receipt_roots=cast(list[str], roots_raw),
    )
    logical_binding = core.get("logical_projection_binding")
    if type(logical_binding) is not dict or any(
        logical_binding.get(key) != expected
        for key, expected in {
            "schema_version": PROFILED_MODEL_LOGICAL_PROJECTION_V1_SCHEMA_VERSION,
            "base_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
            "base_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
            "logical_slot_count": LOGICAL_MODEL_FEATURE_COUNT,
            "logical_model_input_count": LOGICAL_MODEL_INPUT_COUNT,
            "profile_selection_mask": list(LOGICAL_PROFILE_SELECTION_MASK),
            "profile_selection_mask_sha256": LOGICAL_PROFILE_SELECTION_MASK_SHA256,
            "enabled_slot_ordinals": list(LOGICAL_ENABLED_SLOT_ORDINALS),
            "enabled_slot_ordinals_sha256": LOGICAL_ENABLED_SLOT_ORDINALS_SHA256,
            "model_vector_sha256": logical["model_vector_sha256"],
            "logical_projection_sha256": logical["logical_projection_sha256"],
        }.items()
    ):
        _fail("PROFILED_TRAINING_PARENT_LOGICAL_BINDING_INVALID")
    binding = {
        "schema_version": PROFILED_MODEL_RECORD_LINEAGE_BINDING_V1_SCHEMA_VERSION,
        "durable_snapshot_id": record["durable_snapshot_id"],
        "record_sha256": record["record_sha256"],
        "frozen_envelope_sha256": record["frozen_envelope_sha256"],
        "source_lineage_sha256": typed_envelope["source_lineage_sha256"],
        "physical_model_vector_sha256": typed_envelope["model_vector_sha256"],
        "feature_snapshot_id": typed_envelope["feature_snapshot_id"],
        "profile_id": core["profile_id"],
        "profile_sha256": core["profile_sha256"],
        "capture_set_sha256": core["capture_set_sha256"],
        "transform_artifact_sha256": core["transform_artifact_sha256"],
        "source_provenance_binding_sha256": source_binding_sha,
        "logical_profile_selection_mask_sha256": LOGICAL_PROFILE_SELECTION_MASK_SHA256,
        "logical_enabled_slot_ordinals": list(LOGICAL_ENABLED_SLOT_ORDINALS),
        "logical_enabled_slot_ordinals_sha256": LOGICAL_ENABLED_SLOT_ORDINALS_SHA256,
        "logical_model_vector_sha256": logical["model_vector_sha256"],
        "logical_projection_sha256": logical["logical_projection_sha256"],
        "feature_cutoff": typed_envelope["feature_cutoff"],
        "decision_time": typed_envelope["tensor_decision_time"],
        "generated_at": typed_envelope["generated_at"],
        "authorization": _PARENT_FALSE_AUTHORIZATION,
    }
    return {
        "record": record,
        "envelope": typed_envelope,
        "core_lineage": core,
        "binding": binding,
        "values": values,
        "source_labels": tuple(cast(list[str], labels_raw)),
        "receipt_roots": tuple(cast(list[str], roots_raw)),
        "logical": logical,
        "model_vector": model_vector,
    }


def _receipt_index(envelope: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = envelope.get("source_read_receipts")
    if type(raw) is not list:
        _fail("PROFILED_TRAINING_SOURCE_RECEIPTS_INVALID")
    output: dict[str, dict[str, Any]] = {}
    for value in cast(list[object], raw):
        if type(value) is not dict or not _valid_sha256(value.get("receipt_sha256")):
            _fail("PROFILED_TRAINING_SOURCE_RECEIPT_INVALID")
        receipt = cast(dict[str, Any], value)
        digest = cast(str, receipt["receipt_sha256"])
        if digest in output:
            _fail("PROFILED_TRAINING_SOURCE_RECEIPT_DUPLICATE")
        output[digest] = receipt
    return output


def _validate_causal_immutable_receipt(
    receipt: Mapping[str, Any],
    *,
    decision_time: datetime,
    reason: str,
) -> None:
    read = receipt.get("read_evidence")
    finality = receipt.get("finality_evidence")
    if (
        type(read) is not dict
        or type(finality) is not dict
        or read.get("read_locator_type") not in _IMMUTABLE_COST_LOCATORS
        or type(read.get("payload_byte_count")) is not int
        or read.get("payload_byte_count") <= 0
        or finality.get("event_final") is not True
    ):
        _fail(reason)
    clocks = (
        receipt.get("event_time"),
        receipt.get("available_at"),
        receipt.get("consumer_observed_at"),
        receipt.get("feature_cutoff"),
        finality.get("finality_cutoff"),
        finality.get("finality_verified_at"),
    )
    if any(_clock(value, reason=reason) > decision_time for value in clocks):
        _fail(reason)


def _validate_cost_binding(
    value: object,
    *,
    envelope: Mapping[str, Any],
    physical_values: Sequence[float],
    decision_time: datetime,
) -> dict[str, Any]:
    binding = _exact_dict(
        value,
        _COST_BINDING_FIELDS,
        reason="PROFILED_TRAINING_COST_BINDING_FIELDS_INVALID",
    )
    auxiliary_values = tuple(physical_values[PHYSICAL_MODEL_FEATURE_COUNT:])
    auxiliary_roots = envelope.get("feature_source_receipt_sha256s", [])[
        PHYSICAL_MODEL_FEATURE_COUNT:
    ]
    auxiliary_labels = envelope.get("ordered_feature_source_labels", [])[
        PHYSICAL_MODEL_FEATURE_COUNT:
    ]
    binding_available = _clock(
        binding.get("available_at"),
        reason="PROFILED_TRAINING_COST_AVAILABLE_AT_INVALID",
    )
    binding_cutoff = _clock(
        binding.get("feature_cutoff"),
        reason="PROFILED_TRAINING_COST_FEATURE_CUTOFF_INVALID",
    )
    if (
        binding.get("schema_version") != PROFILED_TRAINING_COST_BINDING_V1_SCHEMA_VERSION
        or type(binding.get("cost_capture_schema_version")) is not str
        or binding.get("cost_capture_schema_version") != CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION
        or binding.get("cost_capture_implementation_id")
        != CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID
        or binding.get("cost_capture_implementation_sha256")
        != CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256
        or binding.get("symbol") != envelope.get("symbol")
        or binding.get("decision_time") != envelope.get("tensor_decision_time")
        or binding.get("expected_holding_horizon_seconds")
        != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        or binding_available > decision_time
        or binding_cutoff > decision_time
        or binding.get("auxiliary_feature_names") != list(AUXILIARY_LABEL_ONLY_FEATURE_NAMES)
        or binding.get("auxiliary_source_labels") != auxiliary_labels
        or binding.get("auxiliary_feature_receipt_sha256s") != auxiliary_roots
        or binding.get("auxiliary_values_float32_sha256")
        != _auxiliary_values_sha256(auxiliary_values)
        or any(value < 0.0 for value in auxiliary_values[:3])
        or any(
            not _valid_sha256(binding.get(name))
            for name in (
                "cost_capture_artifact_sha256",
                "cost_capture_receipt_sha256",
                "authoritative_fee_schedule_sha256",
                "expected_notional_policy_sha256",
                "fee_schedule_receipt_sha256",
                "notional_policy_receipt_sha256",
                "orderbook_depth_receipt_sha256",
                "orderbook_features_receipt_sha256",
                "mark_price_receipt_sha256",
            )
        )
        or type(binding.get("cost_capture_artifact_byte_count")) is not int
        or binding.get("cost_capture_artifact_byte_count") <= 0
    ):
        _fail("PROFILED_TRAINING_COST_BINDING_INVALID")
    receipts = _receipt_index(envelope)
    child_claims = {
        "authoritative_fee_schedule": binding["fee_schedule_receipt_sha256"],
        "expected_notional_policy": binding["notional_policy_receipt_sha256"],
        "mark_price": binding["mark_price_receipt_sha256"],
        "orderbook_depth": binding["orderbook_depth_receipt_sha256"],
        "orderbook_features": binding["orderbook_features_receipt_sha256"],
    }
    if len(set(child_claims.values())) != len(PROFILED_TRAINING_COST_CAPTURE_RECEIPT_CHILD_ROLES):
        _fail("PROFILED_TRAINING_COST_CAPTURE_RECEIPT_BINDING_INVALID")
    cost_receipt = receipts.get(cast(str, binding["cost_capture_receipt_sha256"]))
    if cost_receipt is None:
        _fail("PROFILED_TRAINING_COST_CAPTURE_RECEIPT_MISSING")
    _validate_causal_immutable_receipt(
        cost_receipt,
        decision_time=decision_time,
        reason="PROFILED_TRAINING_COST_CAPTURE_RECEIPT_NOT_CAUSAL_IMMUTABLE",
    )
    expected_children = [
        {"input_role": role, "receipt_sha256": child_claims[role]}
        for role in PROFILED_TRAINING_COST_CAPTURE_RECEIPT_CHILD_ROLES
    ]
    if (
        cost_receipt.get("receipt_kind") != "COMPOSITE_DERIVATION"
        or cost_receipt.get("payload_sha256") != binding.get("cost_capture_artifact_sha256")
        or cost_receipt.get("read_evidence", {}).get("payload_byte_count")
        != binding.get("cost_capture_artifact_byte_count")
        or cost_receipt.get("child_read_bindings") != expected_children
    ):
        _fail("PROFILED_TRAINING_COST_CAPTURE_RECEIPT_BINDING_INVALID")
    for role, receipt_sha in child_claims.items():
        source = receipts.get(cast(str, receipt_sha))
        if source is None:
            _fail(f"PROFILED_TRAINING_COST_SOURCE_RECEIPT_MISSING:{role}")
        _validate_causal_immutable_receipt(
            source,
            decision_time=decision_time,
            reason=f"PROFILED_TRAINING_COST_SOURCE_NOT_CAUSAL_IMMUTABLE:{role}",
        )
        if source.get("receipt_kind") != "DIRECT_READ":
            _fail(f"PROFILED_TRAINING_COST_SOURCE_RECEIPT_KIND_INVALID:{role}")
    if (
        receipts[cast(str, binding["fee_schedule_receipt_sha256"])].get("payload_sha256")
        != binding["authoritative_fee_schedule_sha256"]
        or receipts[cast(str, binding["notional_policy_receipt_sha256"])].get("payload_sha256")
        != binding["expected_notional_policy_sha256"]
    ):
        _fail("PROFILED_TRAINING_FEE_OR_NOTIONAL_POLICY_PAYLOAD_BINDING_INVALID")
    auxiliary_available_times: list[datetime] = []
    for name, root_sha in zip(
        AUXILIARY_LABEL_ONLY_FEATURE_NAMES,
        auxiliary_roots,
        strict=True,
    ):
        root = receipts.get(cast(str, root_sha))
        if root is None:
            _fail(f"PROFILED_TRAINING_AUXILIARY_RECEIPT_MISSING:{name}")
        _validate_causal_immutable_receipt(
            root,
            decision_time=decision_time,
            reason=f"PROFILED_TRAINING_AUXILIARY_NOT_CAUSAL_IMMUTABLE:{name}",
        )
        if (
            root.get("receipt_kind") != "COMPOSITE_DERIVATION"
            or root.get("source_label")
            != auxiliary_labels[AUXILIARY_LABEL_ONLY_FEATURE_NAMES.index(name)]
            or root.get("payload_sha256")
            != hashlib.sha256(
                struct.pack(
                    ">f",
                    auxiliary_values[AUXILIARY_LABEL_ONLY_FEATURE_NAMES.index(name)],
                )
            ).hexdigest()
            or root.get("read_evidence", {}).get("payload_byte_count") != 4
            or root.get("child_read_bindings")
            != [
                {
                    "input_role": "causal_cost_capture_artifact",
                    "receipt_sha256": binding["cost_capture_receipt_sha256"],
                }
            ]
        ):
            _fail(f"PROFILED_TRAINING_AUXILIARY_CAPTURE_EDGE_INVALID:{name}")
        if root.get("feature_cutoff") != binding.get("feature_cutoff"):
            _fail(f"PROFILED_TRAINING_AUXILIARY_CUTOFF_BINDING_INVALID:{name}")
        auxiliary_available_times.append(
            _clock(
                root.get("available_at"),
                reason=f"PROFILED_TRAINING_AUXILIARY_AVAILABLE_AT_INVALID:{name}",
            )
        )
    if not auxiliary_available_times or binding_available != max(auxiliary_available_times):
        _fail("PROFILED_TRAINING_COST_AVAILABLE_AT_BINDING_INVALID")
    return binding


@dataclass(frozen=True, slots=True)
class ProfiledTrainingLedgerSampleV1:
    """One factory-authenticated, still-unwired optimizer candidate."""

    sequence: int
    durable_snapshot_id: str
    record_sha256: str
    frozen_envelope_sha256: str
    symbol: str
    timeframe: str
    feature_snapshot_id: str
    decision_time: str
    feature_cutoff: str
    generated_at: str
    parent_durable_snapshot_id: str
    parent_record_sha256: str
    parent_lineage_binding_sha256: str
    physical_feature_values: tuple[float, ...]
    auxiliary_label_values: tuple[float, ...]
    logical_feature_names: tuple[str, ...]
    logical_feature_values: tuple[float, ...]
    logical_missing_mask: tuple[int, ...]
    logical_stale_mask: tuple[int, ...]
    logical_source_availability_mask: tuple[int, ...]
    logical_profile_selection_mask: tuple[int, ...]
    logical_profile_selection_mask_sha256: str
    logical_enabled_slot_ordinals: tuple[int, ...]
    logical_enabled_slot_ordinals_sha256: str
    logical_model_vector: tuple[float, ...]
    logical_model_vector_sha256: str
    logical_projection_sha256: str
    append_transaction_id: str
    append_receipt_sha256: str
    postcommit_receipt_sha256: str
    postcommit_readback_at: str
    ledger_high_water_sha256: str
    trainer_admission_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    runtime_wired: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _RESULT_TOKEN
            or len(self.physical_feature_values) != PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT
            or len(self.logical_feature_values) != LOGICAL_MODEL_FEATURE_COUNT
            or len(self.logical_model_vector) != LOGICAL_MODEL_INPUT_COUNT
            or self.trainer_admission_authorized is not True
            or any(
                value is not False
                for value in (
                    self.prediction_authorized,
                    self.paper_trading_authorized,
                    self.live_execution_authorized,
                    self.runtime_wired,
                )
            )
        ):
            _fail("PROFILED_TRAINING_SAMPLE_RESULT_INVARIANT_INVALID")


@dataclass(frozen=True, slots=True)
class ProfiledTrainingLedgerExclusionV1:
    sequence: int
    durable_snapshot_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class ProfiledTrainingLedgerBatchV1:
    schema_version: str
    training_observed_at: str
    strict_prior_observation: str
    high_water_json: str = field(repr=False)
    high_water_sha256: str
    requested_after_sequence: int
    requested_cursor_sha256: str | None
    page_scan_limit: int
    scanned_start_sequence: int | None
    scanned_end_sequence: int | None
    scanned_record_count: int
    next_after_sequence: int
    next_cursor: str | None = field(repr=False)
    scan_truncated: bool
    has_remaining_strict_rows: bool
    remaining_semantics: str
    page_integrity_semantics: str
    runtime_scalability_status: str
    samples: tuple[ProfiledTrainingLedgerSampleV1, ...]
    exclusions: tuple[ProfiledTrainingLedgerExclusionV1, ...]
    authenticated_prefix_head_sequence: int
    authenticated_prefix_record_count: int
    archive_chain_sha256: str
    append_postcommit_high_water_verified: bool
    runtime_wired: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _BATCH_TOKEN
            or self.schema_version != PROFILED_TRAINING_LEDGER_LOADER_V1_SCHEMA_VERSION
            or self.append_postcommit_high_water_verified is not True
            or self.runtime_wired is not False
            or type(self.requested_after_sequence) is not int
            or self.requested_after_sequence < 0
            or (
                self.requested_cursor_sha256 is not None
                and not _valid_sha256(self.requested_cursor_sha256)
            )
            or ((self.requested_after_sequence == 0) != (self.requested_cursor_sha256 is None))
            or type(self.page_scan_limit) is not int
            or not 0 < self.page_scan_limit <= MAX_PROFILED_TRAINING_SCAN_ROWS
            or type(self.scanned_record_count) is not int
            or self.scanned_record_count != len(self.samples) + len(self.exclusions)
            or not 0 <= self.scanned_record_count <= self.page_scan_limit
            or type(self.next_after_sequence) is not int
            or type(self.scan_truncated) is not bool
            or type(self.has_remaining_strict_rows) is not bool
            or self.scan_truncated is not self.has_remaining_strict_rows
            or self.remaining_semantics
            != (_REMAINING_PRESENT if self.has_remaining_strict_rows else _REMAINING_ABSENT)
            or self.page_integrity_semantics != PROFILED_TRAINING_PAGE_INTEGRITY_SEMANTICS
            or self.runtime_scalability_status != PROFILED_TRAINING_RUNTIME_SCALABILITY_STATUS
        ):
            _fail("PROFILED_TRAINING_BATCH_RESULT_INVARIANT_INVALID")
        if self.scanned_record_count == 0:
            if (
                self.scanned_start_sequence is not None
                or self.scanned_end_sequence is not None
                or self.next_after_sequence != self.requested_after_sequence
                or self.next_cursor is not None
                or self.has_remaining_strict_rows is not False
            ):
                _fail("PROFILED_TRAINING_EMPTY_PAGE_RESULT_INVARIANT_INVALID")
        elif (
            type(self.scanned_start_sequence) is not int
            or self.scanned_start_sequence <= self.requested_after_sequence
            or type(self.scanned_end_sequence) is not int
            or self.scanned_end_sequence < self.scanned_start_sequence
            or self.next_after_sequence != self.scanned_end_sequence
            or (self.has_remaining_strict_rows and type(self.next_cursor) is not str)
            or (not self.has_remaining_strict_rows and self.next_cursor is not None)
        ):
            _fail("PROFILED_TRAINING_PAGE_RESULT_INVARIANT_INVALID")
        try:
            high_water = json.loads(self.high_water_json)
        except (json.JSONDecodeError, TypeError, ValueError):
            _fail("PROFILED_TRAINING_BATCH_HIGH_WATER_JSON_INVALID")
        if (
            type(high_water) is not dict
            or high_water.get("high_water_sha256") != self.high_water_sha256
        ):
            _fail("PROFILED_TRAINING_BATCH_HIGH_WATER_BINDING_INVALID")
        if self.next_cursor is not None:
            cursor = _parse_page_cursor(self.next_cursor)
            if (
                cursor["training_observed_at"] != self.training_observed_at
                or cursor["high_water_sha256"] != self.high_water_sha256
                or cursor["requested_after_sequence"] != self.requested_after_sequence
                or cursor["scanned_start_sequence"] != self.scanned_start_sequence
                or cursor["scanned_end_sequence"] != self.scanned_end_sequence
                or cursor["scanned_record_count"] != self.scanned_record_count
                or cursor["scan_limit"] != self.page_scan_limit
                or cursor["next_after_sequence"] != self.next_after_sequence
            ):
                _fail("PROFILED_TRAINING_BATCH_NEXT_CURSOR_BINDING_INVALID")

    @property
    def high_water(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.high_water_json))


def _profile_attestation(envelope: Mapping[str, Any]) -> dict[str, Any] | None:
    core = _core_lineage(envelope)
    value = core.get(PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY)
    if value is None:
        return None
    if set(core) != {PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY}:
        _fail("PROFILED_TRAINING_ENRICHMENT_LINEAGE_SMUGGLED_FIELDS")
    return _exact_dict(
        value,
        _TRAINING_LINEAGE_FIELDS,
        reason="PROFILED_TRAINING_ENRICHMENT_LINEAGE_FIELDS_INVALID",
    )


def _admit_item(
    *,
    ledger: DurableFeatureSnapshotLedger,
    item: FixedCutoffFeatureSnapshot,
    high_water: Mapping[str, Any],
) -> ProfiledTrainingLedgerSampleV1 | None:
    record = item.record
    if type(record) is not dict or type(record.get("frozen_envelope")) is not dict:
        _fail("PROFILED_TRAINING_LEDGER_ITEM_INVALID")
    envelope = cast(dict[str, Any], record["frozen_envelope"])
    attestation = _profile_attestation(envelope)
    if attestation is None:
        return None
    if (
        envelope.get("provenance_classification") != PROVENANCE_CANONICAL_V3
        or envelope.get("legacy_v1_snapshot_id") is not None
        or envelope.get("strict_training_eligible") is not True
        or envelope.get("strict_training_ineligibility_reasons") != []
        or envelope.get("temporal_rejection_reasons") != []
        or envelope.get("ordered_feature_names")
        != list(PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES)
        or envelope.get("missing_mask") != [0] * PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT
        or envelope.get("stale_mask") != [0] * PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT
        or envelope.get("source_availability_mask")
        != [1] * PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT
    ):
        _fail("PROFILED_TRAINING_ENRICHED_RECORD_CONTRACT_INVALID")
    if (
        attestation.get("schema_version") != PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_SCHEMA_VERSION
        or attestation.get("classification")
        != PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_CLASSIFICATION
        or attestation.get("status") != PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_STATUS
        or attestation.get("profile_id") != ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID
        or attestation.get("profile_sha256") != ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256
        or attestation.get("base_registry_sha256") != FEATURE_SOURCE_REGISTRY_V4_SHA256
        or attestation.get("base_abi_sha256") != FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256
        or attestation.get("logical_profile_selection_mask_sha256")
        != LOGICAL_PROFILE_SELECTION_MASK_SHA256
        or attestation.get("logical_enabled_slot_ordinals_sha256")
        != LOGICAL_ENABLED_SLOT_ORDINALS_SHA256
        or attestation.get("transform_implementation_id")
        != AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_ID
        or attestation.get("transform_implementation_sha256")
        != AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256
        or attestation.get("transform_configuration_sha256")
        != AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
        or attestation.get("projection_schema_version")
        != PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION
        or attestation.get("projection_implementation_sha256")
        != PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256
        or attestation.get("projection_configuration_sha256")
        != PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256
        or attestation.get("physical_feature_count") != PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT
        or attestation.get("physical_ordered_feature_names_sha256")
        != PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES_SHA256
        or _exact_dict(
            attestation.get("authorization"),
            _AUTHORIZATION_FIELDS,
            reason="PROFILED_TRAINING_AUTHORIZATION_FIELDS_INVALID",
        )
        != _EXPECTED_AUTHORIZATION
    ):
        _fail("PROFILED_TRAINING_ENRICHMENT_ATTESTATION_INVALID")
    parent_claim = _exact_dict(
        attestation.get("parent_model_record_binding"),
        _PARENT_BINDING_FIELDS,
        reason="PROFILED_TRAINING_PARENT_BINDING_FIELDS_INVALID",
    )
    parent_id = parent_claim.get("durable_snapshot_id")
    if type(parent_id) is not str:
        _fail("PROFILED_TRAINING_PARENT_ID_INVALID")
    parent = ledger.get_snapshot(parent_id)
    if parent is None:
        _fail("PROFILED_TRAINING_PARENT_LEDGER_RECORD_MISSING")
    parent_material = _validate_parent_model_record(parent)
    if parent_claim != parent_material["binding"]:
        _fail("PROFILED_TRAINING_PARENT_BINDING_MISMATCH")
    parent_envelope = cast(dict[str, Any], parent_material["envelope"])
    if (
        parent.sequence >= item.sequence
        or parent.append_transaction_id != item.append_transaction_id
        or parent.append_receipt_sha256 != item.append_receipt_sha256
        or parent.postcommit_receipt_sha256 != item.postcommit_receipt_sha256
        or parent.postcommit_readback_at != item.postcommit_readback_at
        or any(
            envelope.get(field) != parent_envelope.get(field)
            for field in (
                "symbol",
                "timeframe",
                "tensor_decision_time",
                "feature_cutoff",
                "masa_feature_cutoff",
                "ppo_feature_cutoff",
                "ppo_decision_time",
            )
        )
    ):
        _fail("PROFILED_TRAINING_PARENT_ATOMIC_APPEND_OR_CLOCK_BINDING_INVALID")
    physical_values = _float32_vector(
        envelope.get("feature_values"),
        expected=PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT,
        reason="PROFILED_TRAINING_PHYSICAL_VALUES_INVALID",
    )
    labels = envelope.get("ordered_feature_source_labels")
    roots = envelope.get("feature_source_receipt_sha256s")
    if (
        type(labels) is not list
        or type(roots) is not list
        or len(labels) != PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT
        or len(roots) != PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT
        or any(type(value) is not str or not value for value in labels)
        or any(not _valid_sha256(value) for value in roots)
        or physical_values[:PHYSICAL_MODEL_FEATURE_COUNT] != parent_material["values"]
        or tuple(labels[:PHYSICAL_MODEL_FEATURE_COUNT]) != parent_material["source_labels"]
        or tuple(roots[:PHYSICAL_MODEL_FEATURE_COUNT]) != parent_material["receipt_roots"]
    ):
        _fail("PROFILED_TRAINING_PARENT_MODEL_BIT_IDENTITY_INVALID")
    child_receipts = _receipt_index(envelope)
    parent_receipts = _receipt_index(parent_envelope)
    if any(
        child_receipts.get(root) != parent_receipts.get(root)
        for root in parent_material["receipt_roots"]
    ):
        _fail("PROFILED_TRAINING_PARENT_RECEIPT_GRAPH_NOT_SELF_CONTAINED")
    decision = _clock(
        envelope.get("tensor_decision_time"),
        reason="PROFILED_TRAINING_DECISION_TIME_INVALID",
    )
    _validate_cost_binding(
        attestation.get("cost_capture_binding"),
        envelope=envelope,
        physical_values=physical_values,
        decision_time=decision,
    )
    logical, model_vector = _logical_projection(
        physical_model_values=physical_values[:PHYSICAL_MODEL_FEATURE_COUNT],
        source_labels=cast(list[str], labels[:PHYSICAL_MODEL_FEATURE_COUNT]),
        receipt_roots=cast(list[str], roots[:PHYSICAL_MODEL_FEATURE_COUNT]),
    )
    if (
        logical["model_vector_sha256"] != parent_material["logical"]["model_vector_sha256"]
        or logical["logical_projection_sha256"]
        != parent_material["logical"]["logical_projection_sha256"]
    ):
        _fail("PROFILED_TRAINING_LOGICAL_PROJECTION_PARENT_MISMATCH")
    high_water_sha = high_water.get("high_water_sha256")
    if (
        not _valid_sha256(high_water_sha)
        or type(high_water.get("verified_records")) is not int
        or item.sequence > high_water["verified_records"]
        or parent.sequence > high_water["verified_records"]
    ):
        _fail("PROFILED_TRAINING_LEDGER_HEAD_PROOF_INVALID")
    parent_binding_sha = stable_sha256(parent_material["binding"])
    return ProfiledTrainingLedgerSampleV1(
        sequence=item.sequence,
        durable_snapshot_id=cast(str, record["durable_snapshot_id"]),
        record_sha256=cast(str, record["record_sha256"]),
        frozen_envelope_sha256=cast(str, record["frozen_envelope_sha256"]),
        symbol=cast(str, envelope["symbol"]),
        timeframe=cast(str, envelope["timeframe"]),
        feature_snapshot_id=cast(str, envelope["feature_snapshot_id"]),
        decision_time=cast(str, envelope["tensor_decision_time"]),
        feature_cutoff=cast(str, envelope["feature_cutoff"]),
        generated_at=cast(str, envelope["generated_at"]),
        parent_durable_snapshot_id=cast(str, parent_id),
        parent_record_sha256=cast(str, parent_material["record"]["record_sha256"]),
        parent_lineage_binding_sha256=parent_binding_sha,
        physical_feature_values=physical_values,
        auxiliary_label_values=physical_values[PHYSICAL_MODEL_FEATURE_COUNT:],
        logical_feature_names=tuple(LOGICAL_ORDERED_FEATURE_NAMES),
        logical_feature_values=tuple(logical["feature_values"]),
        logical_missing_mask=tuple(logical["missing_mask"]),
        logical_stale_mask=tuple(logical["stale_mask"]),
        logical_source_availability_mask=tuple(logical["source_availability_mask"]),
        logical_profile_selection_mask=LOGICAL_PROFILE_SELECTION_MASK,
        logical_profile_selection_mask_sha256=LOGICAL_PROFILE_SELECTION_MASK_SHA256,
        logical_enabled_slot_ordinals=LOGICAL_ENABLED_SLOT_ORDINALS,
        logical_enabled_slot_ordinals_sha256=LOGICAL_ENABLED_SLOT_ORDINALS_SHA256,
        logical_model_vector=model_vector,
        logical_model_vector_sha256=cast(str, logical["model_vector_sha256"]),
        logical_projection_sha256=cast(str, logical["logical_projection_sha256"]),
        append_transaction_id=item.append_transaction_id,
        append_receipt_sha256=item.append_receipt_sha256,
        postcommit_receipt_sha256=item.postcommit_receipt_sha256,
        postcommit_readback_at=item.postcommit_readback_at,
        ledger_high_water_sha256=cast(str, high_water_sha),
        trainer_admission_authorized=True,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        runtime_wired=False,
        _construction_token=_RESULT_TOKEN,
    )


def load_profiled_training_ledger_v1(
    *,
    ledger: DurableFeatureSnapshotLedger,
    training_observed_at: str,
    scan_limit: int = MAX_PROFILED_TRAINING_SCAN_ROWS,
    after_sequence: int = 0,
    page_cursor: str | None = None,
) -> ProfiledTrainingLedgerBatchV1:
    """Load one immutable, fixed-observation profiled training inventory."""

    if type(ledger) is not DurableFeatureSnapshotLedger:
        _fail("PROFILED_TRAINING_LEDGER_EXACT_TYPE_REQUIRED")
    if type(scan_limit) is not int or not 0 < scan_limit <= MAX_PROFILED_TRAINING_SCAN_ROWS:
        _fail("PROFILED_TRAINING_SCAN_LIMIT_INVALID")
    if type(after_sequence) is not int or after_sequence < 0:
        _fail("PROFILED_TRAINING_AFTER_SEQUENCE_INVALID")
    if (after_sequence == 0 and page_cursor is not None) or (
        after_sequence > 0 and type(page_cursor) is not str
    ):
        _fail("PROFILED_TRAINING_PAGE_CURSOR_REQUIREMENT_INVALID")
    observed = _clock(
        training_observed_at,
        reason="PROFILED_TRAINING_OBSERVED_AT_INVALID",
    )
    observed_text = _canonical_clock(observed)
    try:
        strict_prior = observed - timedelta(microseconds=1)
    except OverflowError:
        _fail("PROFILED_TRAINING_OBSERVED_AT_INVALID")
    try:
        before_report = ledger.verify_integrity_streaming()
        before_high_water_scan_limit = max(
            before_report.verified_records,
            before_report.verified_append_receipts,
            1,
        )
        before_high_water = feature_ledger_fixed_observation_high_water(
            ledger=ledger,
            report=before_report,
            observation_cutoff=observed,
            scan_limit=before_high_water_scan_limit,
        )
        if (
            before_report.integrity_verified is not True
            or before_high_water.get("schema_version") != FEATURE_HIGH_WATER_SCHEMA_VERSION
            or before_high_water.get("postcommit_readback_verified") is not True
            or before_high_water.get("receipt_backed") is not True
            or before_high_water.get("fixed_observation_prefix_only") is not True
            or type(before_high_water.get("verified_records")) is not int
            or before_high_water["verified_records"] < 0
        ):
            _fail("PROFILED_TRAINING_HIGH_WATER_INVALID")
        prefix_records = cast(int, before_high_water["verified_records"])
        high_water_sha256 = before_high_water.get("high_water_sha256")
        if not _valid_sha256(high_water_sha256) or after_sequence > prefix_records:
            _fail("PROFILED_TRAINING_PAGE_START_OUTSIDE_HIGH_WATER")
        requested_cursor_sha256: str | None = None
        if page_cursor is not None:
            parsed_cursor = _parse_page_cursor(page_cursor)
            if (
                parsed_cursor["training_observed_at"] != observed_text
                or parsed_cursor["high_water_sha256"] != high_water_sha256
                or parsed_cursor["next_after_sequence"] != after_sequence
            ):
                _fail("PROFILED_TRAINING_PAGE_CURSOR_CONTEXT_MISMATCH")
            requested_cursor_sha256 = cast(str, parsed_cursor["cursor_sha256"])
        strict_prior_text = _canonical_clock(strict_prior)
        items: list[FixedCutoffFeatureSnapshot] = []
        query_after_sequence = after_sequence
        page_fetch_limit = scan_limit + 1
        while len(items) < page_fetch_limit:
            page = ledger.query_fixed_cutoff(
                decision_time_cutoff=strict_prior_text,
                training_observed_at=strict_prior_text,
                limit=min(MAX_QUERY_ROWS, page_fetch_limit - len(items)),
                after_sequence=query_after_sequence,
            )
            if not page:
                break
            if any(item.sequence > prefix_records for item in page):
                _fail("PROFILED_TRAINING_PAGE_EXCEEDED_FIXED_HIGH_WATER")
            items.extend(page)
            query_after_sequence = page[-1].sequence
        has_remaining = len(items) > scan_limit
        scanned_items = items[:scan_limit]
        samples: list[ProfiledTrainingLedgerSampleV1] = []
        exclusions: list[ProfiledTrainingLedgerExclusionV1] = []
        for item in scanned_items:
            admitted = _admit_item(
                ledger=ledger,
                item=item,
                high_water=before_high_water,
            )
            if admitted is None:
                exclusions.append(
                    ProfiledTrainingLedgerExclusionV1(
                        sequence=item.sequence,
                        durable_snapshot_id=cast(
                            str,
                            item.record.get("durable_snapshot_id", ""),
                        ),
                        reason="NOT_AUTHENTICATED_PROFILED_TRAINING_ENRICHMENT",
                    )
                )
            else:
                samples.append(admitted)
        after_report = ledger.verify_integrity_streaming()
        after_high_water_scan_limit = max(
            after_report.verified_records,
            after_report.verified_append_receipts,
            1,
        )
        after_high_water = feature_ledger_fixed_observation_high_water(
            ledger=ledger,
            report=after_report,
            observation_cutoff=observed,
            scan_limit=after_high_water_scan_limit,
        )
    except ProfiledTrainingLedgerLoaderV1Error:
        raise
    except (FeatureSnapshotLedgerError, TrainingSampleIdentityError, OSError, ValueError) as exc:
        raise ProfiledTrainingLedgerLoaderV1Error(
            f"PROFILED_TRAINING_LEDGER_READ_FAILED:{type(exc).__name__}"
        ) from exc
    if before_high_water != after_high_water:
        _fail("PROFILED_TRAINING_AUTHENTICATED_HIGH_WATER_MOVED_DURING_LOAD")
    high_water_json = _canonical_json(before_high_water)
    scanned_record_count = len(scanned_items)
    scanned_start_sequence = scanned_items[0].sequence if scanned_items else None
    scanned_end_sequence = scanned_items[-1].sequence if scanned_items else None
    next_after_sequence = (
        cast(int, scanned_end_sequence) if scanned_end_sequence is not None else after_sequence
    )
    next_cursor = (
        _build_page_cursor(
            training_observed_at=observed_text,
            high_water_sha256=cast(str, before_high_water["high_water_sha256"]),
            requested_after_sequence=after_sequence,
            scanned_start_sequence=cast(int, scanned_start_sequence),
            scanned_end_sequence=cast(int, scanned_end_sequence),
            scanned_record_count=scanned_record_count,
            scan_limit=scan_limit,
        )
        if has_remaining
        else None
    )
    return ProfiledTrainingLedgerBatchV1(
        schema_version=PROFILED_TRAINING_LEDGER_LOADER_V1_SCHEMA_VERSION,
        training_observed_at=observed_text,
        strict_prior_observation=_canonical_clock(strict_prior),
        high_water_json=high_water_json,
        high_water_sha256=cast(str, before_high_water["high_water_sha256"]),
        requested_after_sequence=after_sequence,
        requested_cursor_sha256=requested_cursor_sha256,
        page_scan_limit=scan_limit,
        scanned_start_sequence=scanned_start_sequence,
        scanned_end_sequence=scanned_end_sequence,
        scanned_record_count=scanned_record_count,
        next_after_sequence=next_after_sequence,
        next_cursor=next_cursor,
        scan_truncated=has_remaining,
        has_remaining_strict_rows=has_remaining,
        remaining_semantics=(_REMAINING_PRESENT if has_remaining else _REMAINING_ABSENT),
        page_integrity_semantics=PROFILED_TRAINING_PAGE_INTEGRITY_SEMANTICS,
        runtime_scalability_status=PROFILED_TRAINING_RUNTIME_SCALABILITY_STATUS,
        samples=tuple(samples),
        exclusions=tuple(exclusions),
        authenticated_prefix_head_sequence=cast(
            int,
            before_high_water["authenticated_prefix_head_sequence"],
        ),
        authenticated_prefix_record_count=cast(
            int,
            before_high_water["verified_records"],
        ),
        archive_chain_sha256=cast(str, before_high_water["archive_chain_sha256"]),
        append_postcommit_high_water_verified=True,
        runtime_wired=False,
        _construction_token=_BATCH_TOKEN,
    )


__all__ = [
    "MAX_PROFILED_TRAINING_SCAN_ROWS",
    "PROFILED_TRAINING_COST_BINDING_V1_SCHEMA_VERSION",
    "PROFILED_TRAINING_COST_CAPTURE_RECEIPT_CHILD_ROLES",
    "PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_CLASSIFICATION",
    "PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY",
    "PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_SCHEMA_VERSION",
    "PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_STATUS",
    "PROFILED_TRAINING_LEDGER_LOADER_V1_SCHEMA_VERSION",
    "PROFILED_TRAINING_PAGE_CURSOR_V1_SCHEMA_VERSION",
    "PROFILED_TRAINING_PAGE_INTEGRITY_SEMANTICS",
    "PROFILED_TRAINING_RUNTIME_SCALABILITY_STATUS",
    "PROFILED_TRAINING_PHYSICAL_FEATURE_COUNT",
    "PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES",
    "PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES_SHA256",
    "PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256",
    "PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256",
    "PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION",
    "ProfiledTrainingLedgerBatchV1",
    "ProfiledTrainingLedgerExclusionV1",
    "ProfiledTrainingLedgerLoaderV1Error",
    "ProfiledTrainingLedgerSampleV1",
    "load_profiled_training_ledger_v1",
]
