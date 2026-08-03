"""Audit-tool bridge between a resolution trace and the incomplete P0-D ledger.

The two committed v4 boundaries intentionally prove different facts:

* :mod:`feature_resolution_trace_v4` binds all 446 TensorBuilder slots, exact
  float32 model bytes, masks, selectors, transforms, and declared clocks, but
  its observations and source roots are caller supplied; and
* :mod:`feature_snapshot_publication_ledger_v4` freshly authenticates its P0-C
  closed-OHLCV source entry and its ledger-owned feature-artifact CAS bytes,
  but deliberately records unresolved per-field source labels, absent roots,
  absent per-field ``available_at`` clocks, and absent derivation identities.

This module establishes only the safe intersection of those facts.  It
freshly revalidates both factory artifacts, requires exact snapshot identity,
ABI order, values, missing mask, and stale mask, and requires the authenticated
P0-D audit entry to predate the trace decision.  Source availability is
compared but never promoted because P0-D intentionally stores an all-zero
placeholder vector.

The resulting artifact freezes the exact gaps that a later resolver-capture
and publication implementation must close.  It is not an authenticated feature
snapshot, publication receipt, trainer admission receipt, prediction receipt,
or execution authorization.  Every downstream flag remains factory-frozen
false.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, NoReturn, cast

from v2.backend.app.services.native_trainer.feature_resolution_trace_v4 import (
    FEATURE_RESOLUTION_TRACE_V4_ABI_SHA256,
    FEATURE_RESOLUTION_TRACE_V4_SCHEMA_VERSION,
    FEATURE_RESOLUTION_TRACE_V4_SLOT_COUNT,
    FeatureResolutionTraceArtifactV4,
    FeatureResolutionTraceV4ValidationError,
)
from v2.backend.app.services.native_trainer.feature_snapshot_publication_ledger_v4 import (
    FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_EVIDENCE_CLASSIFICATION,
    FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_SCHEMA_VERSION,
    NATIVE_MODEL_ABI_ORIGIN,
    SOURCE_SCOPE_INCOMPLETENESS_REASONS,
    UNRESOLVED_SOURCE_LABEL,
    FeatureSnapshotPublicationLedgerEntryV4,
    FeatureSnapshotPublicationLedgerV4,
    FeatureSnapshotPublicationLedgerV4Error,
)

FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_SCHEMA_VERSION = (
    "trainer_feature_resolution_publication_bridge_v4"
)
FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_EVIDENCE_CLASSIFICATION = (
    "AUDIT_ONLY_TRACE_TO_AUTHENTICATED_INCOMPLETE_P0D_STRUCTURAL_BINDING"
)
FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_DOWNSTREAM_STATUS = (
    "NON_CONSUMABLE_AUTHENTICATED_COMPLETE_SNAPSHOT_AND_PUBLICATION_RECEIPT_ABSENT"
)
MAX_FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_BYTES = 128 * 1024

AUTHENTICATION_GAP_REASONS = (
    "RESOLVER_BRANCH_CAPTURE_UNAUTHENTICATED",
    "RAW_CONTEXT_CAS_UNVERIFIED",
    "TRACE_SOURCE_ROOT_NAMESPACE_AND_LOCATOR_UNAUTHENTICATED",
    "TRACE_NEGATIVE_EVIDENCE_UNAUTHENTICATED",
    "P0D_PER_FIELD_SOURCE_RECEIPTS_ABSENT",
    "P0D_PER_FIELD_AVAILABLE_AT_ABSENT",
    "P0D_RESOLVED_SOURCE_LABELS_UNRESOLVED",
    "P0D_SOURCE_AVAILABILITY_UNPROVEN",
    "P0D_DERIVATION_IDENTITIES_ABSENT",
    "P0D_TRUTHFUL_PUBLICATION_COMPLETION_CLOCK_ABSENT",
    "TRACE_SOURCE_SCOPE_NOT_BOUND_TO_AUTHENTICATED_SOURCE_LEDGERS",
    "CONSUMER_ADMISSION_RECEIPT_ABSENT",
)

_TRUE_FIELDS = (
    "audit_bridge_only",
    "trace_structural_integrity_revalidated",
    "p0d_durable_ledger_entry_and_owned_cas_revalidated",
    "cross_artifact_identity_abi_value_and_masks_bound",
    "p0d_audit_evidence_recorded_no_later_than_trace_decision",
)
_P0D_FALSE_FIELDS = (
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "source_scope_complete",
    "per_field_receipts_complete",
    "truthful_completion_clock_present",
    "consumer_eligible",
    "trainer_admission_granted",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)
_TRACE_FALSE_FIELDS = (
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
_FALSE_FIELDS = (
    "authenticated_complete_snapshot_ready",
    "resolver_branch_capture_authenticated",
    "raw_context_cas_verified",
    "source_receipts_authenticated",
    "source_scope_complete",
    "per_field_receipts_complete",
    "per_field_available_at_complete",
    "resolved_source_mapping_verified",
    "derivation_identity_complete",
    "truthful_publication_completion_clock_present",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)
_TRACE_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "trace_sha256",
        "raw_context_sha256",
        "tensor_id",
        "feature_snapshot_id",
        "symbol",
        "timeframe",
        "decision_time",
        "source_lineage_sha256",
        "feature_abi_sha256",
        "feature_slot_count",
        "ordered_feature_names_sha256",
        "ordered_source_labels_sha256",
        "missing_mask_sha256",
        "stale_mask_sha256",
        "source_availability_mask_sha256",
        "model_vector_float32_be_sha256",
        "model_vector_float32_be_byte_count",
        "slot_observation_graph_sha256",
        "resolved_slot_count",
        "typed_negative_slot_count",
        "required_value_contract_valid",
    }
)
_PUBLICATION_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "ledger_sequence",
        "entry_sha256",
        "publication_identity_sha256",
        "source_ledger_sequence",
        "source_ledger_entry_sha256",
        "artifact_record_id",
        "feature_snapshot_id",
        "symbol",
        "timeframe",
        "artifact_serialization_sha256",
        "artifact_binding_sha256",
        "feature_abi_sha256",
        "feature_count",
        "vector_binding_sha256",
        "ordered_feature_names_sha256",
        "ordered_feature_values_sha256",
        "missing_mask_sha256",
        "stale_mask_sha256",
        "source_availability_mask_sha256",
        "ordered_resolved_source_labels_sha256",
        "per_field_root_receipt_sha256s_sha256",
        "per_field_available_at_sha256",
        "snapshot_generated_at",
        "ledger_recorded_at",
    }
)
_CROSS_BINDING_FIELDS = frozenset(
    {
        "feature_snapshot_id",
        "symbol",
        "timeframe",
        "feature_abi_sha256",
        "feature_count",
        "ordered_feature_names_sha256",
        "ordered_feature_values_sha256",
        "missing_mask_sha256",
        "stale_mask_sha256",
        "trace_source_availability_mask_sha256",
        "p0d_source_availability_mask_sha256",
        "source_availability_vectors_equal",
        "source_availability_comparison_only_not_authenticated",
        "trace_ordered_source_labels_sha256",
        "p0d_ordered_source_labels_sha256",
        "trace_raw_context_sha256",
        "p0d_artifact_serialization_sha256",
        "p0d_ledger_recorded_at",
        "trace_decision_time",
        "p0d_candle_close_strictly_before_trace_decision",
        "p0d_artifact_generated_no_later_than_trace_decision",
        "p0d_ledger_recorded_no_later_than_trace_decision",
        "cross_artifact_binding_sha256",
    }
)
_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "trace_binding",
        "publication_binding",
        "cross_artifact_binding",
        "authentication_gap_reasons",
        *_TRUE_FIELDS,
        *_FALSE_FIELDS,
        "bridge_sha256",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CONSTRUCTION_TOKEN = object()


class FeatureResolutionPublicationBridgeV4ValidationError(ValueError):
    """The two upstream artifacts cannot form one truthful audit bridge."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise FeatureResolutionPublicationBridgeV4ValidationError(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _parse_clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        _fail(reason)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        _fail(reason)
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if parsed < _EPOCH or canonical != value:
        _fail(reason)
    return parsed


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
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_NOT_STRICT_JSON")
    if (
        len(encoded.encode("ascii"))
        > MAX_FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_BYTES
    ):
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_SIZE_LIMIT_EXCEEDED")
    return encoded


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def _exact_dict(
    value: object, fields: frozenset[str], *, reason: str
) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(reason)
    mapping = cast(dict[object, object], value)
    if any(type(key) is not str for key in mapping) or frozenset(mapping) != fields:
        _fail(reason)
    return cast(dict[str, Any], dict(mapping))


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _parse_json(value: object) -> dict[str, Any]:
    if type(value) is not str or not value:
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_JSON_INVALID")
    try:
        raw = value.encode("ascii", errors="strict")
        if len(raw) > MAX_FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_BYTES:
            _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_JSON_INVALID")
        parsed = json.loads(
            value,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=lambda _: _fail(
                "FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_JSON_CONSTANT_FORBIDDEN"
            ),
        )
    except FeatureResolutionPublicationBridgeV4ValidationError:
        raise
    except (
        UnicodeEncodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
    ):
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_JSON_INVALID")
    if type(parsed) is not dict:
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_NOT_EXACT_OBJECT")
    return cast(dict[str, Any], parsed)


def _read_upstreams(
    trace_artifact: object,
    publication_ledger: object,
    publication_entry: object,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if type(trace_artifact) is not FeatureResolutionTraceArtifactV4:
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_EXACT_TRACE_REQUIRED")
    if type(publication_entry) is not FeatureSnapshotPublicationLedgerEntryV4:
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_EXACT_P0D_ENTRY_REQUIRED")
    if type(publication_ledger) is not FeatureSnapshotPublicationLedgerV4:
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_EXACT_P0D_LEDGER_REQUIRED")
    try:
        trace = trace_artifact.trace
    except FeatureResolutionTraceV4ValidationError as exc:
        raise FeatureResolutionPublicationBridgeV4ValidationError(
            "FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_TRACE_REVALIDATION_FAILED"
        ) from exc
    try:
        supplied_publication = publication_entry.record
        durable_entries = publication_ledger.read_entries()
    except FeatureSnapshotPublicationLedgerV4Error as exc:
        raise FeatureResolutionPublicationBridgeV4ValidationError(
            "FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_P0D_REVALIDATION_FAILED"
        ) from exc
    matches = tuple(
        entry
        for entry in durable_entries
        if entry.ledger_sequence == publication_entry.ledger_sequence
        and entry.entry_sha256 == publication_entry.entry_sha256
    )
    if len(matches) != 1:
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_P0D_ENTRY_NOT_DURABLY_PRESENT")
    try:
        durable_publication = matches[0].record
    except FeatureSnapshotPublicationLedgerV4Error as exc:
        raise FeatureResolutionPublicationBridgeV4ValidationError(
            "FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_P0D_REVALIDATION_FAILED"
        ) from exc
    if (
        matches[0].entry_json != publication_entry.entry_json
        or durable_publication != supplied_publication
    ):
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_P0D_ENTRY_BINDING_MISMATCH")
    return trace, durable_publication


def _build_material(
    trace: dict[str, Any],
    publication: dict[str, Any],
) -> dict[str, Any]:
    tensor = cast(dict[str, Any], trace["tensor_binding"])
    artifact = cast(dict[str, Any], publication["feature_artifact_binding"])
    vector = cast(dict[str, Any], publication["feature_vector_binding"])
    source = cast(dict[str, Any], publication["source_provenance_binding"])
    temporal = cast(dict[str, Any], publication["temporal_binding"])
    derivation = cast(dict[str, Any], publication["derivation_binding"])
    slots = cast(list[dict[str, Any]], trace["slot_observations"])

    if (
        trace["schema_version"] != FEATURE_RESOLUTION_TRACE_V4_SCHEMA_VERSION
        or publication["schema_version"]
        != FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_SCHEMA_VERSION
        or publication["evidence_classification"]
        != FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_EVIDENCE_CLASSIFICATION
        or vector["abi_origin"] != NATIVE_MODEL_ABI_ORIGIN
        or trace["feature_abi_sha256"] != FEATURE_RESOLUTION_TRACE_V4_ABI_SHA256
        or vector["feature_abi_sha256"] != FEATURE_RESOLUTION_TRACE_V4_ABI_SHA256
        or trace["feature_slot_count"] != FEATURE_RESOLUTION_TRACE_V4_SLOT_COUNT
        or vector["feature_count"] != FEATURE_RESOLUTION_TRACE_V4_SLOT_COUNT
        or any(trace.get(name) is not False for name in _TRACE_FALSE_FIELDS)
        or any(publication.get(name) is not False for name in _P0D_FALSE_FIELDS)
    ):
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_UPSTREAM_CONTRACT_MISMATCH")

    identity_pairs = (
        (tensor["feature_snapshot_id"], artifact["feature_snapshot_id"]),
        (tensor["symbol"], artifact["symbol"]),
        (tensor["timeframe"], artifact["timeframe"]),
    )
    if any(left != right for left, right in identity_pairs):
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_SNAPSHOT_IDENTITY_MISMATCH")

    trace_names = [slot["feature_name"] for slot in slots]
    trace_values = [slot["tensor_value"] for slot in slots]
    trace_missing = [slot["missing_mask"] for slot in slots]
    trace_stale = [slot["stale_mask"] for slot in slots]
    trace_availability = [slot["source_availability_mask"] for slot in slots]
    trace_sources = [slot["resolved_source_label"] for slot in slots]
    p0d_names = cast(list[Any], vector["ordered_feature_names"])
    p0d_values = cast(list[Any], vector["ordered_feature_values"])
    p0d_missing = cast(list[Any], vector["missing_mask"])
    p0d_stale = cast(list[Any], vector["stale_mask"])
    p0d_availability = cast(list[Any], vector["source_availability_mask"])
    p0d_sources = cast(list[Any], vector["ordered_resolved_source_labels"])

    if trace_names != p0d_names:
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_FEATURE_ORDER_MISMATCH")
    if trace_values != p0d_values:
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_FEATURE_VALUES_MISMATCH")
    if trace_missing != p0d_missing:
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_MISSING_MASK_MISMATCH")
    if trace_stale != p0d_stale:
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_STALE_MASK_MISMATCH")
    if any(source != UNRESOLVED_SOURCE_LABEL for source in p0d_sources):
        _fail(
            "FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_P0D_SOURCE_LABELS_NOT_UNRESOLVED"
        )
    if any(root is not None for root in vector["per_field_root_receipt_sha256s"]):
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_P0D_PER_FIELD_ROOTS_PRESENT")
    if any(clock is not None for clock in vector["per_field_available_at"]):
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_P0D_PER_FIELD_CLOCKS_PRESENT")
    if (
        vector["feature_source_evidence_complete"] is not False
        or vector["feature_available_at_complete"] is not False
        or derivation["derivation_identity_complete"] is not False
        or temporal["publication_completed_at"] is not None
        or publication["source_scope_incompleteness_reasons"]
        != list(SOURCE_SCOPE_INCOMPLETENESS_REASONS)
    ):
        _fail(
            "FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_P0D_INCOMPLETE_INVARIANT_CHANGED"
        )

    decision = _parse_clock(
        tensor["decision_time"],
        reason="FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_TRACE_DECISION_TIME_INVALID",
    )
    candle_close = _parse_clock(
        artifact["candle_close_time"],
        reason="FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_P0D_CANDLE_CLOSE_INVALID",
    )
    generated = _parse_clock(
        artifact["generated_at"],
        reason="FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_P0D_GENERATED_AT_INVALID",
    )
    recorded = _parse_clock(
        publication["ledger_recorded_at"],
        reason="FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_P0D_LEDGER_RECORDED_AT_INVALID",
    )
    if candle_close >= decision:
        _fail(
            "FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_CANDLE_NOT_CLOSED_BEFORE_DECISION"
        )
    if generated > decision:
        _fail(
            "FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_ARTIFACT_GENERATED_AFTER_DECISION"
        )
    if recorded > decision:
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_P0D_RECORDED_AFTER_DECISION")

    names_sha = _sha256(trace_names)
    values_sha = _sha256(trace_values)
    missing_sha = _sha256(trace_missing)
    stale_sha = _sha256(trace_stale)
    trace_availability_sha = _sha256(trace_availability)
    p0d_availability_sha = _sha256(p0d_availability)
    trace_sources_sha = _sha256(trace_sources)
    p0d_sources_sha = _sha256(p0d_sources)
    if (
        tensor["ordered_feature_names_sha256"] != names_sha
        or tensor["missing_mask_sha256"] != missing_sha
        or tensor["stale_mask_sha256"] != stale_sha
        or tensor["source_availability_mask_sha256"] != trace_availability_sha
        or tensor["ordered_source_labels_sha256"] != trace_sources_sha
        or vector["ordered_values_sha256"]
        != _sha256(
            {
                "ordered_feature_names": trace_names,
                "ordered_feature_values": trace_values,
            }
        )
    ):
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_UPSTREAM_VECTOR_HASH_MISMATCH")

    trace_binding: dict[str, object] = {
        "schema_version": trace["schema_version"],
        "trace_sha256": trace["trace_sha256"],
        "raw_context_sha256": trace["raw_context_sha256"],
        "tensor_id": tensor["tensor_id"],
        "feature_snapshot_id": tensor["feature_snapshot_id"],
        "symbol": tensor["symbol"],
        "timeframe": tensor["timeframe"],
        "decision_time": tensor["decision_time"],
        "source_lineage_sha256": tensor["source_lineage_sha256"],
        "feature_abi_sha256": trace["feature_abi_sha256"],
        "feature_slot_count": trace["feature_slot_count"],
        "ordered_feature_names_sha256": tensor["ordered_feature_names_sha256"],
        "ordered_source_labels_sha256": tensor["ordered_source_labels_sha256"],
        "missing_mask_sha256": tensor["missing_mask_sha256"],
        "stale_mask_sha256": tensor["stale_mask_sha256"],
        "source_availability_mask_sha256": tensor["source_availability_mask_sha256"],
        "model_vector_float32_be_sha256": tensor["model_vector_float32_be_sha256"],
        "model_vector_float32_be_byte_count": tensor[
            "model_vector_float32_be_byte_count"
        ],
        "slot_observation_graph_sha256": trace["slot_observation_graph_sha256"],
        "resolved_slot_count": trace["resolved_slot_count"],
        "typed_negative_slot_count": trace["typed_negative_slot_count"],
        "required_value_contract_valid": trace["required_value_contract_valid"],
    }
    publication_binding: dict[str, object] = {
        "schema_version": publication["schema_version"],
        "ledger_sequence": publication["ledger_sequence"],
        "entry_sha256": publication["entry_sha256"],
        "publication_identity_sha256": publication["publication_identity_sha256"],
        "source_ledger_sequence": source["source_ledger_sequence"],
        "source_ledger_entry_sha256": source["source_ledger_entry_sha256"],
        "artifact_record_id": artifact["artifact_record_id"],
        "feature_snapshot_id": artifact["feature_snapshot_id"],
        "symbol": artifact["symbol"],
        "timeframe": artifact["timeframe"],
        "artifact_serialization_sha256": artifact["artifact_serialization_sha256"],
        "artifact_binding_sha256": artifact["artifact_binding_sha256"],
        "feature_abi_sha256": vector["feature_abi_sha256"],
        "feature_count": vector["feature_count"],
        "vector_binding_sha256": vector["vector_binding_sha256"],
        "ordered_feature_names_sha256": names_sha,
        "ordered_feature_values_sha256": values_sha,
        "missing_mask_sha256": missing_sha,
        "stale_mask_sha256": stale_sha,
        "source_availability_mask_sha256": p0d_availability_sha,
        "ordered_resolved_source_labels_sha256": p0d_sources_sha,
        "per_field_root_receipt_sha256s_sha256": _sha256(
            vector["per_field_root_receipt_sha256s"]
        ),
        "per_field_available_at_sha256": _sha256(vector["per_field_available_at"]),
        "snapshot_generated_at": artifact["generated_at"],
        "ledger_recorded_at": publication["ledger_recorded_at"],
    }
    cross: dict[str, object] = {
        "feature_snapshot_id": tensor["feature_snapshot_id"],
        "symbol": tensor["symbol"],
        "timeframe": tensor["timeframe"],
        "feature_abi_sha256": trace["feature_abi_sha256"],
        "feature_count": trace["feature_slot_count"],
        "ordered_feature_names_sha256": names_sha,
        "ordered_feature_values_sha256": values_sha,
        "missing_mask_sha256": missing_sha,
        "stale_mask_sha256": stale_sha,
        "trace_source_availability_mask_sha256": trace_availability_sha,
        "p0d_source_availability_mask_sha256": p0d_availability_sha,
        "source_availability_vectors_equal": trace_availability == p0d_availability,
        "source_availability_comparison_only_not_authenticated": True,
        "trace_ordered_source_labels_sha256": trace_sources_sha,
        "p0d_ordered_source_labels_sha256": p0d_sources_sha,
        "trace_raw_context_sha256": trace["raw_context_sha256"],
        "p0d_artifact_serialization_sha256": artifact["artifact_serialization_sha256"],
        "p0d_ledger_recorded_at": publication["ledger_recorded_at"],
        "trace_decision_time": tensor["decision_time"],
        "p0d_candle_close_strictly_before_trace_decision": True,
        "p0d_artifact_generated_no_later_than_trace_decision": True,
        "p0d_ledger_recorded_no_later_than_trace_decision": True,
    }
    cross["cross_artifact_binding_sha256"] = _sha256(cross)
    gaps = list(AUTHENTICATION_GAP_REASONS)
    if trace["required_value_contract_valid"] is not True:
        gaps.append("REQUIRED_VALUE_CONTRACT_INVALID")
    if any(trace_stale):
        gaps.append("STALE_FEATURE_SLOTS_PRESENT")
    record: dict[str, Any] = {
        "schema_version": FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_SCHEMA_VERSION,
        "evidence_classification": (
            FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_EVIDENCE_CLASSIFICATION
        ),
        "downstream_status": FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_DOWNSTREAM_STATUS,
        "trace_binding": trace_binding,
        "publication_binding": publication_binding,
        "cross_artifact_binding": cross,
        "authentication_gap_reasons": gaps,
        **{name: True for name in _TRUE_FIELDS},
        **{name: False for name in _FALSE_FIELDS},
    }
    record["bridge_sha256"] = _sha256(record)
    return record


def _validate_material(value: object) -> dict[str, Any]:
    record = _exact_dict(
        value,
        _ROOT_FIELDS,
        reason="FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_FIELDS_INVALID",
    )
    _exact_dict(
        record["trace_binding"],
        _TRACE_BINDING_FIELDS,
        reason="FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_TRACE_BINDING_FIELDS_INVALID",
    )
    _exact_dict(
        record["publication_binding"],
        _PUBLICATION_BINDING_FIELDS,
        reason="FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_PUBLICATION_BINDING_FIELDS_INVALID",
    )
    cross = _exact_dict(
        record["cross_artifact_binding"],
        _CROSS_BINDING_FIELDS,
        reason="FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_CROSS_BINDING_FIELDS_INVALID",
    )
    if (
        record["schema_version"]
        != FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_SCHEMA_VERSION
        or record["evidence_classification"]
        != FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_EVIDENCE_CLASSIFICATION
        or record["downstream_status"]
        != FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_DOWNSTREAM_STATUS
        or any(record[name] is not True for name in _TRUE_FIELDS)
        or any(record[name] is not False for name in _FALSE_FIELDS)
        or type(record["authentication_gap_reasons"]) is not list
        or record["authentication_gap_reasons"][: len(AUTHENTICATION_GAP_REASONS)]
        != list(AUTHENTICATION_GAP_REASONS)
        or cross["source_availability_comparison_only_not_authenticated"] is not True
    ):
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_CONSTANT_OR_FLAG_MISMATCH")
    if any(
        type(reason) is not str or not reason
        for reason in record["authentication_gap_reasons"]
    ):
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_GAP_REASON_INVALID")
    cross_without_hash = {
        key: item
        for key, item in cross.items()
        if key != "cross_artifact_binding_sha256"
    }
    if not _valid_sha256(cross["cross_artifact_binding_sha256"]) or cross[
        "cross_artifact_binding_sha256"
    ] != _sha256(cross_without_hash):
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_CROSS_BINDING_SHA256_MISMATCH")
    material = {key: item for key, item in record.items() if key != "bridge_sha256"}
    if not _valid_sha256(record["bridge_sha256"]) or record["bridge_sha256"] != _sha256(
        material
    ):
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_SHA256_MISMATCH")
    return record


@dataclass(frozen=True, slots=True)
class FeatureResolutionPublicationBridgeArtifactV4:
    """Factory-only association artifact that can never grant admission."""

    schema_version: str
    bridge_sha256: str
    bridge_json: str = field(repr=False)
    _trace_artifact: FeatureResolutionTraceArtifactV4 = field(repr=False, compare=False)
    _publication_ledger: FeatureSnapshotPublicationLedgerV4 = field(
        repr=False,
        compare=False,
    )
    _publication_entry: FeatureSnapshotPublicationLedgerEntryV4 = field(
        repr=False,
        compare=False,
    )
    _construction_token: object = field(repr=False, compare=False)
    audit_bridge_only: bool = field(default=True, init=False)
    trace_structural_integrity_revalidated: bool = field(default=True, init=False)
    p0d_durable_ledger_entry_and_owned_cas_revalidated: bool = field(
        default=True,
        init=False,
    )
    cross_artifact_identity_abi_value_and_masks_bound: bool = field(
        default=True, init=False
    )
    p0d_audit_evidence_recorded_no_later_than_trace_decision: bool = field(
        default=True,
        init=False,
    )
    authenticated_complete_snapshot_ready: bool = field(default=False, init=False)
    resolver_branch_capture_authenticated: bool = field(default=False, init=False)
    raw_context_cas_verified: bool = field(default=False, init=False)
    source_receipts_authenticated: bool = field(default=False, init=False)
    source_scope_complete: bool = field(default=False, init=False)
    per_field_receipts_complete: bool = field(default=False, init=False)
    per_field_available_at_complete: bool = field(default=False, init=False)
    resolved_source_mapping_verified: bool = field(default=False, init=False)
    derivation_identity_complete: bool = field(default=False, init=False)
    truthful_publication_completion_clock_present: bool = field(
        default=False, init=False
    )
    feature_snapshot_published: bool = field(default=False, init=False)
    feature_publication_receipt_emitted: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail(
                "FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_FACTORY_CONSTRUCTION_REQUIRED"
            )
        parsed = _validate_material(_parse_json(self.bridge_json))
        trace, publication = _read_upstreams(
            self._trace_artifact,
            self._publication_ledger,
            self._publication_entry,
        )
        expected = _build_material(trace, publication)
        if (
            self.schema_version
            != FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_SCHEMA_VERSION
            or self.bridge_sha256 != parsed["bridge_sha256"]
            or parsed != expected
            or self.bridge_json != _canonical_json(expected)
            or any(getattr(self, name) is not True for name in _TRUE_FIELDS)
            or any(getattr(self, name) is not False for name in _FALSE_FIELDS)
        ):
            _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_ARTIFACT_BINDING_MISMATCH")

    @property
    def bridge(self) -> dict[str, Any]:
        """Return a fresh mapping after revalidating both upstream artifacts."""

        parsed = _validate_material(_parse_json(self.bridge_json))
        trace, publication = _read_upstreams(
            self._trace_artifact,
            self._publication_ledger,
            self._publication_entry,
        )
        expected = _build_material(trace, publication)
        if parsed != expected:
            _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_UPSTREAM_CHANGED")
        return cast(dict[str, Any], json.loads(_canonical_json(parsed)))


def build_feature_resolution_publication_bridge_v4(
    *,
    trace_artifact: FeatureResolutionTraceArtifactV4,
    publication_ledger: FeatureSnapshotPublicationLedgerV4,
    publication_entry: FeatureSnapshotPublicationLedgerEntryV4,
) -> FeatureResolutionPublicationBridgeArtifactV4:
    """Bind one trace to one exact P0-D entry without promoting either one."""

    trace, publication = _read_upstreams(
        trace_artifact,
        publication_ledger,
        publication_entry,
    )
    material = _build_material(trace, publication)
    # Repeat both authenticated reads after materialization.  A source ledger,
    # owned CAS object, or trace artifact that changed during binding fails
    # before a bridge object exists.
    final_trace, final_publication = _read_upstreams(
        trace_artifact,
        publication_ledger,
        publication_entry,
    )
    if final_trace != trace or final_publication != publication:
        _fail("FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_UPSTREAM_CHANGED_DURING_BIND")
    canonical = _canonical_json(material)
    return FeatureResolutionPublicationBridgeArtifactV4(
        schema_version=FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_SCHEMA_VERSION,
        bridge_sha256=cast(str, material["bridge_sha256"]),
        bridge_json=canonical,
        _trace_artifact=trace_artifact,
        _publication_ledger=publication_ledger,
        _publication_entry=publication_entry,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "AUTHENTICATION_GAP_REASONS",
    "FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_DOWNSTREAM_STATUS",
    "FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_EVIDENCE_CLASSIFICATION",
    "FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_SCHEMA_VERSION",
    "FeatureResolutionPublicationBridgeArtifactV4",
    "FeatureResolutionPublicationBridgeV4ValidationError",
    "build_feature_resolution_publication_bridge_v4",
]
