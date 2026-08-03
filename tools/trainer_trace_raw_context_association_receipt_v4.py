"""Audit-only P0-F2 association between one trace and immutable raw context.

P0-E and P0-F1 deliberately prove different, incomplete facts.  P0-E binds a
structurally validated feature-resolution trace to one committed,
CAS-integrity-revalidated incomplete P0-D artifact publication.  P0-F1 pins
producer-supplied canonical raw-context bytes in immutable CAS and associates
them with one committed, CAS-integrity-revalidated P0-D entry.

This module intersects those two artifacts without promoting either one.  It
requires their exact P0-D identities to agree, requires the trace-declared raw
context SHA-256 to equal the freshly revalidated P0-F1 CAS payload SHA-256, and
enforces the closed-candle/capture/publication/decision clock order.  That is an
integrity association only: it does not attest how the producer constructed the
payload, authenticate resolver/source/per-field evidence, publish a feature
snapshot, admit a trainer sample, authorize prediction, or authorize trading.

The module is tool-only and intentionally has no runtime, service, network, or
exchange wiring.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, NoReturn, cast

from tools.trainer_feature_resolution_publication_bridge_v4 import (
    AUTHENTICATION_GAP_REASONS,
    FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_DOWNSTREAM_STATUS,
    FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_EVIDENCE_CLASSIFICATION,
    FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_SCHEMA_VERSION,
    FeatureResolutionPublicationBridgeArtifactV4,
    FeatureResolutionPublicationBridgeV4ValidationError,
)
from tools.trainer_raw_context_cas_receipt_v4 import (
    MAX_RAW_CONTEXT_V4_BYTES,
    RAW_CONTEXT_AUTHENTICATION_LIMITATIONS,
    RAW_CONTEXT_CAS_RECEIPT_V4_DOWNSTREAM_STATUS,
    RAW_CONTEXT_CAS_RECEIPT_V4_EVIDENCE_CLASSIFICATION,
    RAW_CONTEXT_CAS_RECEIPT_V4_SCHEMA_VERSION,
    RawContextCasReceiptArtifactV4,
    RawContextCasReceiptV4ValidationError,
)

TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SCHEMA_VERSION = (
    "trainer_trace_raw_context_association_receipt_v4"
)
TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_EVIDENCE_CLASSIFICATION = (
    "AUDIT_ONLY_INTEGRITY_BOUND_TRACE_TO_IMMUTABLE_RAW_CONTEXT_CAS"
)
TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_DOWNSTREAM_STATUS = (
    "TRACE_TO_CAS_INTEGRITY_ASSOCIATION_ONLY_NO_SOURCE_PUBLICATION_ADMISSION_"
    "PREDICTION_OR_EXECUTION_AUTHORIZATION"
)

# Resource-integrity ceilings only.  They choose no market, feature, sample,
# threshold, leverage, position, or risk outcome.
MAX_TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_BYTES = 128 * 1024
MAX_TRACE_RAW_CONTEXT_ASSOCIATION_JSON_DEPTH = 8
MAX_TRACE_RAW_CONTEXT_ASSOCIATION_JSON_NODES = 512
MAX_TRACE_RAW_CONTEXT_ASSOCIATION_LABEL_BYTES = 256

TRACE_RAW_CONTEXT_ASSOCIATION_LIMITATIONS = (
    "UPSTREAM_IMMUTABLE_PAYLOAD_CONSTRUCTION_NOT_INDEPENDENTLY_ATTESTED",
    "TRACE_TO_RAW_CONTEXT_ASSOCIATION_IS_INTEGRITY_ONLY",
    "TRACE_TO_RAW_CONTEXT_ASSOCIATION_IS_NOT_SOURCE_AUTHENTICATION",
    "RESOLVER_BRANCH_CAPTURE_NOT_AUTHENTICATED",
    "PRODUCER_IDENTITY_NOT_INDEPENDENTLY_AUTHENTICATED",
    "PER_FIELD_SOURCE_RECEIPTS_ABSENT",
    "PER_FIELD_AVAILABLE_AT_EVIDENCE_ABSENT",
    "RESOLVED_SOURCE_MAPPING_NOT_AUTHENTICATED",
    "NEGATIVE_SOURCE_EVIDENCE_NOT_AUTHENTICATED",
    "FEATURE_PUBLICATION_RECEIPT_ABSENT",
    "CONSUMER_ADMISSION_RECEIPT_ABSENT",
)

_TRUE_FIELD = "trace_to_raw_context_cas_association_verified"
_FALSE_FIELDS = (
    "upstream_payload_construction_independently_attested",
    "trace_association_source_authentication_verified",
    "resolver_branch_capture_authenticated",
    "producer_identity_independently_authenticated",
    "source_receipts_authenticated",
    "source_scope_complete",
    "per_field_receipts_complete",
    "per_field_available_at_complete",
    "resolved_source_mapping_verified",
    "negative_evidence_authenticated",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)

_P0E_TRUE_FIELDS = (
    "audit_bridge_only",
    "trace_structural_integrity_revalidated",
    "p0d_durable_ledger_entry_and_owned_cas_revalidated",
    "cross_artifact_identity_abi_value_and_masks_bound",
    "p0d_audit_evidence_recorded_no_later_than_trace_decision",
)
_P0E_FALSE_FIELDS = (
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
_P0F1_TRUE_FIELDS = (
    "audit_receipt_only",
    "exact_canonical_raw_context_bytes_pinned",
    "raw_context_cas_integrity_revalidated",
    "p0d_committed_head_and_owned_cas_freshly_revalidated",
    "snapshot_and_closed_candle_identity_bound",
    "declared_producer_code_and_configuration_identity_bound",
)
_P0F1_FALSE_FIELDS = (
    "upstream_payload_construction_independently_attested",
    "trace_raw_context_binding_verified",
    "resolver_branch_capture_authenticated",
    "producer_identity_independently_authenticated",
    "source_receipts_authenticated",
    "source_scope_complete",
    "per_field_receipts_complete",
    "per_field_available_at_complete",
    "resolved_source_mapping_verified",
    "negative_evidence_authenticated",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)

_P0E_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "p0e_bridge_sha256",
        "p0e_cross_artifact_binding_sha256",
        "p0e_authentication_gap_reasons_sha256",
        "trace_sha256",
        "trace_raw_context_sha256",
        "feature_snapshot_id",
        "symbol",
        "timeframe",
        "trace_decision_time",
        "p0d_ledger_sequence",
        "p0d_ledger_entry_sha256",
        "p0d_publication_identity_sha256",
        "p0d_source_ledger_sequence",
        "p0d_source_ledger_entry_sha256",
        "p0d_artifact_record_id",
        "p0d_artifact_binding_sha256",
        "p0d_artifact_serialization_sha256",
        "p0d_snapshot_generated_at",
        "p0d_ledger_recorded_at",
        "p0e_bridge_binding_sha256",
    }
)
_P0F1_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "p0f1_receipt_sha256",
        "raw_context_sha256",
        "raw_context_byte_count",
        "raw_context_document_binding_sha256",
        "context_locator_sha256",
        "producer_identity_sha256",
        "raw_context_cas_binding_sha256",
        "raw_context_cas_payload_sha256",
        "raw_context_cas_payload_byte_count",
        "raw_context_cas_store_root_sha256",
        "raw_context_cas_relative_path",
        "p0d_association_sha256",
        "p0d_ledger_sequence",
        "p0d_ledger_entry_sha256",
        "p0d_publication_identity_sha256",
        "p0d_publication_replay_identity_sha256",
        "p0d_source_ledger_sequence",
        "p0d_source_ledger_entry_sha256",
        "p0d_artifact_record_id",
        "p0d_artifact_binding_sha256",
        "p0d_artifact_serialization_sha256",
        "feature_snapshot_id",
        "symbol",
        "timeframe",
        "candle_close_time",
        "raw_context_capture_completed_at",
        "p0d_snapshot_generated_at",
        "p0d_ledger_recorded_at",
        "p0f1_authentication_limitations_sha256",
        "p0f1_raw_context_binding_sha256",
    }
)
_CROSS_BINDING_FIELDS = frozenset(
    {
        "p0e_bridge_sha256",
        "p0f1_receipt_sha256",
        "trace_sha256",
        "raw_context_sha256",
        "feature_snapshot_id",
        "symbol",
        "timeframe",
        "p0d_ledger_sequence",
        "p0d_ledger_entry_sha256",
        "p0d_publication_identity_sha256",
        "p0d_source_ledger_sequence",
        "p0d_source_ledger_entry_sha256",
        "p0d_artifact_record_id",
        "p0d_artifact_binding_sha256",
        "p0d_artifact_serialization_sha256",
        "candle_close_time",
        "raw_context_capture_completed_at",
        "snapshot_generated_at",
        "ledger_recorded_at",
        "trace_decision_time",
        "association_binding_sha256",
    }
)
_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "p0e_bridge_binding",
        "p0f1_raw_context_binding",
        "cross_artifact_binding",
        "association_limitations",
        _TRUE_FIELD,
        *_FALSE_FIELDS,
        "receipt_sha256",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,255}$", re.ASCII)
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CONSTRUCTION_TOKEN = object()


class TraceRawContextAssociationReceiptV4ValidationError(ValueError):
    """P0-E and P0-F1 cannot form one truthful, immutable association."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise TraceRawContextAssociationReceiptV4ValidationError(*reasons) from None


@dataclass(slots=True)
class _JsonBudget:
    remaining_bytes: int
    remaining_nodes: int = MAX_TRACE_RAW_CONTEXT_ASSOCIATION_JSON_NODES

    def consume_bytes(self, amount: int) -> None:
        if amount < 0 or amount > self.remaining_bytes:
            _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SIZE_LIMIT_EXCEEDED")
        self.remaining_bytes -= amount

    def consume_node(self) -> None:
        if self.remaining_nodes <= 0:
            _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_NODE_LIMIT_EXCEEDED")
        self.remaining_nodes -= 1


def _consume_json_string(value: str, budget: _JsonBudget) -> None:
    budget.consume_bytes(2)
    if len(value) > budget.remaining_bytes:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SIZE_LIMIT_EXCEEDED")
    if (
        value.isascii()
        and value.isprintable()
        and '"' not in value
        and "\\" not in value
    ):
        budget.consume_bytes(len(value))
        return
    for character in value:
        codepoint = ord(character)
        if character in {'"', "\\"} or codepoint in {8, 9, 10, 12, 13}:
            width = 2
        elif codepoint < 0x20:
            width = 6
        elif codepoint <= 0x7E:
            width = 1
        elif codepoint <= 0xFFFF:
            width = 6
        else:
            width = 12
        budget.consume_bytes(width)


def _preflight_json(
    value: object,
    *,
    budget: _JsonBudget,
    depth: int = 0,
) -> None:
    budget.consume_node()
    if depth > MAX_TRACE_RAW_CONTEXT_ASSOCIATION_JSON_DEPTH:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_DEPTH_LIMIT_EXCEEDED")
    if value is None:
        budget.consume_bytes(4)
        return
    if type(value) is bool:
        budget.consume_bytes(4 if value else 5)
        return
    if type(value) is int:
        try:
            encoded = str(value)
        except (ValueError, MemoryError):
            _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_INTEGER_LIMIT_EXCEEDED")
        budget.consume_bytes(len(encoded))
        return
    if type(value) is float:
        if not math.isfinite(value):
            _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_NUMBER_NOT_FINITE")
        budget.consume_bytes(len(repr(value)))
        return
    if type(value) is str:
        _consume_json_string(value, budget)
        return
    if type(value) is list:
        items = cast(list[object], value)
        if len(items) > budget.remaining_nodes:
            _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_NODE_LIMIT_EXCEEDED")
        budget.consume_bytes(2)
        for index, item in enumerate(items):
            if index:
                budget.consume_bytes(1)
            _preflight_json(item, budget=budget, depth=depth + 1)
        return
    if type(value) is dict:
        mapping = cast(dict[object, object], value)
        if len(mapping) > budget.remaining_nodes:
            _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_NODE_LIMIT_EXCEEDED")
        budget.consume_bytes(2)
        for index, (key, item) in enumerate(mapping.items()):
            if type(key) is not str:
                _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_JSON_KEY_INVALID")
            if index:
                budget.consume_bytes(1)
            _consume_json_string(key, budget)
            budget.consume_bytes(1)
            _preflight_json(item, budget=budget, depth=depth + 1)
        return
    _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_NOT_STRICT_JSON")


def _strict_json_snapshot(
    value: object,
    *,
    depth: int = 0,
    remaining_nodes: list[int] | None = None,
) -> Any:
    if remaining_nodes is None:
        remaining_nodes = [MAX_TRACE_RAW_CONTEXT_ASSOCIATION_JSON_NODES]
    remaining_nodes[0] -= 1
    if remaining_nodes[0] < 0:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_NODE_LIMIT_EXCEEDED")
    if depth > MAX_TRACE_RAW_CONTEXT_ASSOCIATION_JSON_DEPTH:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_DEPTH_LIMIT_EXCEEDED")
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_NUMBER_NOT_FINITE")
        return value
    if type(value) is list:
        return [
            _strict_json_snapshot(
                item,
                depth=depth + 1,
                remaining_nodes=remaining_nodes,
            )
            for item in cast(list[object], value)
        ]
    if type(value) is dict:
        copied: dict[str, Any] = {}
        for key, item in cast(dict[object, object], value).items():
            if type(key) is not str:
                _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_JSON_KEY_INVALID")
            copied[key] = _strict_json_snapshot(
                item,
                depth=depth + 1,
                remaining_nodes=remaining_nodes,
            )
        return copied
    _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_NOT_STRICT_JSON")


def _canonical_json(value: object) -> str:
    initial_budget = _JsonBudget(
        remaining_bytes=MAX_TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_BYTES
    )
    _preflight_json(value, budget=initial_budget)
    copied = _strict_json_snapshot(value)
    final_budget = _JsonBudget(
        remaining_bytes=MAX_TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_BYTES
    )
    _preflight_json(copied, budget=final_budget)
    expected_size = (
        MAX_TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_BYTES
        - final_budget.remaining_bytes
    )
    try:
        encoded = json.dumps(
            copied,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        raw = encoded.encode("ascii", errors="strict")
    except (
        TypeError,
        ValueError,
        OverflowError,
        UnicodeEncodeError,
        RecursionError,
        MemoryError,
    ):
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_NOT_STRICT_JSON")
    if not raw or len(raw) != expected_size:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SERIALIZATION_SIZE_MISMATCH")
    return encoded


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _parse_json(value: object) -> dict[str, Any]:
    if type(value) is not str or not value:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_JSON_INVALID")
    try:
        raw = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_JSON_INVALID")
    if len(raw) > MAX_TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_BYTES:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_JSON_SIZE_INVALID")
    try:
        parsed = json.loads(
            value,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=lambda _: _fail(
                "TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_JSON_CONSTANT_FORBIDDEN"
            ),
        )
    except TraceRawContextAssociationReceiptV4ValidationError:
        raise
    except (
        json.JSONDecodeError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
        MemoryError,
    ):
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_JSON_INVALID")
    if type(parsed) is not dict:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_NOT_EXACT_OBJECT")
    copied = cast(dict[str, Any], _strict_json_snapshot(parsed))
    if _canonical_json(copied) != value:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_JSON_NOT_CANONICAL")
    return copied


def _exact_dict(
    value: object,
    fields: frozenset[str],
    *,
    reason: str,
) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(reason)
    mapping = cast(dict[object, object], value)
    if any(type(key) is not str for key in mapping) or frozenset(mapping) != fields:
        _fail(reason)
    return cast(dict[str, Any], dict(mapping))


def _mapping(value: object, *, reason: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(reason)
    return cast(dict[str, Any], value)


def _required_sha256(value: object, *, reason: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(reason)
    return value


def _required_label(value: object, *, reason: str) -> str:
    if (
        type(value) is not str
        or not value.isascii()
        or len(value.encode("ascii")) > MAX_TRACE_RAW_CONTEXT_ASSOCIATION_LABEL_BYTES
        or _LABEL_RE.fullmatch(value) is None
    ):
        _fail(reason)
    return value


def _required_text(value: object, *, reason: str, max_bytes: int = 1024) -> str:
    if type(value) is not str or not value or "\x00" in value:
        _fail(reason)
    try:
        byte_count = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError:
        _fail(reason)
    if byte_count > max_bytes:
        _fail(reason)
    return value


def _required_positive_int(value: object, *, reason: str) -> int:
    if type(value) is not int or value <= 0:
        _fail(reason)
    return value


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


def _validate_named_hashes(mapping: dict[str, Any]) -> None:
    for name, value in mapping.items():
        if name.endswith("sha256"):
            _required_sha256(
                value,
                reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SHA256_FIELD_INVALID",
            )


def _read_upstreams(
    bridge_artifact: object,
    raw_context_artifact: object,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if type(bridge_artifact) is not FeatureResolutionPublicationBridgeArtifactV4:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_EXACT_P0E_BRIDGE_REQUIRED")
    if type(raw_context_artifact) is not RawContextCasReceiptArtifactV4:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_EXACT_P0F1_RECEIPT_REQUIRED")
    try:
        bridge = bridge_artifact.bridge
    except FeatureResolutionPublicationBridgeV4ValidationError as exc:
        raise TraceRawContextAssociationReceiptV4ValidationError(
            "TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_P0E_REVALIDATION_FAILED"
        ) from exc
    try:
        raw_context = raw_context_artifact.receipt
    except RawContextCasReceiptV4ValidationError as exc:
        raise TraceRawContextAssociationReceiptV4ValidationError(
            "TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_P0F1_REVALIDATION_FAILED"
        ) from exc
    return bridge, raw_context


def _validate_upstream_contracts(
    bridge: dict[str, Any],
    raw_context: dict[str, Any],
) -> None:
    if (
        bridge.get("schema_version")
        != FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_SCHEMA_VERSION
        or bridge.get("evidence_classification")
        != FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_EVIDENCE_CLASSIFICATION
        or bridge.get("downstream_status")
        != FEATURE_RESOLUTION_PUBLICATION_BRIDGE_V4_DOWNSTREAM_STATUS
        or any(bridge.get(name) is not True for name in _P0E_TRUE_FIELDS)
        or any(bridge.get(name) is not False for name in _P0E_FALSE_FIELDS)
        or type(bridge.get("authentication_gap_reasons")) is not list
        or bridge["authentication_gap_reasons"][: len(AUTHENTICATION_GAP_REASONS)]
        != list(AUTHENTICATION_GAP_REASONS)
    ):
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_P0E_CONTRACT_MISMATCH")
    if (
        raw_context.get("schema_version") != RAW_CONTEXT_CAS_RECEIPT_V4_SCHEMA_VERSION
        or raw_context.get("evidence_classification")
        != RAW_CONTEXT_CAS_RECEIPT_V4_EVIDENCE_CLASSIFICATION
        or raw_context.get("downstream_status")
        != RAW_CONTEXT_CAS_RECEIPT_V4_DOWNSTREAM_STATUS
        or any(raw_context.get(name) is not True for name in _P0F1_TRUE_FIELDS)
        or any(raw_context.get(name) is not False for name in _P0F1_FALSE_FIELDS)
        or raw_context.get("authentication_limitations")
        != list(RAW_CONTEXT_AUTHENTICATION_LIMITATIONS)
    ):
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_P0F1_CONTRACT_MISMATCH")


def _p0e_binding(bridge: dict[str, Any]) -> dict[str, Any]:
    trace = _mapping(
        bridge.get("trace_binding"),
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_P0E_TRACE_BINDING_INVALID",
    )
    publication = _mapping(
        bridge.get("publication_binding"),
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_P0E_PUBLICATION_BINDING_INVALID",
    )
    cross = _mapping(
        bridge.get("cross_artifact_binding"),
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_P0E_CROSS_BINDING_INVALID",
    )
    material: dict[str, Any] = {
        "schema_version": bridge["schema_version"],
        "p0e_bridge_sha256": bridge["bridge_sha256"],
        "p0e_cross_artifact_binding_sha256": cross["cross_artifact_binding_sha256"],
        "p0e_authentication_gap_reasons_sha256": _sha256_json(
            bridge["authentication_gap_reasons"]
        ),
        "trace_sha256": trace["trace_sha256"],
        "trace_raw_context_sha256": trace["raw_context_sha256"],
        "feature_snapshot_id": trace["feature_snapshot_id"],
        "symbol": trace["symbol"],
        "timeframe": trace["timeframe"],
        "trace_decision_time": trace["decision_time"],
        "p0d_ledger_sequence": publication["ledger_sequence"],
        "p0d_ledger_entry_sha256": publication["entry_sha256"],
        "p0d_publication_identity_sha256": publication["publication_identity_sha256"],
        "p0d_source_ledger_sequence": publication["source_ledger_sequence"],
        "p0d_source_ledger_entry_sha256": publication["source_ledger_entry_sha256"],
        "p0d_artifact_record_id": publication["artifact_record_id"],
        "p0d_artifact_binding_sha256": publication["artifact_binding_sha256"],
        "p0d_artifact_serialization_sha256": publication[
            "artifact_serialization_sha256"
        ],
        "p0d_snapshot_generated_at": publication["snapshot_generated_at"],
        "p0d_ledger_recorded_at": publication["ledger_recorded_at"],
    }
    _validate_named_hashes(material)
    _required_label(
        material["feature_snapshot_id"],
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_FEATURE_SNAPSHOT_ID_INVALID",
    )
    _required_label(
        material["symbol"],
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SYMBOL_INVALID",
    )
    _required_label(
        material["timeframe"],
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_TIMEFRAME_INVALID",
    )
    _required_label(
        material["p0d_artifact_record_id"],
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_ARTIFACT_RECORD_ID_INVALID",
    )
    _required_positive_int(
        material["p0d_ledger_sequence"],
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_P0D_LEDGER_SEQUENCE_INVALID",
    )
    _required_positive_int(
        material["p0d_source_ledger_sequence"],
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SOURCE_LEDGER_SEQUENCE_INVALID",
    )
    material["p0e_bridge_binding_sha256"] = _sha256_json(material)
    return material


def _p0f1_binding(raw_context: dict[str, Any]) -> dict[str, Any]:
    locator = _mapping(
        raw_context.get("context_locator"),
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_CONTEXT_LOCATOR_INVALID",
    )
    snapshot = _mapping(
        raw_context.get("snapshot_identity"),
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SNAPSHOT_IDENTITY_INVALID",
    )
    temporal = _mapping(
        raw_context.get("temporal_identity"),
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_TEMPORAL_IDENTITY_INVALID",
    )
    producer = _mapping(
        raw_context.get("producer_identity"),
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_PRODUCER_IDENTITY_INVALID",
    )
    cas = _mapping(
        raw_context.get("raw_context_cas_binding"),
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_CAS_BINDING_INVALID",
    )
    association = _mapping(
        raw_context.get("p0d_ledger_association"),
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_P0D_ASSOCIATION_INVALID",
    )
    if (
        cas.get("canonical_json_verified") is not True
        or association.get("committed_head_and_owned_cas_fresh_read_verified")
        is not True
    ):
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_P0F1_FRESH_FLAG_MISMATCH")
    material: dict[str, Any] = {
        "schema_version": raw_context["schema_version"],
        "p0f1_receipt_sha256": raw_context["receipt_sha256"],
        "raw_context_sha256": raw_context["raw_context_sha256"],
        "raw_context_byte_count": raw_context["raw_context_byte_count"],
        "raw_context_document_binding_sha256": raw_context[
            "raw_context_document_binding_sha256"
        ],
        "context_locator_sha256": locator["locator_sha256"],
        "producer_identity_sha256": producer["producer_identity_sha256"],
        "raw_context_cas_binding_sha256": cas["cas_binding_sha256"],
        "raw_context_cas_payload_sha256": cas["payload_sha256"],
        "raw_context_cas_payload_byte_count": cas["payload_byte_count"],
        "raw_context_cas_store_root_sha256": cas["store_root_sha256"],
        "raw_context_cas_relative_path": cas["relative_path"],
        "p0d_association_sha256": association["association_sha256"],
        "p0d_ledger_sequence": association["ledger_sequence"],
        "p0d_ledger_entry_sha256": association["ledger_entry_sha256"],
        "p0d_publication_identity_sha256": association["publication_identity_sha256"],
        "p0d_publication_replay_identity_sha256": association[
            "publication_replay_identity_sha256"
        ],
        "p0d_source_ledger_sequence": association["source_ledger_sequence"],
        "p0d_source_ledger_entry_sha256": association["source_ledger_entry_sha256"],
        "p0d_artifact_record_id": association["artifact_record_id"],
        "p0d_artifact_binding_sha256": association["artifact_binding_sha256"],
        "p0d_artifact_serialization_sha256": association[
            "artifact_serialization_sha256"
        ],
        "feature_snapshot_id": snapshot["feature_snapshot_id"],
        "symbol": snapshot["symbol"],
        "timeframe": snapshot["timeframe"],
        "candle_close_time": temporal["candle_close_time"],
        "raw_context_capture_completed_at": temporal[
            "raw_context_capture_completed_at"
        ],
        "p0d_snapshot_generated_at": association["snapshot_generated_at"],
        "p0d_ledger_recorded_at": association["ledger_recorded_at"],
        "p0f1_authentication_limitations_sha256": _sha256_json(
            raw_context["authentication_limitations"]
        ),
    }
    _validate_named_hashes(material)
    if (
        type(material["raw_context_byte_count"]) is not int
        or not 1 <= material["raw_context_byte_count"] <= MAX_RAW_CONTEXT_V4_BYTES
        or material["raw_context_cas_payload_byte_count"]
        != material["raw_context_byte_count"]
        or material["raw_context_cas_payload_sha256"] != material["raw_context_sha256"]
    ):
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_RAW_CONTEXT_SIZE_INVALID")
    for name in ("feature_snapshot_id", "symbol", "timeframe"):
        _required_label(
            material[name],
            reason=f"TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_{name.upper()}_INVALID",
        )
    _required_label(
        material["p0d_artifact_record_id"],
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_ARTIFACT_RECORD_ID_INVALID",
    )
    _required_text(
        material["raw_context_cas_relative_path"],
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_CAS_RELATIVE_PATH_INVALID",
    )
    _required_positive_int(
        material["p0d_ledger_sequence"],
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_P0D_LEDGER_SEQUENCE_INVALID",
    )
    _required_positive_int(
        material["p0d_source_ledger_sequence"],
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SOURCE_LEDGER_SEQUENCE_INVALID",
    )
    material["p0f1_raw_context_binding_sha256"] = _sha256_json(material)
    return material


def _cross_binding(
    p0e: dict[str, Any],
    p0f1: dict[str, Any],
) -> dict[str, Any]:
    shared_names = (
        "feature_snapshot_id",
        "symbol",
        "timeframe",
        "p0d_ledger_sequence",
        "p0d_ledger_entry_sha256",
        "p0d_publication_identity_sha256",
        "p0d_source_ledger_sequence",
        "p0d_source_ledger_entry_sha256",
        "p0d_artifact_record_id",
        "p0d_artifact_binding_sha256",
        "p0d_artifact_serialization_sha256",
        "p0d_snapshot_generated_at",
        "p0d_ledger_recorded_at",
    )
    if any(p0e.get(name) != p0f1.get(name) for name in shared_names):
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SHARED_P0D_IDENTITY_MISMATCH")
    if not (
        p0e.get("trace_raw_context_sha256")
        == p0f1.get("raw_context_sha256")
        == p0f1.get("raw_context_cas_payload_sha256")
    ):
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_RAW_CONTEXT_SHA256_MISMATCH")

    candle_close = _parse_clock(
        p0f1.get("candle_close_time"),
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_CANDLE_CLOSE_INVALID",
    )
    capture_completed = _parse_clock(
        p0f1.get("raw_context_capture_completed_at"),
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_CAPTURE_COMPLETED_AT_INVALID",
    )
    snapshot_generated = _parse_clock(
        p0e.get("p0d_snapshot_generated_at"),
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SNAPSHOT_GENERATED_AT_INVALID",
    )
    ledger_recorded = _parse_clock(
        p0e.get("p0d_ledger_recorded_at"),
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_LEDGER_RECORDED_AT_INVALID",
    )
    decision_time = _parse_clock(
        p0e.get("trace_decision_time"),
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_TRACE_DECISION_TIME_INVALID",
    )
    if not (
        candle_close
        < capture_completed
        <= snapshot_generated
        <= ledger_recorded
        <= decision_time
    ):
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_PIT_CLOCK_ORDER_INVALID")

    material: dict[str, Any] = {
        "p0e_bridge_sha256": p0e["p0e_bridge_sha256"],
        "p0f1_receipt_sha256": p0f1["p0f1_receipt_sha256"],
        "trace_sha256": p0e["trace_sha256"],
        "raw_context_sha256": p0f1["raw_context_sha256"],
        "feature_snapshot_id": p0e["feature_snapshot_id"],
        "symbol": p0e["symbol"],
        "timeframe": p0e["timeframe"],
        "p0d_ledger_sequence": p0e["p0d_ledger_sequence"],
        "p0d_ledger_entry_sha256": p0e["p0d_ledger_entry_sha256"],
        "p0d_publication_identity_sha256": p0e["p0d_publication_identity_sha256"],
        "p0d_source_ledger_sequence": p0e["p0d_source_ledger_sequence"],
        "p0d_source_ledger_entry_sha256": p0e["p0d_source_ledger_entry_sha256"],
        "p0d_artifact_record_id": p0e["p0d_artifact_record_id"],
        "p0d_artifact_binding_sha256": p0e["p0d_artifact_binding_sha256"],
        "p0d_artifact_serialization_sha256": p0e["p0d_artifact_serialization_sha256"],
        "candle_close_time": p0f1["candle_close_time"],
        "raw_context_capture_completed_at": p0f1["raw_context_capture_completed_at"],
        "snapshot_generated_at": p0e["p0d_snapshot_generated_at"],
        "ledger_recorded_at": p0e["p0d_ledger_recorded_at"],
        "trace_decision_time": p0e["trace_decision_time"],
    }
    material["association_binding_sha256"] = _sha256_json(material)
    return material


def _build_material(
    bridge: dict[str, Any],
    raw_context: dict[str, Any],
) -> dict[str, Any]:
    _validate_upstream_contracts(bridge, raw_context)
    p0e = _p0e_binding(bridge)
    p0f1 = _p0f1_binding(raw_context)
    cross = _cross_binding(p0e, p0f1)
    material: dict[str, Any] = {
        "schema_version": TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SCHEMA_VERSION,
        "evidence_classification": (
            TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_EVIDENCE_CLASSIFICATION
        ),
        "downstream_status": TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_DOWNSTREAM_STATUS,
        "p0e_bridge_binding": p0e,
        "p0f1_raw_context_binding": p0f1,
        "cross_artifact_binding": cross,
        "association_limitations": list(TRACE_RAW_CONTEXT_ASSOCIATION_LIMITATIONS),
        _TRUE_FIELD: True,
        **{name: False for name in _FALSE_FIELDS},
    }
    material["receipt_sha256"] = _sha256_json(material)
    return material


def _validate_material(value: object) -> dict[str, Any]:
    receipt = _exact_dict(
        value,
        _ROOT_FIELDS,
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_FIELDS_INVALID",
    )
    p0e = _exact_dict(
        receipt["p0e_bridge_binding"],
        _P0E_BINDING_FIELDS,
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_P0E_BINDING_FIELDS_INVALID",
    )
    p0f1 = _exact_dict(
        receipt["p0f1_raw_context_binding"],
        _P0F1_BINDING_FIELDS,
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_P0F1_BINDING_FIELDS_INVALID",
    )
    cross = _exact_dict(
        receipt["cross_artifact_binding"],
        _CROSS_BINDING_FIELDS,
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_CROSS_BINDING_FIELDS_INVALID",
    )
    if (
        receipt["schema_version"]
        != TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SCHEMA_VERSION
        or receipt["evidence_classification"]
        != TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_EVIDENCE_CLASSIFICATION
        or receipt["downstream_status"]
        != TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_DOWNSTREAM_STATUS
        or receipt["association_limitations"]
        != list(TRACE_RAW_CONTEXT_ASSOCIATION_LIMITATIONS)
        or receipt[_TRUE_FIELD] is not True
        or any(receipt[name] is not False for name in _FALSE_FIELDS)
    ):
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_CONSTANT_OR_FLAG_MISMATCH")
    for mapping in (p0e, p0f1, cross):
        _validate_named_hashes(mapping)

    for mapping, hash_name in (
        (p0e, "p0e_bridge_binding_sha256"),
        (p0f1, "p0f1_raw_context_binding_sha256"),
    ):
        binding_material = {
            key: item for key, item in mapping.items() if key != hash_name
        }
        if mapping[hash_name] != _sha256_json(binding_material):
            _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_NESTED_SHA256_MISMATCH")

    expected_cross = _cross_binding(p0e, p0f1)
    if cross != expected_cross:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_CROSS_BINDING_MISMATCH")
    receipt_material = {
        key: item for key, item in receipt.items() if key != "receipt_sha256"
    }
    if _required_sha256(
        receipt["receipt_sha256"],
        reason="TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_RECEIPT_SHA256_INVALID",
    ) != _sha256_json(receipt_material):
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_RECEIPT_SHA256_MISMATCH")
    return receipt


def _fresh_expected(
    *,
    bridge_artifact: FeatureResolutionPublicationBridgeArtifactV4,
    raw_context_artifact: RawContextCasReceiptArtifactV4,
) -> dict[str, Any]:
    bridge, raw_context = _read_upstreams(bridge_artifact, raw_context_artifact)
    return _build_material(bridge, raw_context)


@dataclass(frozen=True, slots=True)
class TraceRawContextAssociationReceiptArtifactV4:
    """Factory-only P0-F2 receipt with fresh upstream checks on access."""

    schema_version: str
    receipt_sha256: str
    association_json: str = field(repr=False)
    _bridge_artifact: FeatureResolutionPublicationBridgeArtifactV4 = field(
        repr=False,
        compare=False,
    )
    _raw_context_artifact: RawContextCasReceiptArtifactV4 = field(
        repr=False,
        compare=False,
    )
    _construction_token: object = field(repr=False, compare=False)
    trace_to_raw_context_cas_association_verified: bool = field(
        default=True,
        init=False,
    )
    upstream_payload_construction_independently_attested: bool = field(
        default=False,
        init=False,
    )
    trace_association_source_authentication_verified: bool = field(
        default=False,
        init=False,
    )
    resolver_branch_capture_authenticated: bool = field(default=False, init=False)
    producer_identity_independently_authenticated: bool = field(
        default=False,
        init=False,
    )
    source_receipts_authenticated: bool = field(default=False, init=False)
    source_scope_complete: bool = field(default=False, init=False)
    per_field_receipts_complete: bool = field(default=False, init=False)
    per_field_available_at_complete: bool = field(default=False, init=False)
    resolved_source_mapping_verified: bool = field(default=False, init=False)
    negative_evidence_authenticated: bool = field(default=False, init=False)
    feature_snapshot_published: bool = field(default=False, init=False)
    feature_publication_receipt_emitted: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_FACTORY_REQUIRED")
        parsed = _validate_material(_parse_json(self.association_json))
        expected = _fresh_expected(
            bridge_artifact=self._bridge_artifact,
            raw_context_artifact=self._raw_context_artifact,
        )
        if (
            self.schema_version
            != TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SCHEMA_VERSION
            or self.receipt_sha256 != expected["receipt_sha256"]
            or parsed != expected
            or self.association_json != _canonical_json(expected)
            or self.trace_to_raw_context_cas_association_verified is not True
            or any(getattr(self, name) is not False for name in _FALSE_FIELDS)
        ):
            _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_ARTIFACT_BINDING_MISMATCH")

    @property
    def receipt(self) -> dict[str, Any]:
        """Return a private mapping only after fresh P0-E and P0-F1 reads."""

        parsed = _validate_material(_parse_json(self.association_json))
        expected = _fresh_expected(
            bridge_artifact=self._bridge_artifact,
            raw_context_artifact=self._raw_context_artifact,
        )
        if parsed != expected:
            _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_UPSTREAM_CHANGED")
        return cast(dict[str, Any], json.loads(_canonical_json(parsed)))


def build_trace_raw_context_association_receipt_v4(
    *,
    bridge_artifact: FeatureResolutionPublicationBridgeArtifactV4,
    raw_context_artifact: RawContextCasReceiptArtifactV4,
) -> TraceRawContextAssociationReceiptArtifactV4:
    """Bind one exact P0-E trace hash to one exact freshly verified P0-F1 CAS."""

    first_bridge, first_raw_context = _read_upstreams(
        bridge_artifact,
        raw_context_artifact,
    )
    first = _build_material(first_bridge, first_raw_context)
    final_bridge, final_raw_context = _read_upstreams(
        bridge_artifact,
        raw_context_artifact,
    )
    if final_bridge != first_bridge or final_raw_context != first_raw_context:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_UPSTREAM_CHANGED_DURING_BIND")
    final = _build_material(final_bridge, final_raw_context)
    if final != first:
        _fail("TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_MATERIAL_CHANGED_DURING_BIND")
    canonical = _canonical_json(final)
    return TraceRawContextAssociationReceiptArtifactV4(
        schema_version=TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SCHEMA_VERSION,
        receipt_sha256=cast(str, final["receipt_sha256"]),
        association_json=canonical,
        _bridge_artifact=bridge_artifact,
        _raw_context_artifact=raw_context_artifact,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "MAX_TRACE_RAW_CONTEXT_ASSOCIATION_JSON_DEPTH",
    "MAX_TRACE_RAW_CONTEXT_ASSOCIATION_JSON_NODES",
    "MAX_TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_BYTES",
    "TRACE_RAW_CONTEXT_ASSOCIATION_LIMITATIONS",
    "TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_DOWNSTREAM_STATUS",
    "TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_EVIDENCE_CLASSIFICATION",
    "TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SCHEMA_VERSION",
    "TraceRawContextAssociationReceiptArtifactV4",
    "TraceRawContextAssociationReceiptV4ValidationError",
    "build_trace_raw_context_association_receipt_v4",
]
