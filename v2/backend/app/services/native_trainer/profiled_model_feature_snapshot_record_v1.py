"""Authenticated 35-feature model-only ledger-v3 evidence boundary.

This module is deliberately unwired.  It turns the exact output of
``authenticated_ohlcv_profile_transform_v1`` into one physical 35-slot
durable-ledger-v3 record, then exposes the deterministic profile-aware logical
446-slot/1784-value projection.  It never accepts model scalars from a caller.

The boundary requires the two durable source-provenance-v4 entries to exist
before construction.  It freshly reads and verifies that ledger, matches the
5m and true-1h atomic capture slices, independently recomputes the transform,
and pins the capture manifests, transform artifact, and every scalar in an
immutable content-addressed store.  The resulting record has one explicit
unwired quarantine reason and grants no trainer, prediction, paper, live, or
runtime authority.
"""

from __future__ import annotations

import hashlib
import hmac
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
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
    PROFILE_DISABLED,
    adaptive_ohlcv_feature_selection_profile_v1_contract,
)
from v2.backend.app.services.native_trainer.authenticated_ohlcv_profile_transform_v1 import (
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256,
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_ID,
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256,
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_SCHEMA_VERSION,
    AuthenticatedOhlcvProfileTransformV1Error,
    AuthenticatedOhlcvProfileTransformV1Result,
    transform_authenticated_ohlcv_profile_v1,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION,
    PROVENANCE_CANONICAL_V3,
    TEMPORAL_REJECTION_INELIGIBILITY_REASON,
    FeatureSnapshotValidationError,
    build_feature_snapshot_record,
    build_source_read_receipt,
    canonical_json,
    stable_sha256,
    validate_feature_snapshot_record,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.source_provenance_ledger_v4 import (
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_NAMESPACE,
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION,
    TrainerSourceProvenanceLedgerEntryV4,
    TrainerSourceProvenanceLedgerV4,
    TrainerSourceProvenanceLedgerV4Error,
)

PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_SCHEMA_VERSION: Final = (
    "profiled_model_feature_snapshot_record_v1"
)
PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_CLASSIFICATION: Final = (
    "AUTHENTICATED_OHLCV_MODEL_ONLY_LEDGER_V3_UNWIRED"
)
PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_STATUS: Final = (
    "VALIDATED_QUARANTINED_NO_RUNTIME_AUTHORITY"
)
PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON: Final = (
    "PROFILED_MODEL_RECORD_RUNTIME_UNWIRED_NO_CONSUMER_AUTHORITY"
)
PROFILED_MODEL_SOURCE_PROVENANCE_BINDING_V1_SCHEMA_VERSION: Final = (
    "profiled_model_source_provenance_binding_v1"
)
PROFILED_MODEL_LOGICAL_PROJECTION_V1_SCHEMA_VERSION: Final = (
    "profiled_model_logical_projection_v1"
)
PROFILED_MODEL_RECORD_LINEAGE_BINDING_V1_SCHEMA_VERSION: Final = (
    "profiled_model_record_lineage_binding_v1"
)

PHYSICAL_MODEL_FEATURE_COUNT: Final = 35
LOGICAL_MODEL_FEATURE_COUNT: Final = 446
LOGICAL_MODEL_INPUT_COUNT: Final = 1784
PHYSICAL_ORDERED_FEATURE_NAMES: Final = (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.enabled_feature_names
)
LOGICAL_ORDERED_FEATURE_NAMES: Final = tuple(
    slot.feature_name for slot in FEATURE_SOURCE_REGISTRY_V4.slots
)
LOGICAL_PROFILE_SELECTION_MASK: Final = tuple(
    0 if disposition == PROFILE_DISABLED else 1
    for disposition in (
        ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.ordered_slot_dispositions
    )
)
LOGICAL_PROFILE_SELECTION_MASK_SHA256: Final = stable_sha256(
    list(LOGICAL_PROFILE_SELECTION_MASK)
)
LOGICAL_ENABLED_SLOT_ORDINALS: Final = (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.enabled_slot_ordinals
)
LOGICAL_ENABLED_SLOT_ORDINALS_SHA256: Final = stable_sha256(
    list(LOGICAL_ENABLED_SLOT_ORDINALS)
)

_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:"
    r"[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_MODEL_VECTOR_HASH_DOMAIN = b"canonical_feature_model_vector_v3\0"
_RESULT_CONSTRUCTION_TOKEN = object()
_LOGICAL_CONSTRUCTION_TOKEN = object()
_EXPECTED_TIMEFRAMES = ("5m", "1h")
_CAPTURE_ROOT_EXCLUDED_FIELDS = frozenset(
    {"content_address", "capture_set_sha256", "capture_set_manifest_byte_count"}
)
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
_AUTHORITY_FALSE_FIELDS = (
    "feature_snapshot_published",
    "consumer_eligible",
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "runtime_wired",
)
_FORBIDDEN_MODEL_COST_FIELDS = frozenset(
    {"fee_bps", "spread_bps", "expected_slippage_bps", "expected_funding_bps"}
)

_IMPLEMENTATION_MATERIAL = {
    "schema_version": PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_SCHEMA_VERSION,
    "physical_feature_count": PHYSICAL_MODEL_FEATURE_COUNT,
    "physical_source": "EXACT_RECOMPUTED_AUTHENTICATED_OHLCV_TRANSFORM_V1",
    "logical_slot_count": LOGICAL_MODEL_FEATURE_COUNT,
    "logical_model_input_count": LOGICAL_MODEL_INPUT_COUNT,
    "disabled_encoding": {
        "feature_value": 0.0,
        "missing_mask": 0,
        "stale_mask": 0,
        "source_availability_mask": 0,
        "selection_mask": 0,
    },
    "selected_encoding": {
        "missing_mask": 0,
        "stale_mask": 0,
        "source_availability_mask": 1,
        "selection_mask": 1,
    },
    "provenance_precondition": "EXACT_5M_AND_1H_DURABLE_V4_ENTRIES_FRESHLY_VERIFIED",
    "scalar_input_policy": "CALLER_PROVIDED_MODEL_SCALARS_FORBIDDEN",
    "runtime_wired": False,
}
PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_IMPLEMENTATION_SHA256: Final = stable_sha256(
    _IMPLEMENTATION_MATERIAL
)


class ProfiledModelFeatureSnapshotRecordV1Error(RuntimeError):
    """The model-only record or any upstream evidence failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledModelFeatureSnapshotRecordV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


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


def _strict_contract_copy(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        _fail("PROFILED_MODEL_RECORD_CAPTURE_CONTRACT_NOT_EXACT_DICT")
    try:
        encoded = canonical_json(value)
        parsed = json.loads(encoded)
    except (FeatureSnapshotValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProfiledModelFeatureSnapshotRecordV1Error(
            "PROFILED_MODEL_RECORD_CAPTURE_CONTRACT_NOT_STRICT_JSON"
        ) from exc
    if type(parsed) is not dict:
        _fail("PROFILED_MODEL_RECORD_CAPTURE_CONTRACT_NOT_EXACT_DICT")
    return cast(dict[str, Any], parsed)


def _address_material(address: SourcePayloadAddress) -> dict[str, object]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _materialize_payload(
    store: object,
    payload: bytes,
    *,
    publish: bool,
    reason: str,
) -> dict[str, object]:
    if type(store) is not ImmutableSourcePayloadStore:
        _fail(f"{reason}_STORE_INVALID")
    if type(payload) is not bytes or not payload:
        _fail(f"{reason}_PAYLOAD_INVALID")
    digest = hashlib.sha256(payload).hexdigest()
    try:
        typed_store = cast(ImmutableSourcePayloadStore, store)
        if publish:
            address = typed_store.put(
                payload,
                expected_sha256=digest,
                expected_byte_count=len(payload),
            )
        else:
            address = typed_store.verify(digest, expected_byte_count=len(payload))
        readback = typed_store.get(digest, expected_byte_count=len(payload))
    except SourcePayloadStoreError as exc:
        raise ProfiledModelFeatureSnapshotRecordV1Error(reason) from exc
    if not hmac.compare_digest(readback, payload):
        _fail(f"{reason}_READBACK_MISMATCH")
    return _address_material(address)


def _verify_capture_manifest_cas(
    contract: dict[str, Any],
    store: object,
) -> tuple[bytes, dict[str, object]]:
    material = {
        key: value
        for key, value in contract.items()
        if key not in _CAPTURE_ROOT_EXCLUDED_FIELDS
    }
    payload = canonical_json(material).encode("ascii", errors="strict")
    digest = hashlib.sha256(payload).hexdigest()
    if (
        contract.get("capture_set_sha256") != digest
        or contract.get("capture_set_manifest_byte_count") != len(payload)
    ):
        _fail("PROFILED_MODEL_RECORD_CAPTURE_MANIFEST_BINDING_INVALID")
    address = _materialize_payload(
        store,
        payload,
        publish=False,
        reason="PROFILED_MODEL_RECORD_CAPTURE_MANIFEST_CAS_INVALID",
    )
    if contract.get("content_address") != address:
        _fail("PROFILED_MODEL_RECORD_CAPTURE_MANIFEST_ADDRESS_INVALID")
    return payload, address


def _exact_transform(
    transform_result: object,
    capture_set_contract: object,
) -> tuple[
    dict[str, Any],
    AuthenticatedOhlcvProfileTransformV1Result,
    dict[str, Any],
]:
    if type(transform_result) is not AuthenticatedOhlcvProfileTransformV1Result:
        _fail("PROFILED_MODEL_RECORD_EXACT_TRANSFORM_RESULT_REQUIRED")
    contract = _strict_contract_copy(capture_set_contract)
    capture_sha256 = contract.get("capture_set_sha256")
    if not _valid_sha256(capture_sha256):
        _fail("PROFILED_MODEL_RECORD_CAPTURE_SHA256_INVALID")
    try:
        recomputed = transform_authenticated_ohlcv_profile_v1(
            contract,
            expected_capture_set_sha256=cast(str, capture_sha256),
            expected_profile_sha256=ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
        )
        supplied_artifact = cast(
            AuthenticatedOhlcvProfileTransformV1Result,
            transform_result,
        ).contract
        artifact = recomputed.contract
    except AuthenticatedOhlcvProfileTransformV1Error as exc:
        raise ProfiledModelFeatureSnapshotRecordV1Error(
            "PROFILED_MODEL_RECORD_TRANSFORM_RECOMPUTE_INVALID",
            *exc.reasons,
        ) from exc
    supplied = cast(AuthenticatedOhlcvProfileTransformV1Result, transform_result)
    exact_fields = (
        "schema_version",
        "profile_id",
        "profile_sha256",
        "capture_set_sha256",
        "symbol",
        "ordered_feature_names",
        "ordered_feature_values",
        "ordered_receipt_material_sha256s",
        "artifact_sha256",
        "artifact_json",
    )
    if supplied_artifact != artifact or any(
        getattr(supplied, name) != getattr(recomputed, name) for name in exact_fields
    ):
        _fail("PROFILED_MODEL_RECORD_TRANSFORM_RESULT_RECOMPUTE_MISMATCH")
    if (
        recomputed.profile_id != ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID
        or recomputed.profile_sha256
        != ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256
        or recomputed.ordered_feature_names != PHYSICAL_ORDERED_FEATURE_NAMES
        or len(recomputed.ordered_feature_values) != PHYSICAL_MODEL_FEATURE_COUNT
        or _FORBIDDEN_MODEL_COST_FIELDS.intersection(recomputed.ordered_feature_names)
    ):
        _fail("PROFILED_MODEL_RECORD_TRANSFORM_MODEL_INVENTORY_INVALID")
    expected_authorization = {
        "feature_snapshot_published": False,
        "consumer_eligible": False,
        "trainer_admission_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "runtime_wired": False,
    }
    if artifact.get("authorization") != expected_authorization:
        _fail("PROFILED_MODEL_RECORD_TRANSFORM_AUTHORITY_INVALID")
    return contract, recomputed, artifact


def _timeframe_contracts(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = contract.get("timeframes")
    if type(raw) is not list or len(raw) != 2 or any(type(item) is not dict for item in raw):
        _fail("PROFILED_MODEL_RECORD_TIMEFRAME_INVENTORY_INVALID")
    by_timeframe = {cast(str, item["timeframe"]): item for item in raw}
    if tuple(item.get("timeframe") for item in raw) != _EXPECTED_TIMEFRAMES or set(
        by_timeframe
    ) != set(_EXPECTED_TIMEFRAMES):
        _fail("PROFILED_MODEL_RECORD_TIMEFRAME_ORDER_INVALID")
    return cast(dict[str, dict[str, Any]], by_timeframe)


def _ledger_root_material(ledger: TrainerSourceProvenanceLedgerV4) -> dict[str, str]:
    root = str(ledger.root)
    if not root.startswith("/") or "\x00" in root:
        _fail("PROFILED_MODEL_RECORD_SOURCE_LEDGER_ROOT_INVALID")
    return {
        "source_ledger_root": root,
        "source_ledger_root_sha256": hashlib.sha256(root.encode("utf-8")).hexdigest(),
    }


def _match_source_entry(
    *,
    timeframe: str,
    timeframe_contract: dict[str, Any],
    entry: TrainerSourceProvenanceLedgerEntryV4,
    transform_available_at: datetime,
) -> dict[str, Any]:
    record = entry.record
    source = cast(dict[str, Any], record["source_capture"])
    manifest = cast(dict[str, Any], record["suffix_manifest"])
    rows = cast(list[dict[str, Any]], record["ordered_rows"])
    source_key = f"v2:market:ohlcv_closed:binance:{timeframe_contract['symbol']}:{timeframe}"
    if (
        source.get("source_key") != source_key
        or timeframe_contract.get("source_key") != source_key
        or source.get("source_key_version") != timeframe_contract.get("source_key_version")
        or source.get("atomic_batch_id") != timeframe_contract.get("atomic_batch_id")
        or source.get("consumer_observed_at")
        != timeframe_contract.get("atomic_consumer_observed_at")
        or manifest.get("suffix_digest_sha256")
        != timeframe_contract.get("atomic_suffix_digest_sha256")
        or manifest.get("manifest_cas_address")
        != timeframe_contract.get("atomic_suffix_manifest_address")
    ):
        _fail("PROFILED_MODEL_RECORD_SOURCE_PROVENANCE_CAPTURE_BINDING_INVALID")
    start = timeframe_contract.get("atomic_selected_start_ordinal")
    capture_rows = timeframe_contract.get("rows")
    if (
        type(start) is not int
        or start < 0
        or type(capture_rows) is not list
        or start + len(capture_rows) > len(rows)
    ):
        _fail("PROFILED_MODEL_RECORD_SOURCE_PROVENANCE_SLICE_INVALID")
    source_slice = rows[start : start + len(capture_rows)]
    for capture_row, provenance_row in zip(capture_rows, source_slice, strict=True):
        expected = {
            "selected_ordinal": capture_row["atomic_selected_ordinal"],
            "source_index": capture_row["atomic_source_index"],
            "candle_id": capture_row["candle_id"],
            "candle_open_time_ms": capture_row["candle_open_time_ms"],
            "candle_close_time_ms": capture_row["candle_close_time_ms"],
            "economic_event_time": capture_row["event_time"],
            "producer_event_time": capture_row["producer_event_time"],
            "ingested_at": capture_row["ingested_at"],
            "available_at": capture_row["available_at"],
            "feature_cutoff": capture_row["feature_cutoff"],
            "source": capture_row["source_transport"],
            "source_sequence_id": capture_row["source_sequence_id"],
            "raw_payload_hash": capture_row["raw_payload_hash"],
            "is_backfilled": capture_row["is_backfilled"],
            "source_read_receipt_sha256": capture_row["source_read_receipt_sha256"],
            "exact_payload_sha256": capture_row["exact_payload_sha256"],
            "exact_payload_byte_count": capture_row["exact_payload_byte_count"],
        }
        if any(provenance_row.get(name) != value for name, value in expected.items()):
            _fail("PROFILED_MODEL_RECORD_SOURCE_PROVENANCE_ROW_BINDING_INVALID")
    recorded_text, recorded = _clock(
        record.get("ledger_recorded_at"),
        reason="PROFILED_MODEL_RECORD_SOURCE_LEDGER_RECORDED_AT_INVALID",
    )
    if recorded > transform_available_at:
        _fail("PROFILED_MODEL_RECORD_SOURCE_PROVENANCE_RECORDED_AFTER_TRANSFORM")
    binding = {
        "physical_timeframe": timeframe,
        "source_ledger_sequence": entry.ledger_sequence,
        "source_ledger_entry_sha256": entry.entry_sha256,
        "source_ledger_entry_json_sha256": hashlib.sha256(
            entry.entry_json.encode("ascii")
        ).hexdigest(),
        "source_replay_identity_sha256": entry.replay_identity_sha256,
        "source_cycle_identity_sha256": entry.cycle_identity_sha256,
        "trainer_run_id": entry.trainer_run_id,
        "trainer_cycle_id": entry.trainer_cycle_id,
        "source_ledger_recorded_at": recorded_text,
        "source_key": source["source_key"],
        "source_key_version": source["source_key_version"],
        "atomic_batch_id": source["atomic_batch_id"],
        "atomic_batch_material_sha256": source["atomic_batch_material_sha256"],
        "atomic_consumer_observed_at": source["consumer_observed_at"],
        "suffix_manifest_sha256": manifest["exact_manifest_sha256"],
        "suffix_manifest_cas_address": manifest["manifest_cas_address"],
        "suffix_digest_sha256": manifest["suffix_digest_sha256"],
        "capture_selected_start_ordinal": start,
        "capture_selected_row_count": len(capture_rows),
        "capture_ordered_row_identity_sha256s": list(
            timeframe_contract["ordered_row_identity_sha256s"]
        ),
        "capture_ordered_source_receipt_sha256s": list(
            timeframe_contract["ordered_source_receipt_sha256s"]
        ),
        "capture_timeframe_sha256": timeframe_contract["timeframe_capture_sha256"],
    }
    binding["timeframe_source_provenance_binding_sha256"] = stable_sha256(binding)
    return binding


def _source_provenance_binding(
    *,
    source_provenance_ledger: object,
    source_provenance_entries: object,
    timeframes: dict[str, dict[str, Any]],
    transform_available_at: datetime,
) -> dict[str, Any]:
    if type(source_provenance_ledger) is not TrainerSourceProvenanceLedgerV4:
        _fail("PROFILED_MODEL_RECORD_EXACT_SOURCE_PROVENANCE_LEDGER_REQUIRED")
    if (
        type(source_provenance_entries) is not tuple
        or len(source_provenance_entries) != 2
        or any(
            type(item) is not TrainerSourceProvenanceLedgerEntryV4
            for item in source_provenance_entries
        )
    ):
        _fail("PROFILED_MODEL_RECORD_EXACT_SOURCE_PROVENANCE_ENTRIES_REQUIRED")
    ledger = cast(TrainerSourceProvenanceLedgerV4, source_provenance_ledger)
    supplied = cast(tuple[TrainerSourceProvenanceLedgerEntryV4, ...], source_provenance_entries)
    try:
        fresh_entries = ledger.read_entries()
    except TrainerSourceProvenanceLedgerV4Error as exc:
        raise ProfiledModelFeatureSnapshotRecordV1Error(
            "PROFILED_MODEL_RECORD_SOURCE_PROVENANCE_FRESH_READ_FAILED"
        ) from exc
    fresh: list[TrainerSourceProvenanceLedgerEntryV4] = []
    for entry in supplied:
        if entry.ledger_sequence > len(fresh_entries):
            _fail("PROFILED_MODEL_RECORD_SOURCE_PROVENANCE_ENTRY_NOT_FOUND")
        candidate = fresh_entries[entry.ledger_sequence - 1]
        if (
            candidate.entry_sha256 != entry.entry_sha256
            or candidate.entry_json != entry.entry_json
            or candidate.replay_identity_sha256 != entry.replay_identity_sha256
        ):
            _fail("PROFILED_MODEL_RECORD_SOURCE_PROVENANCE_ENTRY_IDENTITY_MISMATCH")
        fresh.append(candidate)
    entry_by_source_key = {
        cast(str, item.record["source_capture"]["source_key"]): item for item in fresh
    }
    if len(entry_by_source_key) != 2:
        _fail("PROFILED_MODEL_RECORD_SOURCE_PROVENANCE_ENTRY_DUPLICATE")
    bindings: list[dict[str, Any]] = []
    for timeframe in _EXPECTED_TIMEFRAMES:
        timeframe_contract = timeframes[timeframe]
        source_key = cast(str, timeframe_contract["source_key"])
        entry = entry_by_source_key.get(source_key)
        if entry is None:
            _fail("PROFILED_MODEL_RECORD_SOURCE_PROVENANCE_TIMEFRAME_MISSING")
        bindings.append(
            _match_source_entry(
                timeframe=timeframe,
                timeframe_contract=timeframe_contract,
                entry=entry,
                transform_available_at=transform_available_at,
            )
        )
    result: dict[str, Any] = {
        "schema_version": PROFILED_MODEL_SOURCE_PROVENANCE_BINDING_V1_SCHEMA_VERSION,
        "source_ledger_schema_version": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION,
        "source_ledger_namespace": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_NAMESPACE,
        **_ledger_root_material(ledger),
        "timeframe_bindings": bindings,
        "provenance_recorded_before_transform": True,
    }
    result["source_provenance_binding_sha256"] = stable_sha256(result)
    return result


def _logical_projection_material(
    *,
    physical_values: Sequence[float],
    physical_source_labels: Sequence[str],
    physical_receipt_roots: Sequence[str],
) -> dict[str, Any]:
    if not (
        len(physical_values)
        == len(physical_source_labels)
        == len(physical_receipt_roots)
        == PHYSICAL_MODEL_FEATURE_COUNT
    ):
        _fail("PROFILED_MODEL_RECORD_LOGICAL_PROJECTION_PHYSICAL_DIMENSION_INVALID")
    values = [0.0] * LOGICAL_MODEL_FEATURE_COUNT
    missing = [0] * LOGICAL_MODEL_FEATURE_COUNT
    stale = [0] * LOGICAL_MODEL_FEATURE_COUNT
    availability = [0] * LOGICAL_MODEL_FEATURE_COUNT
    source_labels: list[str | None] = [None] * LOGICAL_MODEL_FEATURE_COUNT
    receipt_roots: list[str | None] = [None] * LOGICAL_MODEL_FEATURE_COUNT
    for physical_ordinal, logical_ordinal in enumerate(
        ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.enabled_slot_ordinals
    ):
        values[logical_ordinal] = physical_values[physical_ordinal]
        availability[logical_ordinal] = 1
        source_labels[logical_ordinal] = physical_source_labels[physical_ordinal]
        receipt_roots[logical_ordinal] = physical_receipt_roots[physical_ordinal]
    model_vector = [
        *values,
        *(float(value) for value in missing),
        *(float(value) for value in stale),
        *(float(value) for value in availability),
    ]
    if len(model_vector) != LOGICAL_MODEL_INPUT_COUNT:
        _fail("PROFILED_MODEL_RECORD_LOGICAL_MODEL_VECTOR_DIMENSION_INVALID")
    digest = hashlib.sha256()
    digest.update(_MODEL_VECTOR_HASH_DOMAIN)
    digest.update(bytes.fromhex(FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256))
    digest.update(struct.pack(">I", LOGICAL_MODEL_FEATURE_COUNT))
    for value in model_vector:
        digest.update(struct.pack(">f", float(value)))
    model_vector_sha256 = digest.hexdigest()
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
        "feature_source_labels": source_labels,
        "feature_source_receipt_sha256s": receipt_roots,
        "model_vector_length": LOGICAL_MODEL_INPUT_COUNT,
        "model_vector_sha256": model_vector_sha256,
    }
    material["logical_projection_sha256"] = stable_sha256(material)
    return material


@dataclass(frozen=True, slots=True)
class ProfiledModelLogicalProjectionV1:
    """Factory-authenticated logical 446-slot projection with 1784 inputs."""

    schema_version: str
    profile_id: str
    profile_sha256: str
    base_registry_sha256: str
    base_abi_sha256: str
    ordered_feature_names: tuple[str, ...]
    feature_values: tuple[float, ...]
    missing_mask: tuple[int, ...]
    stale_mask: tuple[int, ...]
    source_availability_mask: tuple[int, ...]
    profile_selection_mask: tuple[int, ...]
    profile_selection_mask_sha256: str
    enabled_slot_ordinals: tuple[int, ...]
    enabled_slot_ordinals_sha256: str
    feature_source_labels: tuple[str | None, ...]
    feature_source_receipt_sha256s: tuple[str | None, ...]
    model_vector: tuple[float, ...]
    model_vector_sha256: str
    logical_projection_sha256: str
    trainer_admission_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    runtime_wired: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _LOGICAL_CONSTRUCTION_TOKEN:
            _fail("PROFILED_MODEL_RECORD_LOGICAL_PROJECTION_FACTORY_REQUIRED")
        vectors = (
            self.ordered_feature_names,
            self.feature_values,
            self.missing_mask,
            self.stale_mask,
            self.source_availability_mask,
            self.profile_selection_mask,
            self.feature_source_labels,
            self.feature_source_receipt_sha256s,
        )
        if any(type(value) is not tuple for value in vectors) or any(
            len(value) != LOGICAL_MODEL_FEATURE_COUNT for value in vectors
        ):
            _fail("PROFILED_MODEL_RECORD_LOGICAL_PROJECTION_DIMENSION_INVALID")
        if type(self.model_vector) is not tuple or len(self.model_vector) != (
            LOGICAL_MODEL_INPUT_COUNT
        ):
            _fail("PROFILED_MODEL_RECORD_LOGICAL_MODEL_VECTOR_DIMENSION_INVALID")
        if any(type(value) is not str for value in self.ordered_feature_names):
            _fail("PROFILED_MODEL_RECORD_LOGICAL_FEATURE_NAME_INVALID")
        if any(
            type(value) is not float
            or not math.isfinite(value)
            or struct.unpack(">f", struct.pack(">f", value))[0] != value
            for value in self.feature_values
        ):
            _fail("PROFILED_MODEL_RECORD_LOGICAL_FEATURE_VALUE_INVALID")
        if any(
            type(value) is not float or not math.isfinite(value)
            for value in self.model_vector
        ):
            _fail("PROFILED_MODEL_RECORD_LOGICAL_MODEL_VECTOR_INVALID")
        for mask in (
            self.missing_mask,
            self.stale_mask,
            self.source_availability_mask,
            self.profile_selection_mask,
        ):
            if any(type(value) is not int or value not in {0, 1} for value in mask):
                _fail("PROFILED_MODEL_RECORD_LOGICAL_MASK_INVALID")
        if any(
            value is not None and type(value) is not str
            for value in self.feature_source_labels
        ) or any(
            value is not None and not _valid_sha256(value)
            for value in self.feature_source_receipt_sha256s
        ):
            _fail("PROFILED_MODEL_RECORD_LOGICAL_SOURCE_EVIDENCE_INVALID")
        physical_values = tuple(
            self.feature_values[ordinal] for ordinal in LOGICAL_ENABLED_SLOT_ORDINALS
        )
        physical_source_labels = tuple(
            self.feature_source_labels[ordinal] for ordinal in LOGICAL_ENABLED_SLOT_ORDINALS
        )
        physical_receipt_roots = tuple(
            self.feature_source_receipt_sha256s[ordinal]
            for ordinal in LOGICAL_ENABLED_SLOT_ORDINALS
        )
        if any(type(value) is not str for value in physical_source_labels) or any(
            not _valid_sha256(value) for value in physical_receipt_roots
        ):
            _fail("PROFILED_MODEL_RECORD_LOGICAL_PROJECTION_SELECTED_EVIDENCE_INVALID")
        expected = _logical_projection_material(
            physical_values=physical_values,
            physical_source_labels=cast(tuple[str, ...], physical_source_labels),
            physical_receipt_roots=cast(tuple[str, ...], physical_receipt_roots),
        )
        expected_model_vector = (
            *expected["feature_values"],
            *(float(value) for value in expected["missing_mask"]),
            *(float(value) for value in expected["stale_mask"]),
            *(float(value) for value in expected["source_availability_mask"]),
        )
        if (
            self.schema_version != PROFILED_MODEL_LOGICAL_PROJECTION_V1_SCHEMA_VERSION
            or sum(self.profile_selection_mask) != PHYSICAL_MODEL_FEATURE_COUNT
            or self.enabled_slot_ordinals != LOGICAL_ENABLED_SLOT_ORDINALS
            or self.enabled_slot_ordinals_sha256
            != LOGICAL_ENABLED_SLOT_ORDINALS_SHA256
            or self.ordered_feature_names != tuple(expected["ordered_feature_names"])
            or self.feature_values != tuple(expected["feature_values"])
            or self.missing_mask != tuple(expected["missing_mask"])
            or self.stale_mask != tuple(expected["stale_mask"])
            or self.source_availability_mask
            != tuple(expected["source_availability_mask"])
            or self.profile_selection_mask != tuple(expected["profile_selection_mask"])
            or self.profile_selection_mask_sha256
            != expected["profile_selection_mask_sha256"]
            or self.feature_source_labels != tuple(expected["feature_source_labels"])
            or self.feature_source_receipt_sha256s
            != tuple(expected["feature_source_receipt_sha256s"])
            or self.model_vector != tuple(expected_model_vector)
            or self.model_vector_sha256 != expected["model_vector_sha256"]
            or self.logical_projection_sha256 != expected["logical_projection_sha256"]
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
            _fail("PROFILED_MODEL_RECORD_LOGICAL_PROJECTION_INVARIANT_INVALID")


def _logical_projection_from_material(
    material: dict[str, Any],
) -> ProfiledModelLogicalProjectionV1:
    model_vector = (
        *material["feature_values"],
        *(float(value) for value in material["missing_mask"]),
        *(float(value) for value in material["stale_mask"]),
        *(float(value) for value in material["source_availability_mask"]),
    )
    return ProfiledModelLogicalProjectionV1(
        schema_version=material["schema_version"],
        profile_id=material["profile_id"],
        profile_sha256=material["profile_sha256"],
        base_registry_sha256=material["base_registry_sha256"],
        base_abi_sha256=material["base_abi_sha256"],
        ordered_feature_names=tuple(material["ordered_feature_names"]),
        feature_values=tuple(material["feature_values"]),
        missing_mask=tuple(material["missing_mask"]),
        stale_mask=tuple(material["stale_mask"]),
        source_availability_mask=tuple(material["source_availability_mask"]),
        profile_selection_mask=tuple(material["profile_selection_mask"]),
        profile_selection_mask_sha256=material["profile_selection_mask_sha256"],
        enabled_slot_ordinals=tuple(material["enabled_slot_ordinals"]),
        enabled_slot_ordinals_sha256=material["enabled_slot_ordinals_sha256"],
        feature_source_labels=tuple(material["feature_source_labels"]),
        feature_source_receipt_sha256s=tuple(material["feature_source_receipt_sha256s"]),
        model_vector=tuple(model_vector),
        model_vector_sha256=material["model_vector_sha256"],
        logical_projection_sha256=material["logical_projection_sha256"],
        trainer_admission_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        runtime_wired=False,
        _construction_token=_LOGICAL_CONSTRUCTION_TOKEN,
    )


def _build_evidence_record(
    *,
    transform_result: object,
    capture_set_contract: object,
    capture_set_store: object,
    artifact_store: object,
    source_provenance_ledger: object,
    source_provenance_entries: object,
    transform_available_at: object,
    generated_at: object,
    publish_artifacts: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    adaptive_ohlcv_feature_selection_profile_v1_contract(
        ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1
    )
    contract, recomputed, artifact = _exact_transform(
        transform_result,
        capture_set_contract,
    )
    _capture_manifest_bytes, capture_address = _verify_capture_manifest_cas(
        contract,
        capture_set_store,
    )
    timestamps = cast(dict[str, Any], contract["timestamps"])
    capture_generated_text, capture_generated = _clock(
        timestamps["generated_at"],
        reason="PROFILED_MODEL_RECORD_CAPTURE_GENERATED_AT_INVALID",
    )
    decision_text, decision = _clock(
        timestamps["decision_time"],
        reason="PROFILED_MODEL_RECORD_DECISION_TIME_INVALID",
    )
    available_text, transform_available = _clock(
        transform_available_at,
        reason="PROFILED_MODEL_RECORD_TRANSFORM_AVAILABLE_AT_INVALID",
    )
    generated_text, generated = _clock(
        generated_at,
        reason="PROFILED_MODEL_RECORD_GENERATED_AT_INVALID",
    )
    if not capture_generated <= transform_available <= generated <= decision:
        _fail("PROFILED_MODEL_RECORD_PUBLICATION_CLOCK_ORDER_INVALID")
    timeframes = _timeframe_contracts(contract)
    if any(
        _clock(
            timeframes[timeframe]["feature_cutoff"],
            reason="PROFILED_MODEL_RECORD_TIMEFRAME_CUTOFF_INVALID",
        )[1]
        >= decision
        for timeframe in _EXPECTED_TIMEFRAMES
    ):
        _fail("PROFILED_MODEL_RECORD_UNFINISHED_TIMEFRAME_CANDLE")
    source_provenance = _source_provenance_binding(
        source_provenance_ledger=source_provenance_ledger,
        source_provenance_entries=source_provenance_entries,
        timeframes=timeframes,
        transform_available_at=transform_available,
    )

    artifact_bytes = recomputed.artifact_json.encode("ascii", errors="strict")
    artifact_address = _materialize_payload(
        artifact_store,
        artifact_bytes,
        publish=publish_artifacts,
        reason="PROFILED_MODEL_RECORD_TRANSFORM_ARTIFACT_CAS_INVALID",
    )
    if artifact_address["payload_sha256"] != recomputed.artifact_sha256:
        _fail("PROFILED_MODEL_RECORD_TRANSFORM_ARTIFACT_ADDRESS_INVALID")

    timeframe_receipts: dict[str, dict[str, Any]] = {}
    timeframe_payload_addresses: dict[str, dict[str, object]] = {}
    for timeframe in _EXPECTED_TIMEFRAMES:
        item = timeframes[timeframe]
        payload = canonical_json(item).encode("ascii", errors="strict")
        address = _materialize_payload(
            artifact_store,
            payload,
            publish=publish_artifacts,
            reason=f"PROFILED_MODEL_RECORD_{timeframe.upper()}_CAPTURE_CAS_INVALID",
        )
        timeframe_payload_addresses[timeframe] = address
        try:
            timeframe_receipts[timeframe] = build_source_read_receipt(
                source_label=f"authenticated_ohlcv:capture:{recomputed.symbol}:{timeframe}",
                payload_type="CANONICAL_OHLCV_TIMEFRAME_CAPTURE_V1",
                payload_sha256=cast(str, address["payload_sha256"]),
                payload_byte_count=cast(int, address["payload_byte_count"]),
                event_time=item["event_time"],
                available_at=available_text,
                consumer_observed_at=available_text,
                feature_cutoff=item["feature_cutoff"],
                read_locator_type="FILE_CONTENT_ADDRESS",
                read_locator=cast(str, address["relative_path"]),
                read_locator_version=cast(str, address["payload_sha256"]),
                finality_type="CLOSED_INTERVAL",
                finality_cutoff=item["feature_cutoff"],
                finality_verified_at=available_text,
                finality_verifier=f"profiled_model_record_{timeframe}_capture_finality_v1",
            )
        except FeatureSnapshotValidationError as exc:
            raise ProfiledModelFeatureSnapshotRecordV1Error(
                "PROFILED_MODEL_RECORD_TIMEFRAME_RECEIPT_INVALID",
                *exc.reasons,
            ) from exc

    features = cast(list[dict[str, Any]], artifact["ordered_features"])
    artifact_receipts: dict[str, dict[str, Any]] = {}
    artifact_derivation_contracts: dict[str, dict[str, Any]] = {}
    for timeframe in _EXPECTED_TIMEFRAMES:
        timeframe_features = [
            item for item in features if item["source_timeframe"] == timeframe
        ]
        derivation_contract = {
            "schema_version": "profiled_model_transform_artifact_derivation_v1",
            "profile_id": recomputed.profile_id,
            "profile_sha256": recomputed.profile_sha256,
            "capture_set_sha256": recomputed.capture_set_sha256,
            "transform_artifact_sha256": recomputed.artifact_sha256,
            "physical_timeframe": timeframe,
            "timeframe_capture_sha256": timeframes[timeframe]["timeframe_capture_sha256"],
            "implementation": artifact["implementation"],
            "ordered_feature_receipt_material_sha256s": [
                item["composite_derivation_receipt_material_sha256"]
                for item in timeframe_features
            ],
        }
        artifact_derivation_contracts[timeframe] = derivation_contract
        derivation = {
            "schema_version": FEATURE_SOURCE_DERIVATION_SCHEMA_VERSION,
            "producer_id": "authenticated_ohlcv_profile_transform_v1",
            "producer_version": AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_SCHEMA_VERSION,
            "transform_sha256": stable_sha256(derivation_contract),
            "configuration_sha256": (
                AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
            ),
        }
        try:
            artifact_receipts[timeframe] = build_source_read_receipt(
                source_label=f"authenticated_ohlcv:transform:{recomputed.symbol}:{timeframe}",
                payload_type="AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_ARTIFACT",
                payload_sha256=recomputed.artifact_sha256,
                payload_byte_count=len(artifact_bytes),
                event_time=timeframes[timeframe]["event_time"],
                available_at=available_text,
                consumer_observed_at=available_text,
                feature_cutoff=timeframes[timeframe]["feature_cutoff"],
                read_locator_type="FILE_CONTENT_ADDRESS",
                read_locator=cast(str, artifact_address["relative_path"]),
                read_locator_version=recomputed.artifact_sha256,
                finality_type="VERSIONED_SNAPSHOT",
                finality_cutoff=available_text,
                finality_verified_at=available_text,
                finality_verifier=f"profiled_model_record_{timeframe}_transform_v1",
                receipt_kind="COMPOSITE_DERIVATION",
                child_read_bindings=[
                    {
                        "input_role": f"canonical_closed_{timeframe}_capture",
                        "receipt_sha256": timeframe_receipts[timeframe]["receipt_sha256"],
                    }
                ],
                derivation_material=derivation,
            )
        except FeatureSnapshotValidationError as exc:
            raise ProfiledModelFeatureSnapshotRecordV1Error(
                "PROFILED_MODEL_RECORD_TRANSFORM_ARTIFACT_RECEIPT_INVALID",
                *exc.reasons,
            ) from exc

    values: list[float] = []
    roots: list[str] = []
    labels: list[str] = []
    feature_evidence: list[dict[str, Any]] = []
    scalar_addresses: list[dict[str, object]] = []
    feature_receipts: list[dict[str, Any]] = []
    for physical_ordinal, item in enumerate(features):
        feature_name = cast(str, item["feature_name"])
        timeframe = cast(str, item["source_timeframe"])
        if feature_name != PHYSICAL_ORDERED_FEATURE_NAMES[physical_ordinal]:
            _fail("PROFILED_MODEL_RECORD_FEATURE_ORDER_INVALID")
        value = item["value_float32"]
        if type(value) is not float or not math.isfinite(value):
            _fail("PROFILED_MODEL_RECORD_FEATURE_VALUE_INVALID")
        scalar_bytes = bytes.fromhex(cast(str, item["value_float32_be_hex"]))
        material = cast(dict[str, Any], item["composite_derivation_receipt_material"])
        if (
            len(scalar_bytes) != 4
            or struct.unpack(">f", scalar_bytes)[0] != value
            or material["payload_sha256"] != hashlib.sha256(scalar_bytes).hexdigest()
            or material["payload_byte_count"] != len(scalar_bytes)
            or stable_sha256(material)
            != item["composite_derivation_receipt_material_sha256"]
        ):
            _fail("PROFILED_MODEL_RECORD_FEATURE_SCALAR_ARTIFACT_BINDING_INVALID")
        scalar_address = _materialize_payload(
            artifact_store,
            scalar_bytes,
            publish=publish_artifacts,
            reason="PROFILED_MODEL_RECORD_FEATURE_SCALAR_CAS_INVALID",
        )
        scalar_addresses.append(scalar_address)
        source_label = f"authenticated_ohlcv:model:{feature_name}"
        derivation = cast(dict[str, Any], material["derivation_material"])
        try:
            receipt = build_source_read_receipt(
                source_label=source_label,
                payload_type="IEEE754_BINARY32_MODEL_SCALAR",
                payload_sha256=cast(str, scalar_address["payload_sha256"]),
                payload_byte_count=cast(int, scalar_address["payload_byte_count"]),
                event_time=timeframes[timeframe]["event_time"],
                available_at=available_text,
                consumer_observed_at=generated_text,
                feature_cutoff=timeframes[timeframe]["feature_cutoff"],
                read_locator_type="FILE_CONTENT_ADDRESS",
                read_locator=cast(str, scalar_address["relative_path"]),
                read_locator_version=recomputed.artifact_sha256,
                finality_type="VERSIONED_SNAPSHOT",
                finality_cutoff=available_text,
                finality_verified_at=available_text,
                finality_verifier="profiled_model_record_exact_transform_scalar_v1",
                receipt_kind="COMPOSITE_DERIVATION",
                child_read_bindings=[
                    {
                        "input_role": f"authenticated_transform_{timeframe}",
                        "receipt_sha256": artifact_receipts[timeframe]["receipt_sha256"],
                    }
                ],
                derivation_material=derivation,
            )
        except FeatureSnapshotValidationError as exc:
            raise ProfiledModelFeatureSnapshotRecordV1Error(
                "PROFILED_MODEL_RECORD_FEATURE_RECEIPT_INVALID",
                *exc.reasons,
            ) from exc
        values.append(value)
        roots.append(cast(str, receipt["receipt_sha256"]))
        labels.append(source_label)
        feature_receipts.append(receipt)
        exact_bindings = cast(dict[str, Any], material["exact_bindings"])
        feature_evidence.append(
            {
                "physical_ordinal": physical_ordinal,
                "logical_base_abi_ordinal": item["ordinal"],
                "feature_name": feature_name,
                "physical_timeframe": timeframe,
                "transform_id": item["transform_id"],
                "value_float32_be_hex": item["value_float32_be_hex"],
                "scalar_payload_sha256": material["payload_sha256"],
                "scalar_payload_address": scalar_address,
                "composite_derivation_receipt_material_sha256": item[
                    "composite_derivation_receipt_material_sha256"
                ],
                "implementation_id": exact_bindings["implementation_id"],
                "implementation_sha256": exact_bindings["implementation_sha256"],
                "module_code_sha256": exact_bindings["module_code_sha256"],
                "global_configuration_sha256": exact_bindings[
                    "global_configuration_sha256"
                ],
                "feature_configuration_sha256": exact_bindings[
                    "feature_configuration_sha256"
                ],
                "transform_sha256": exact_bindings["transform_sha256"],
                "artifact_receipt_sha256": artifact_receipts[timeframe]["receipt_sha256"],
                "feature_root_receipt_sha256": receipt["receipt_sha256"],
            }
        )

    logical_material = _logical_projection_material(
        physical_values=values,
        physical_source_labels=labels,
        physical_receipt_roots=roots,
    )
    logical_binding = {
        "schema_version": PROFILED_MODEL_LOGICAL_PROJECTION_V1_SCHEMA_VERSION,
        "base_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "base_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        "logical_slot_count": LOGICAL_MODEL_FEATURE_COUNT,
        "logical_model_input_count": LOGICAL_MODEL_INPUT_COUNT,
        "profile_selection_mask": list(LOGICAL_PROFILE_SELECTION_MASK),
        "profile_selection_mask_sha256": LOGICAL_PROFILE_SELECTION_MASK_SHA256,
        "enabled_slot_ordinals": list(LOGICAL_ENABLED_SLOT_ORDINALS),
        "enabled_slot_ordinals_sha256": LOGICAL_ENABLED_SLOT_ORDINALS_SHA256,
        "model_vector_sha256": logical_material["model_vector_sha256"],
        "logical_projection_sha256": logical_material["logical_projection_sha256"],
    }
    snapshot_identity_sha256 = stable_sha256(
        {
            "schema_version": PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_SCHEMA_VERSION,
            "profile_sha256": recomputed.profile_sha256,
            "capture_set_sha256": recomputed.capture_set_sha256,
            "transform_artifact_sha256": recomputed.artifact_sha256,
            "source_provenance_binding_sha256": source_provenance[
                "source_provenance_binding_sha256"
            ],
            "transform_available_at": available_text,
            "generated_at": generated_text,
        }
    )
    feature_snapshot_id = f"authenticated_ohlcv_model_{snapshot_identity_sha256}"
    authorization = {name: False for name in _AUTHORITY_FALSE_FIELDS}
    lineage = {
        "schema_version": PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_SCHEMA_VERSION,
        "classification": PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_CLASSIFICATION,
        "status": PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_STATUS,
        "implementation_sha256": (
            PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_IMPLEMENTATION_SHA256
        ),
        "unwired_reason": PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON,
        "profile_id": recomputed.profile_id,
        "profile_sha256": recomputed.profile_sha256,
        "physical_model_feature_count": PHYSICAL_MODEL_FEATURE_COUNT,
        "capture_set_sha256": recomputed.capture_set_sha256,
        "capture_manifest_byte_count": len(_capture_manifest_bytes),
        "capture_manifest_address": capture_address,
        "capture_timestamps": timestamps,
        "transform_available_at": available_text,
        "record_generated_at": generated_text,
        "transform_artifact_schema_version": recomputed.schema_version,
        "transform_artifact_sha256": recomputed.artifact_sha256,
        "transform_artifact_byte_count": len(artifact_bytes),
        "transform_artifact_address": artifact_address,
        "transform_implementation_id": (
            AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_ID
        ),
        "transform_implementation_sha256": (
            AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256
        ),
        "transform_configuration_sha256": (
            AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
        ),
        "ordered_transform_receipt_material_sha256s": list(
            recomputed.ordered_receipt_material_sha256s
        ),
        "source_provenance_binding": source_provenance,
        "timeframe_evidence": [
            {
                "physical_timeframe": timeframe,
                "timeframe_capture_sha256": timeframes[timeframe][
                    "timeframe_capture_sha256"
                ],
                "timeframe_payload_address": timeframe_payload_addresses[timeframe],
                "event_time": timeframes[timeframe]["event_time"],
                "ingested_at": timeframes[timeframe]["ingested_at"],
                "available_at": timeframes[timeframe]["available_at"],
                "atomic_consumer_observed_at": timeframes[timeframe][
                    "atomic_consumer_observed_at"
                ],
                "feature_cutoff": timeframes[timeframe]["feature_cutoff"],
                "latest_candle_id": timeframes[timeframe]["latest_candle_id"],
                "exact_closed_row_count": len(timeframes[timeframe]["rows"]),
                "ordered_row_identity_sha256s": list(
                    timeframes[timeframe]["ordered_row_identity_sha256s"]
                ),
                "ordered_source_receipt_sha256s": list(
                    timeframes[timeframe]["ordered_source_receipt_sha256s"]
                ),
                "capture_receipt_sha256": timeframe_receipts[timeframe][
                    "receipt_sha256"
                ],
                "transform_artifact_receipt_sha256": artifact_receipts[timeframe][
                    "receipt_sha256"
                ],
                "transform_artifact_derivation_contract": (
                    artifact_derivation_contracts[timeframe]
                ),
            }
            for timeframe in _EXPECTED_TIMEFRAMES
        ],
        "feature_evidence": feature_evidence,
        "logical_projection_binding": logical_binding,
        "authorization": authorization,
    }
    all_receipts = [
        *timeframe_receipts.values(),
        *artifact_receipts.values(),
        *feature_receipts,
    ]
    try:
        record = build_feature_snapshot_record(
            provenance_classification=PROVENANCE_CANONICAL_V3,
            legacy_v1_snapshot_id=None,
            symbol=recomputed.symbol,
            timeframe="5m",
            feature_snapshot_id=feature_snapshot_id,
            tensor_decision_time=decision_text,
            temporal_rejection_reasons=[
                PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON
            ],
            ordered_feature_names=PHYSICAL_ORDERED_FEATURE_NAMES,
            feature_values=values,
            missing_mask=[0] * PHYSICAL_MODEL_FEATURE_COUNT,
            stale_mask=[0] * PHYSICAL_MODEL_FEATURE_COUNT,
            source_availability_mask=[1] * PHYSICAL_MODEL_FEATURE_COUNT,
            ordered_feature_source_labels=labels,
            feature_source_receipt_sha256s=roots,
            source_read_receipts=all_receipts,
            feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
            ordered_feature_requirement_classes=["REQUIRED"] * PHYSICAL_MODEL_FEATURE_COUNT,
            original_tensor_id=f"profiled_model_{snapshot_identity_sha256}",
            source_lineage_material=lineage,
            feature_cutoff=timestamps["feature_cutoff"],
            masa_feature_cutoff=timestamps["feature_cutoff"],
            ppo_feature_cutoff=timestamps["feature_cutoff"],
            ppo_decision_time=decision_text,
            generated_at=generated_text,
        )
    except FeatureSnapshotValidationError as exc:
        raise ProfiledModelFeatureSnapshotRecordV1Error(
            "PROFILED_MODEL_RECORD_LEDGER_V3_BUILD_INVALID",
            *exc.reasons,
        ) from exc
    return record, logical_material


def build_profiled_model_feature_snapshot_record_v1(
    *,
    transform_result: AuthenticatedOhlcvProfileTransformV1Result,
    capture_set_contract: Mapping[str, Any],
    capture_set_store: ImmutableSourcePayloadStore,
    artifact_store: ImmutableSourcePayloadStore,
    source_provenance_ledger: TrainerSourceProvenanceLedgerV4,
    source_provenance_entries: tuple[
        TrainerSourceProvenanceLedgerEntryV4,
        TrainerSourceProvenanceLedgerEntryV4,
    ],
    transform_available_at: str,
    generated_at: str,
) -> dict[str, Any]:
    """Build a quarantined 35-feature v3 record from authenticated evidence only."""

    record, _logical = _build_evidence_record(
        transform_result=transform_result,
        capture_set_contract=capture_set_contract,
        capture_set_store=capture_set_store,
        artifact_store=artifact_store,
        source_provenance_ledger=source_provenance_ledger,
        source_provenance_entries=source_provenance_entries,
        transform_available_at=transform_available_at,
        generated_at=generated_at,
        publish_artifacts=True,
    )
    validate_profiled_model_feature_snapshot_record_v1(
        record,
        transform_result=transform_result,
        capture_set_contract=capture_set_contract,
        capture_set_store=capture_set_store,
        artifact_store=artifact_store,
        source_provenance_ledger=source_provenance_ledger,
        source_provenance_entries=source_provenance_entries,
    )
    return record


@dataclass(frozen=True, slots=True)
class ProfiledModelFeatureSnapshotRecordV1Validation:
    """Validated identities and the unauthorised logical model projection."""

    schema_version: str
    classification: str
    status: str
    durable_snapshot_id: str
    record_sha256: str
    frozen_envelope_sha256: str
    source_lineage_sha256: str
    physical_model_vector_sha256: str
    feature_snapshot_id: str
    profile_id: str
    profile_sha256: str
    capture_set_sha256: str
    transform_artifact_sha256: str
    source_provenance_binding_sha256: str
    logical_projection: ProfiledModelLogicalProjectionV1
    lineage_binding_sha256: str
    lineage_binding_json: str = field(repr=False)
    trainer_admission_authorized: bool = False
    prediction_authorized: bool = False
    paper_trading_authorized: bool = False
    live_execution_authorized: bool = False
    runtime_wired: bool = False
    _construction_token: object = field(repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        if self._construction_token is not _RESULT_CONSTRUCTION_TOKEN:
            _fail("PROFILED_MODEL_RECORD_VALIDATION_FACTORY_REQUIRED")
        if any(
            value is not False
            for value in (
                self.trainer_admission_authorized,
                self.prediction_authorized,
                self.paper_trading_authorized,
                self.live_execution_authorized,
                self.runtime_wired,
            )
        ):
            _fail("PROFILED_MODEL_RECORD_VALIDATION_AUTHORITY_INVALID")

    @property
    def lineage_binding(self) -> dict[str, Any]:
        parsed = json.loads(self.lineage_binding_json)
        if type(parsed) is not dict or stable_sha256(parsed) != self.lineage_binding_sha256:
            _fail("PROFILED_MODEL_RECORD_LINEAGE_BINDING_INVALID")
        return cast(dict[str, Any], parsed)


def validate_profiled_model_feature_snapshot_record_v1(
    record: Mapping[str, Any],
    *,
    transform_result: AuthenticatedOhlcvProfileTransformV1Result,
    capture_set_contract: Mapping[str, Any],
    capture_set_store: ImmutableSourcePayloadStore,
    artifact_store: ImmutableSourcePayloadStore,
    source_provenance_ledger: TrainerSourceProvenanceLedgerV4,
    source_provenance_entries: tuple[
        TrainerSourceProvenanceLedgerEntryV4,
        TrainerSourceProvenanceLedgerEntryV4,
    ],
) -> ProfiledModelFeatureSnapshotRecordV1Validation:
    """Recompute every binding and return the deterministic logical projection."""

    try:
        validate_feature_snapshot_record(record)
    except FeatureSnapshotValidationError as exc:
        raise ProfiledModelFeatureSnapshotRecordV1Error(
            "PROFILED_MODEL_RECORD_LEDGER_V3_INVALID",
            *exc.reasons,
        ) from exc
    if type(record) is not dict:
        _fail("PROFILED_MODEL_RECORD_NOT_EXACT_DICT")
    envelope = record.get("frozen_envelope")
    if type(envelope) is not dict:
        _fail("PROFILED_MODEL_RECORD_ENVELOPE_INVALID")
    lineage = envelope.get("source_lineage_material")
    if type(lineage) is not dict:
        _fail("PROFILED_MODEL_RECORD_LINEAGE_INVALID")
    core_lineage = {
        key: value for key, value in lineage.items() if key not in _LEDGER_RESERVED_LINEAGE_FIELDS
    }
    transform_available_at = core_lineage.get("transform_available_at")
    generated_at = envelope.get("generated_at")
    expected, logical_material = _build_evidence_record(
        transform_result=transform_result,
        capture_set_contract=capture_set_contract,
        capture_set_store=capture_set_store,
        artifact_store=artifact_store,
        source_provenance_ledger=source_provenance_ledger,
        source_provenance_entries=source_provenance_entries,
        transform_available_at=transform_available_at,
        generated_at=generated_at,
        publish_artifacts=False,
    )
    if record != expected:
        _fail("PROFILED_MODEL_RECORD_FULL_RECOMPUTE_MISMATCH")
    if (
        envelope.get("ordered_feature_names") != list(PHYSICAL_ORDERED_FEATURE_NAMES)
        or len(envelope["feature_values"]) != PHYSICAL_MODEL_FEATURE_COUNT
        or _FORBIDDEN_MODEL_COST_FIELDS.intersection(envelope["ordered_feature_names"])
        or envelope.get("temporal_rejection_reasons")
        != [PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON]
        or envelope.get("strict_training_eligible") is not False
        or envelope.get("strict_training_ineligibility_reasons")
        != [TEMPORAL_REJECTION_INELIGIBILITY_REASON]
        or core_lineage.get("authorization")
        != {name: False for name in _AUTHORITY_FALSE_FIELDS}
    ):
        _fail("PROFILED_MODEL_RECORD_QUARANTINE_OR_INVENTORY_INVALID")
    logical_projection = _logical_projection_from_material(logical_material)
    lineage_binding: dict[str, Any] = {
        "schema_version": PROFILED_MODEL_RECORD_LINEAGE_BINDING_V1_SCHEMA_VERSION,
        "durable_snapshot_id": record["durable_snapshot_id"],
        "record_sha256": record["record_sha256"],
        "frozen_envelope_sha256": record["frozen_envelope_sha256"],
        "source_lineage_sha256": envelope["source_lineage_sha256"],
        "physical_model_vector_sha256": envelope["model_vector_sha256"],
        "feature_snapshot_id": envelope["feature_snapshot_id"],
        "profile_id": core_lineage["profile_id"],
        "profile_sha256": core_lineage["profile_sha256"],
        "capture_set_sha256": core_lineage["capture_set_sha256"],
        "transform_artifact_sha256": core_lineage["transform_artifact_sha256"],
        "source_provenance_binding_sha256": core_lineage["source_provenance_binding"][
            "source_provenance_binding_sha256"
        ],
        "logical_profile_selection_mask_sha256": (
            logical_projection.profile_selection_mask_sha256
        ),
        "logical_enabled_slot_ordinals": list(
            logical_projection.enabled_slot_ordinals
        ),
        "logical_enabled_slot_ordinals_sha256": (
            logical_projection.enabled_slot_ordinals_sha256
        ),
        "logical_model_vector_sha256": logical_projection.model_vector_sha256,
        "logical_projection_sha256": logical_projection.logical_projection_sha256,
        "feature_cutoff": envelope["feature_cutoff"],
        "decision_time": envelope["tensor_decision_time"],
        "generated_at": envelope["generated_at"],
        "authorization": {name: False for name in _AUTHORITY_FALSE_FIELDS},
    }
    lineage_binding_json = canonical_json(lineage_binding)
    return ProfiledModelFeatureSnapshotRecordV1Validation(
        schema_version=PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_SCHEMA_VERSION,
        classification=PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_CLASSIFICATION,
        status=PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_STATUS,
        durable_snapshot_id=cast(str, record["durable_snapshot_id"]),
        record_sha256=cast(str, record["record_sha256"]),
        frozen_envelope_sha256=cast(str, record["frozen_envelope_sha256"]),
        source_lineage_sha256=cast(str, envelope["source_lineage_sha256"]),
        physical_model_vector_sha256=cast(str, envelope["model_vector_sha256"]),
        feature_snapshot_id=cast(str, envelope["feature_snapshot_id"]),
        profile_id=cast(str, core_lineage["profile_id"]),
        profile_sha256=cast(str, core_lineage["profile_sha256"]),
        capture_set_sha256=cast(str, core_lineage["capture_set_sha256"]),
        transform_artifact_sha256=cast(str, core_lineage["transform_artifact_sha256"]),
        source_provenance_binding_sha256=cast(
            str,
            core_lineage["source_provenance_binding"][
                "source_provenance_binding_sha256"
            ],
        ),
        logical_projection=logical_projection,
        lineage_binding_sha256=stable_sha256(lineage_binding),
        lineage_binding_json=lineage_binding_json,
        _construction_token=_RESULT_CONSTRUCTION_TOKEN,
    )


def validate_profiled_model_logical_projection_claim_v1(
    projection: ProfiledModelLogicalProjectionV1,
    *,
    ordered_feature_names: object,
    feature_values: object,
    missing_mask: object,
    stale_mask: object,
    source_availability_mask: object,
    profile_selection_mask: object,
    enabled_slot_ordinals: object,
    model_vector: object,
) -> None:
    """Reject any logical 446 projection claim that differs by one value or slot."""

    if type(projection) is not ProfiledModelLogicalProjectionV1:
        _fail("PROFILED_MODEL_RECORD_LOGICAL_PROJECTION_EXACT_RESULT_REQUIRED")
    claims = (
        (ordered_feature_names, projection.ordered_feature_names),
        (feature_values, projection.feature_values),
        (missing_mask, projection.missing_mask),
        (stale_mask, projection.stale_mask),
        (source_availability_mask, projection.source_availability_mask),
        (profile_selection_mask, projection.profile_selection_mask),
        (enabled_slot_ordinals, projection.enabled_slot_ordinals),
        (model_vector, projection.model_vector),
    )
    for supplied, expected in claims:
        if type(supplied) not in {list, tuple} or tuple(
            cast(Sequence[object], supplied)
        ) != expected:
            _fail("PROFILED_MODEL_RECORD_LOGICAL_PROJECTION_CLAIM_MISMATCH")


__all__ = [
    "LOGICAL_MODEL_FEATURE_COUNT",
    "LOGICAL_MODEL_INPUT_COUNT",
    "LOGICAL_ENABLED_SLOT_ORDINALS",
    "LOGICAL_ENABLED_SLOT_ORDINALS_SHA256",
    "LOGICAL_ORDERED_FEATURE_NAMES",
    "LOGICAL_PROFILE_SELECTION_MASK",
    "LOGICAL_PROFILE_SELECTION_MASK_SHA256",
    "PHYSICAL_MODEL_FEATURE_COUNT",
    "PHYSICAL_ORDERED_FEATURE_NAMES",
    "PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_CLASSIFICATION",
    "PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_IMPLEMENTATION_SHA256",
    "PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_SCHEMA_VERSION",
    "PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_STATUS",
    "PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON",
    "PROFILED_MODEL_LOGICAL_PROJECTION_V1_SCHEMA_VERSION",
    "PROFILED_MODEL_RECORD_LINEAGE_BINDING_V1_SCHEMA_VERSION",
    "PROFILED_MODEL_SOURCE_PROVENANCE_BINDING_V1_SCHEMA_VERSION",
    "ProfiledModelFeatureSnapshotRecordV1Error",
    "ProfiledModelFeatureSnapshotRecordV1Validation",
    "ProfiledModelLogicalProjectionV1",
    "build_profiled_model_feature_snapshot_record_v1",
    "validate_profiled_model_feature_snapshot_record_v1",
    "validate_profiled_model_logical_projection_claim_v1",
]
