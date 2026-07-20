"""Audit-only immutable raw-context receipt associated with one P0-D entry.

P0-F1 closes one deliberately narrow gap: producer-created immutable canonical
resolver-context payload bytes can be wrapped in exact canonical capture bytes,
durably pinned in the existing atomic immutable payload store, and associated
with one freshly revalidated P0-D feature-artifact ledger entry.
The receipt separates the closed candle's economic time from the resolver's
observation, availability, and capture-completion clocks.  It never uses the
ambiguous v3 ``event_time`` name.

This is a tool-only, unwired evidence primitive.  Producer code/configuration
hashes and context clocks are declarations bound into immutable bytes; they
are not authenticated per-field source receipts.  The boundary cannot attest
how the producer assembled its immutable payload bytes before supplying them.
The trace, resolver branch, feature publication, trainer, prediction, paper,
and live paths remain unauthorized.  A later P0-F2 boundary must bind this
receipt to one exact trace and independently preserve those limitations.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, cast

from v2.backend.app.services.native_trainer.feature_snapshot_publication_ledger_v4 import (
    FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_EVIDENCE_CLASSIFICATION,
    FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_NAMESPACE,
    FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_SCHEMA_VERSION,
    FeatureSnapshotPublicationLedgerEntryV4,
    FeatureSnapshotPublicationLedgerV4,
    FeatureSnapshotPublicationLedgerV4Error,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    SOURCE_PAYLOAD_STORE_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)

RAW_CONTEXT_CAPTURE_V4_SCHEMA_VERSION = "trainer_resolver_raw_context_capture_v4"
RAW_CONTEXT_LOCATOR_V4_SCHEMA_VERSION = "trainer_raw_context_typed_locator_v4"
RAW_CONTEXT_SNAPSHOT_IDENTITY_V4_SCHEMA_VERSION = (
    "trainer_raw_context_snapshot_identity_v4"
)
RAW_CONTEXT_TEMPORAL_IDENTITY_V4_SCHEMA_VERSION = (
    "trainer_raw_context_temporal_identity_v4"
)
RAW_CONTEXT_PRODUCER_IDENTITY_V4_SCHEMA_VERSION = (
    "trainer_raw_context_producer_identity_v4"
)
RAW_CONTEXT_CAS_BINDING_V4_SCHEMA_VERSION = "trainer_raw_context_cas_binding_v4"
RAW_CONTEXT_P0D_ASSOCIATION_V4_SCHEMA_VERSION = (
    "trainer_raw_context_p0d_ledger_association_v4"
)
RAW_CONTEXT_CAS_RECEIPT_V4_SCHEMA_VERSION = "trainer_raw_context_cas_receipt_v4"

RAW_CONTEXT_NAMESPACE_TYPE = "TRAINER_RESOLVER_RAW_CONTEXT"
RAW_CONTEXT_NAMESPACE = "trainer-feature-resolver-raw-context-v4"
RAW_CONTEXT_LOCATOR_TYPE = "SNAPSHOT_SYMBOL_TIMEFRAME_IDENTITY_SHA256"
RAW_CONTEXT_FINALITY_TYPE = "CLOSED_CANDLE"
RAW_CONTEXT_CAS_LOCATOR_TYPE = "IMMUTABLE_SHA256_RELATIVE_PATH"
RAW_CONTEXT_P0D_COMMIT_CONTRACT = (
    "P0D_HASH_CHAIN_FSYNCED_HEAD_PREFIX_AND_LEDGER_OWNED_CAS_V4"
)
RAW_CONTEXT_CAS_RECEIPT_V4_EVIDENCE_CLASSIFICATION = (
    "AUDIT_ONLY_IMMUTABLE_RAW_CONTEXT_CAS_WITH_FRESH_P0D_ASSOCIATION"
)
RAW_CONTEXT_CAS_RECEIPT_V4_DOWNSTREAM_STATUS = (
    "NO_TRACE_OR_SOURCE_AUTHENTICATION_PUBLICATION_ADMISSION_OR_EXECUTION_AUTHORIZATION"
)

# Resource-integrity ceilings only.  They select no market, feature, sample,
# threshold, leverage, or risk outcome.
MAX_RAW_CONTEXT_V4_BYTES = 16 * 1024 * 1024
MAX_RAW_CONTEXT_RECEIPT_V4_BYTES = 256 * 1024
MAX_RAW_CONTEXT_JSON_DEPTH = 64
MAX_RAW_CONTEXT_JSON_NODES = 1_000_000
MAX_LABEL_BYTES = 256

RAW_CONTEXT_AUTHENTICATION_LIMITATIONS = (
    "UPSTREAM_IMMUTABLE_PAYLOAD_CONSTRUCTION_NOT_INDEPENDENTLY_ATTESTED",
    "DECLARED_PRODUCER_IDENTITY_NOT_INDEPENDENTLY_AUTHENTICATED",
    "DECLARED_RAW_CONTEXT_CLOCKS_NOT_PER_FIELD_SOURCE_RECEIPTS",
    "TRACE_RAW_CONTEXT_HASH_NOT_BOUND_IN_P0F1",
    "RESOLVER_BRANCH_CAPTURE_NOT_AUTHENTICATED",
    "PER_FIELD_SOURCE_RECEIPTS_ABSENT",
    "PER_FIELD_AVAILABLE_AT_EVIDENCE_ABSENT",
    "NEGATIVE_SOURCE_EVIDENCE_NOT_AUTHENTICATED",
    "FEATURE_PUBLICATION_RECEIPT_ABSENT",
    "CONSUMER_ADMISSION_RECEIPT_ABSENT",
)

_TRUE_FIELDS = (
    "audit_receipt_only",
    "exact_canonical_raw_context_bytes_pinned",
    "raw_context_cas_integrity_revalidated",
    "p0d_committed_head_and_owned_cas_freshly_revalidated",
    "snapshot_and_closed_candle_identity_bound",
    "declared_producer_code_and_configuration_identity_bound",
)
_FALSE_FIELDS = (
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

_RAW_CONTEXT_FIELDS = frozenset(
    {
        "schema_version",
        "context_locator",
        "snapshot_identity",
        "temporal_identity",
        "producer_identity",
        "payload",
        "document_binding_sha256",
    }
)
_LOCATOR_FIELDS = frozenset(
    {
        "schema_version",
        "namespace_type",
        "namespace",
        "locator_type",
        "locator",
        "locator_sha256",
    }
)
_SNAPSHOT_FIELDS = frozenset(
    {"schema_version", "feature_snapshot_id", "symbol", "timeframe"}
)
_TEMPORAL_FIELDS = frozenset(
    {
        "schema_version",
        "candle_open_time",
        "candle_close_time",
        "economic_event_time",
        "raw_context_observed_at",
        "raw_context_available_at",
        "raw_context_capture_completed_at",
        "finality_type",
        "candle_final",
    }
)
_PRODUCER_FIELDS = frozenset(
    {
        "schema_version",
        "producer_id",
        "producer_version",
        "producer_code_sha256",
        "producer_config_sha256",
        "producer_identity_sha256",
    }
)
_CAS_FIELDS = frozenset(
    {
        "schema_version",
        "store_schema_version",
        "address_schema_version",
        "logical_namespace",
        "locator_type",
        "store_root",
        "store_root_sha256",
        "relative_path",
        "payload_sha256",
        "payload_byte_count",
        "canonical_json_verified",
        "cas_binding_sha256",
    }
)
_ASSOCIATION_FIELDS = frozenset(
    {
        "schema_version",
        "ledger_schema_version",
        "ledger_namespace",
        "ledger_root",
        "ledger_root_sha256",
        "ledger_sequence",
        "ledger_entry_sha256",
        "ledger_entry_json_sha256",
        "publication_identity_sha256",
        "publication_replay_identity_sha256",
        "source_ledger_sequence",
        "source_ledger_entry_sha256",
        "artifact_record_id",
        "artifact_binding_sha256",
        "artifact_serialization_sha256",
        "feature_snapshot_id",
        "symbol",
        "timeframe",
        "snapshot_generated_at",
        "ledger_recorded_at",
        "durable_atomic_commit_contract",
        "committed_head_and_owned_cas_fresh_read_verified",
        "association_sha256",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "raw_context_sha256",
        "raw_context_byte_count",
        "raw_context_document_binding_sha256",
        "context_locator",
        "snapshot_identity",
        "temporal_identity",
        "producer_identity",
        "raw_context_cas_binding",
        "p0d_ledger_association",
        "authentication_limitations",
        *_TRUE_FIELDS,
        *_FALSE_FIELDS,
        "receipt_sha256",
    }
)

_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,255}$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_UPSTREAM_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3,6}Z$",
    re.ASCII,
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CONSTRUCTION_TOKEN = object()


class RawContextCasReceiptV4ValidationError(ValueError):
    """Raw-context bytes, CAS state, or durable association fail closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise RawContextCasReceiptV4ValidationError(*reasons) from None


def _valid_label(value: object) -> bool:
    return (
        type(value) is str
        and value.isascii()
        and len(value.encode("ascii")) <= MAX_LABEL_BYTES
        and _LABEL_RE.fullmatch(value) is not None
    )


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _required_label(value: object, *, reason: str) -> str:
    if not _valid_label(value):
        _fail(reason)
    return cast(str, value)


def _required_sha256(value: object, *, reason: str) -> str:
    if not _valid_sha256(value):
        _fail(reason)
    return cast(str, value)


@dataclass(slots=True)
class _JsonPreflightBudget:
    remaining_bytes: int
    remaining_nodes: int = MAX_RAW_CONTEXT_JSON_NODES

    def consume_bytes(self, byte_count: int, *, reason: str) -> None:
        if byte_count < 0 or byte_count > self.remaining_bytes:
            _fail(reason)
        self.remaining_bytes -= byte_count

    def consume_node(self) -> None:
        if self.remaining_nodes <= 0:
            _fail("RAW_CONTEXT_V4_JSON_NODE_LIMIT_EXCEEDED")
        self.remaining_nodes -= 1


def _consume_json_string(
    value: str,
    *,
    budget: _JsonPreflightBudget,
    reason: str,
) -> None:
    """Consume the exact ensure-ASCII JSON width without building an escape copy."""

    budget.consume_bytes(2, reason=reason)
    if len(value) > budget.remaining_bytes:
        _fail(reason)
    if (
        value.isascii()
        and value.isprintable()
        and '"' not in value
        and "\\" not in value
    ):
        budget.consume_bytes(len(value), reason=reason)
        return
    for character in value:
        codepoint = ord(character)
        if character in {'"', "\\"} or codepoint in {8, 9, 10, 12, 13}:
            encoded_width = 2
        elif codepoint < 0x20:
            encoded_width = 6
        elif codepoint <= 0x7E:
            encoded_width = 1
        elif codepoint <= 0xFFFF:
            encoded_width = 6
        else:
            encoded_width = 12
        budget.consume_bytes(encoded_width, reason=reason)


def _consume_json_integer(value: int, *, budget: _JsonPreflightBudget) -> None:
    """Reject a huge integer by bit length before bounded decimal conversion."""

    bit_count = value.bit_length()
    if bit_count == 0:
        minimum_width = 1
    else:
        # 30102 / 100000 is below log10(2), so this is a safe lower
        # bound.  Values that could exceed the remaining byte budget are
        # rejected without constructing a decimal string.
        minimum_digits = ((bit_count - 1) * 30_102) // 100_000 + 1
        minimum_width = minimum_digits + int(value < 0)
    if minimum_width > budget.remaining_bytes:
        _fail("RAW_CONTEXT_V4_JSON_INTEGER_SIZE_LIMIT_EXCEEDED")
    try:
        decimal = str(value)
    except (ValueError, MemoryError):
        _fail("RAW_CONTEXT_V4_JSON_INTEGER_SIZE_LIMIT_EXCEEDED")
    budget.consume_bytes(
        len(decimal),
        reason="RAW_CONTEXT_V4_JSON_INTEGER_SIZE_LIMIT_EXCEEDED",
    )


def _preflight_json_value(
    value: object,
    *,
    budget: _JsonPreflightBudget,
    depth: int = 0,
) -> None:
    budget.consume_node()
    if depth > MAX_RAW_CONTEXT_JSON_DEPTH:
        _fail("RAW_CONTEXT_V4_JSON_DEPTH_LIMIT_EXCEEDED")
    if value is None:
        budget.consume_bytes(4, reason="RAW_CONTEXT_V4_SIZE_LIMIT_EXCEEDED")
        return
    if type(value) is bool:
        budget.consume_bytes(
            4 if value else 5,
            reason="RAW_CONTEXT_V4_SIZE_LIMIT_EXCEEDED",
        )
        return
    if type(value) is int:
        _consume_json_integer(value, budget=budget)
        return
    if type(value) is float:
        float_value = value
        if not math.isfinite(float_value):
            _fail("RAW_CONTEXT_V4_JSON_NUMBER_NOT_FINITE")
        budget.consume_bytes(
            len(repr(float_value)),
            reason="RAW_CONTEXT_V4_SIZE_LIMIT_EXCEEDED",
        )
        return
    if type(value) is str:
        _consume_json_string(
            value,
            budget=budget,
            reason="RAW_CONTEXT_V4_JSON_STRING_SIZE_LIMIT_EXCEEDED",
        )
        return
    if type(value) is list:
        list_source = cast(list[object], value)
        item_count = len(list_source)
        if item_count > budget.remaining_nodes:
            _fail("RAW_CONTEXT_V4_JSON_NODE_LIMIT_EXCEEDED")
        minimum_width = 2 if item_count == 0 else 2 * item_count + 1
        if minimum_width > budget.remaining_bytes:
            _fail("RAW_CONTEXT_V4_JSON_CONTAINER_SIZE_LIMIT_EXCEEDED")
        budget.consume_bytes(2, reason="RAW_CONTEXT_V4_SIZE_LIMIT_EXCEEDED")
        for index in range(item_count):
            if index:
                budget.consume_bytes(1, reason="RAW_CONTEXT_V4_SIZE_LIMIT_EXCEEDED")
            try:
                item = list_source[index]
            except IndexError:
                _fail("RAW_CONTEXT_V4_MUTATED_DURING_PREFLIGHT")
            _preflight_json_value(item, budget=budget, depth=depth + 1)
        if len(list_source) != item_count:
            _fail("RAW_CONTEXT_V4_MUTATED_DURING_PREFLIGHT")
        return
    if type(value) is dict:
        dict_source = cast(dict[object, object], value)
        item_count = len(dict_source)
        if item_count > budget.remaining_nodes:
            _fail("RAW_CONTEXT_V4_JSON_NODE_LIMIT_EXCEEDED")
        minimum_width = 2 if item_count == 0 else 5 * item_count + 1
        if minimum_width > budget.remaining_bytes:
            _fail("RAW_CONTEXT_V4_JSON_CONTAINER_SIZE_LIMIT_EXCEEDED")
        budget.consume_bytes(2, reason="RAW_CONTEXT_V4_SIZE_LIMIT_EXCEEDED")
        iterator = iter(dict_source.items())
        for index in range(item_count):
            try:
                key, item = next(iterator)
            except (RuntimeError, StopIteration):
                _fail("RAW_CONTEXT_V4_MUTATED_DURING_PREFLIGHT")
            if type(key) is not str:
                _fail("RAW_CONTEXT_V4_JSON_OBJECT_KEY_INVALID")
            if index:
                budget.consume_bytes(1, reason="RAW_CONTEXT_V4_SIZE_LIMIT_EXCEEDED")
            _consume_json_string(
                key,
                budget=budget,
                reason="RAW_CONTEXT_V4_JSON_KEY_SIZE_LIMIT_EXCEEDED",
            )
            budget.consume_bytes(1, reason="RAW_CONTEXT_V4_SIZE_LIMIT_EXCEEDED")
            _preflight_json_value(item, budget=budget, depth=depth + 1)
        try:
            next(iterator)
        except StopIteration:
            pass
        except RuntimeError:
            _fail("RAW_CONTEXT_V4_MUTATED_DURING_PREFLIGHT")
        else:
            _fail("RAW_CONTEXT_V4_MUTATED_DURING_PREFLIGHT")
        if len(dict_source) != item_count:
            _fail("RAW_CONTEXT_V4_MUTATED_DURING_PREFLIGHT")
        return
    _fail("RAW_CONTEXT_V4_NOT_STRICT_JSON")


def _preflight_canonical_json(value: object, *, max_bytes: int) -> int:
    if type(max_bytes) is not int or max_bytes <= 0:
        _fail("RAW_CONTEXT_V4_SIZE_LIMIT_EXCEEDED")
    budget = _JsonPreflightBudget(remaining_bytes=max_bytes)
    _preflight_json_value(value, budget=budget)
    return max_bytes - budget.remaining_bytes


def _strict_json_snapshot(
    value: object,
    *,
    depth: int = 0,
    budget: list[int] | None = None,
) -> Any:
    if budget is None:
        budget = [MAX_RAW_CONTEXT_JSON_NODES]
    budget[0] -= 1
    if budget[0] < 0:
        _fail("RAW_CONTEXT_V4_JSON_NODE_LIMIT_EXCEEDED")
    if depth > MAX_RAW_CONTEXT_JSON_DEPTH:
        _fail("RAW_CONTEXT_V4_JSON_DEPTH_LIMIT_EXCEEDED")
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _fail("RAW_CONTEXT_V4_JSON_NUMBER_NOT_FINITE")
        return value
    if type(value) is list:
        list_source = cast(list[object], value)
        item_count = len(list_source)
        if item_count > budget[0]:
            _fail("RAW_CONTEXT_V4_JSON_NODE_LIMIT_EXCEEDED")
        copied_list: list[Any] = []
        for index in range(item_count):
            try:
                item = list_source[index]
            except IndexError:
                _fail("RAW_CONTEXT_V4_MUTATED_DURING_SNAPSHOT")
            copied_list.append(
                _strict_json_snapshot(item, depth=depth + 1, budget=budget)
            )
        if len(list_source) != item_count:
            _fail("RAW_CONTEXT_V4_MUTATED_DURING_SNAPSHOT")
        return copied_list
    if type(value) is dict:
        dict_source = cast(dict[object, object], value)
        item_count = len(dict_source)
        if item_count > budget[0]:
            _fail("RAW_CONTEXT_V4_JSON_NODE_LIMIT_EXCEEDED")
        copied: dict[str, Any] = {}
        iterator = iter(dict_source.items())
        for _ in range(item_count):
            try:
                key, item = next(iterator)
            except (RuntimeError, StopIteration):
                _fail("RAW_CONTEXT_V4_MUTATED_DURING_SNAPSHOT")
            if type(key) is not str:
                _fail("RAW_CONTEXT_V4_JSON_OBJECT_KEY_INVALID")
            copied[key] = _strict_json_snapshot(
                item,
                depth=depth + 1,
                budget=budget,
            )
        try:
            next(iterator)
        except StopIteration:
            pass
        except RuntimeError:
            _fail("RAW_CONTEXT_V4_MUTATED_DURING_SNAPSHOT")
        else:
            _fail("RAW_CONTEXT_V4_MUTATED_DURING_SNAPSHOT")
        if len(dict_source) != item_count:
            _fail("RAW_CONTEXT_V4_MUTATED_DURING_SNAPSHOT")
        return copied
    _fail("RAW_CONTEXT_V4_NOT_STRICT_JSON")


def _canonical_json(value: object, *, max_bytes: int) -> str:
    expected_byte_count = _preflight_canonical_json(value, max_bytes=max_bytes)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        raw = encoded.encode("ascii", errors="strict")
    except (TypeError, ValueError, OverflowError, UnicodeEncodeError, RecursionError):
        _fail("RAW_CONTEXT_V4_NOT_STRICT_JSON")
    if not raw or len(raw) != expected_byte_count:
        _fail("RAW_CONTEXT_V4_PREFLIGHT_SERIALIZATION_SIZE_MISMATCH")
    return encoded


def _sha256_json(
    value: object, *, max_bytes: int = MAX_RAW_CONTEXT_RECEIPT_V4_BYTES
) -> str:
    return hashlib.sha256(
        _canonical_json(value, max_bytes=max_bytes).encode("ascii")
    ).hexdigest()


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("RAW_CONTEXT_V4_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _parse_json_bytes(value: object) -> dict[str, Any]:
    if type(value) is not bytes:
        _fail("RAW_CONTEXT_V4_EXACT_BYTES_REQUIRED")
    raw = value
    if not raw or len(raw) > MAX_RAW_CONTEXT_V4_BYTES:
        _fail("RAW_CONTEXT_V4_BYTES_SIZE_INVALID")
    try:
        text = raw.decode("ascii", errors="strict")
        parsed = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=lambda _: _fail("RAW_CONTEXT_V4_JSON_CONSTANT_FORBIDDEN"),
        )
    except RawContextCasReceiptV4ValidationError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
    ):
        _fail("RAW_CONTEXT_V4_JSON_INVALID")
    if type(parsed) is not dict:
        _fail("RAW_CONTEXT_V4_NOT_EXACT_OBJECT")
    copied = cast(dict[str, Any], _strict_json_snapshot(parsed))
    if (
        _canonical_json(copied, max_bytes=MAX_RAW_CONTEXT_V4_BYTES).encode("ascii")
        != raw
    ):
        _fail("RAW_CONTEXT_V4_BYTES_NOT_EXACT_CANONICAL_JSON")
    return copied


def _parse_exact_canonical_payload_bytes(value: object) -> dict[str, Any]:
    """Parse one immutable canonical JSON object with no caller-owned aliases."""

    if type(value) is not bytes:
        _fail("RAW_CONTEXT_V4_IMMUTABLE_PAYLOAD_BYTES_REQUIRED")
    raw = value
    if not raw or len(raw) > MAX_RAW_CONTEXT_V4_BYTES:
        _fail("RAW_CONTEXT_V4_PAYLOAD_BYTES_SIZE_INVALID")
    try:
        text = raw.decode("ascii", errors="strict")
        parsed = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=lambda _: _fail("RAW_CONTEXT_V4_JSON_CONSTANT_FORBIDDEN"),
        )
    except RawContextCasReceiptV4ValidationError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        OverflowError,
        RecursionError,
    ):
        _fail("RAW_CONTEXT_V4_PAYLOAD_JSON_INVALID")
    if type(parsed) is not dict:
        _fail("RAW_CONTEXT_V4_PAYLOAD_NOT_EXACT_OBJECT")

    # ``parsed`` and every nested container are parser-owned.  The immutable
    # caller bytes cannot change during or after parsing, unlike a recursive
    # copy of a caller-owned dict/list graph.  Preflight still enforces the
    # resource ceilings before the strict copy or canonical serialization.
    _preflight_canonical_json(parsed, max_bytes=MAX_RAW_CONTEXT_V4_BYTES)
    copied = cast(dict[str, Any], _strict_json_snapshot(parsed))
    if (
        _canonical_json(copied, max_bytes=MAX_RAW_CONTEXT_V4_BYTES).encode("ascii")
        != raw
    ):
        _fail("RAW_CONTEXT_V4_PAYLOAD_BYTES_NOT_EXACT_CANONICAL_JSON")
    return copied


def _parse_receipt_json(value: object) -> dict[str, Any]:
    if type(value) is not str or not value:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_JSON_INVALID")
    try:
        raw = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_JSON_INVALID")
    if len(raw) > MAX_RAW_CONTEXT_RECEIPT_V4_BYTES:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_JSON_INVALID")
    try:
        parsed = json.loads(
            value,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=lambda _: _fail("RAW_CONTEXT_V4_JSON_CONSTANT_FORBIDDEN"),
        )
    except RawContextCasReceiptV4ValidationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError, OverflowError, RecursionError):
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_JSON_INVALID")
    if type(parsed) is not dict:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_NOT_EXACT_OBJECT")
    mapping = cast(dict[str, Any], parsed)
    if _canonical_json(mapping, max_bytes=MAX_RAW_CONTEXT_RECEIPT_V4_BYTES) != value:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_JSON_NOT_CANONICAL")
    return mapping


def _exact_dict(
    value: object, fields: frozenset[str], *, reason: str
) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(reason)
    mapping = cast(dict[object, object], value)
    if any(type(key) is not str for key in mapping) or frozenset(mapping) != fields:
        _fail(reason)
    return cast(dict[str, Any], dict(mapping))


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


def _parse_upstream_clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or _UPSTREAM_CLOCK_RE.fullmatch(value) is None:
        _fail(reason)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00").astimezone(UTC)
    except ValueError:
        _fail(reason)
    if parsed < _EPOCH:
        _fail(reason)
    return parsed


def _clock6(value: datetime) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _locator(snapshot: dict[str, Any]) -> dict[str, object]:
    locator_material = {
        "schema_version": RAW_CONTEXT_LOCATOR_V4_SCHEMA_VERSION,
        "namespace_type": RAW_CONTEXT_NAMESPACE_TYPE,
        "namespace": RAW_CONTEXT_NAMESPACE,
        "locator_type": RAW_CONTEXT_LOCATOR_TYPE,
        "feature_snapshot_id": snapshot["feature_snapshot_id"],
        "symbol": snapshot["symbol"],
        "timeframe": snapshot["timeframe"],
    }
    digest = _sha256_json(locator_material)
    material: dict[str, object] = {
        "schema_version": RAW_CONTEXT_LOCATOR_V4_SCHEMA_VERSION,
        "namespace_type": RAW_CONTEXT_NAMESPACE_TYPE,
        "namespace": RAW_CONTEXT_NAMESPACE,
        "locator_type": RAW_CONTEXT_LOCATOR_TYPE,
        "locator": f"rawctx_v4_{digest}",
    }
    material["locator_sha256"] = _sha256_json(material)
    return material


def _validate_temporal(value: object) -> dict[str, Any]:
    temporal = _exact_dict(
        value,
        _TEMPORAL_FIELDS,
        reason="RAW_CONTEXT_V4_TEMPORAL_FIELDS_INVALID",
    )
    if (
        temporal["schema_version"] != RAW_CONTEXT_TEMPORAL_IDENTITY_V4_SCHEMA_VERSION
        or temporal["finality_type"] != RAW_CONTEXT_FINALITY_TYPE
        or temporal["candle_final"] is not True
    ):
        _fail("RAW_CONTEXT_V4_CANDLE_NOT_FINAL")
    clocks = {
        name: _parse_clock(
            temporal[name],
            reason=f"RAW_CONTEXT_V4_{name.upper()}_INVALID",
        )
        for name in (
            "candle_open_time",
            "candle_close_time",
            "economic_event_time",
            "raw_context_observed_at",
            "raw_context_available_at",
            "raw_context_capture_completed_at",
        )
    }
    if clocks["candle_open_time"] >= clocks["candle_close_time"]:
        _fail("RAW_CONTEXT_V4_CANDLE_CLOCK_ORDER_INVALID")
    if clocks["economic_event_time"] != clocks["candle_close_time"]:
        _fail("RAW_CONTEXT_V4_ECONOMIC_EVENT_NOT_CANDLE_CLOSE")
    if not (
        clocks["candle_close_time"]
        <= clocks["raw_context_observed_at"]
        <= clocks["raw_context_available_at"]
        <= clocks["raw_context_capture_completed_at"]
    ):
        _fail("RAW_CONTEXT_V4_CAPTURE_CLOCK_ORDER_INVALID")
    return temporal


def _validate_raw_context_document(value: object) -> dict[str, Any]:
    document = _exact_dict(
        value,
        _RAW_CONTEXT_FIELDS,
        reason="RAW_CONTEXT_V4_FIELDS_INVALID",
    )
    locator = _exact_dict(
        document["context_locator"],
        _LOCATOR_FIELDS,
        reason="RAW_CONTEXT_V4_LOCATOR_FIELDS_INVALID",
    )
    snapshot = _exact_dict(
        document["snapshot_identity"],
        _SNAPSHOT_FIELDS,
        reason="RAW_CONTEXT_V4_SNAPSHOT_FIELDS_INVALID",
    )
    temporal = _validate_temporal(document["temporal_identity"])
    producer = _exact_dict(
        document["producer_identity"],
        _PRODUCER_FIELDS,
        reason="RAW_CONTEXT_V4_PRODUCER_FIELDS_INVALID",
    )
    if document["schema_version"] != RAW_CONTEXT_CAPTURE_V4_SCHEMA_VERSION:
        _fail("RAW_CONTEXT_V4_SCHEMA_VERSION_MISMATCH")
    if snapshot["schema_version"] != RAW_CONTEXT_SNAPSHOT_IDENTITY_V4_SCHEMA_VERSION:
        _fail("RAW_CONTEXT_V4_SNAPSHOT_SCHEMA_MISMATCH")
    for name in ("feature_snapshot_id", "symbol", "timeframe"):
        _required_label(snapshot[name], reason=f"RAW_CONTEXT_V4_{name.upper()}_INVALID")
    expected_locator = _locator(snapshot)
    if locator != expected_locator:
        _fail("RAW_CONTEXT_V4_NAMESPACE_OR_LOCATOR_MISMATCH")
    if producer["schema_version"] != RAW_CONTEXT_PRODUCER_IDENTITY_V4_SCHEMA_VERSION:
        _fail("RAW_CONTEXT_V4_PRODUCER_SCHEMA_MISMATCH")
    for name in ("producer_id", "producer_version"):
        _required_label(producer[name], reason=f"RAW_CONTEXT_V4_{name.upper()}_INVALID")
    for name in ("producer_code_sha256", "producer_config_sha256"):
        _required_sha256(
            producer[name], reason=f"RAW_CONTEXT_V4_{name.upper()}_INVALID"
        )
    producer_material = {
        key: item for key, item in producer.items() if key != "producer_identity_sha256"
    }
    if not _valid_sha256(producer["producer_identity_sha256"]) or producer[
        "producer_identity_sha256"
    ] != _sha256_json(producer_material):
        _fail("RAW_CONTEXT_V4_PRODUCER_IDENTITY_SHA256_MISMATCH")
    if type(document["payload"]) is not dict:
        _fail("RAW_CONTEXT_V4_PAYLOAD_NOT_EXACT_OBJECT")
    _strict_json_snapshot(document["payload"])
    normalized = {
        **document,
        "context_locator": locator,
        "snapshot_identity": snapshot,
        "temporal_identity": temporal,
        "producer_identity": producer,
    }
    binding_material = {
        key: item
        for key, item in normalized.items()
        if key != "document_binding_sha256"
    }
    if not _valid_sha256(document["document_binding_sha256"]) or document[
        "document_binding_sha256"
    ] != _sha256_json(binding_material, max_bytes=MAX_RAW_CONTEXT_V4_BYTES):
        _fail("RAW_CONTEXT_V4_DOCUMENT_BINDING_SHA256_MISMATCH")
    return normalized


def canonical_raw_context_bytes_v4(
    *,
    feature_snapshot_id: str,
    symbol: str,
    timeframe: str,
    candle_open_time: str,
    candle_close_time: str,
    economic_event_time: str,
    raw_context_observed_at: str,
    raw_context_available_at: str,
    raw_context_capture_completed_at: str,
    producer_id: str,
    producer_version: str,
    producer_code_sha256: str,
    producer_config_sha256: str,
    payload_json_bytes: object,
) -> bytes:
    """Wrap one immutable canonical JSON-object payload in capture bytes."""

    # Mutable object graphs cannot be copied atomically without a producer-held
    # synchronization/version protocol: same-width concurrent changes can make
    # a recursive copy represent no point-in-time state.  Exact ``bytes`` are
    # therefore the evidence boundary; parsing creates a private, unaliased
    # object graph used for every subsequent binding and serialization step.
    exact_payload = _parse_exact_canonical_payload_bytes(payload_json_bytes)
    snapshot = {
        "schema_version": RAW_CONTEXT_SNAPSHOT_IDENTITY_V4_SCHEMA_VERSION,
        "feature_snapshot_id": _required_label(
            feature_snapshot_id,
            reason="RAW_CONTEXT_V4_FEATURE_SNAPSHOT_ID_INVALID",
        ),
        "symbol": _required_label(symbol, reason="RAW_CONTEXT_V4_SYMBOL_INVALID"),
        "timeframe": _required_label(
            timeframe, reason="RAW_CONTEXT_V4_TIMEFRAME_INVALID"
        ),
    }
    temporal = {
        "schema_version": RAW_CONTEXT_TEMPORAL_IDENTITY_V4_SCHEMA_VERSION,
        "candle_open_time": candle_open_time,
        "candle_close_time": candle_close_time,
        "economic_event_time": economic_event_time,
        "raw_context_observed_at": raw_context_observed_at,
        "raw_context_available_at": raw_context_available_at,
        "raw_context_capture_completed_at": raw_context_capture_completed_at,
        "finality_type": RAW_CONTEXT_FINALITY_TYPE,
        "candle_final": True,
    }
    _validate_temporal(temporal)
    producer: dict[str, object] = {
        "schema_version": RAW_CONTEXT_PRODUCER_IDENTITY_V4_SCHEMA_VERSION,
        "producer_id": _required_label(
            producer_id,
            reason="RAW_CONTEXT_V4_PRODUCER_ID_INVALID",
        ),
        "producer_version": _required_label(
            producer_version,
            reason="RAW_CONTEXT_V4_PRODUCER_VERSION_INVALID",
        ),
        "producer_code_sha256": _required_sha256(
            producer_code_sha256,
            reason="RAW_CONTEXT_V4_PRODUCER_CODE_SHA256_INVALID",
        ),
        "producer_config_sha256": _required_sha256(
            producer_config_sha256,
            reason="RAW_CONTEXT_V4_PRODUCER_CONFIG_SHA256_INVALID",
        ),
    }
    producer["producer_identity_sha256"] = _sha256_json(producer)
    context_locator = _locator(snapshot)
    preflight_document: dict[str, object] = {
        "schema_version": RAW_CONTEXT_CAPTURE_V4_SCHEMA_VERSION,
        "context_locator": context_locator,
        "snapshot_identity": snapshot,
        "temporal_identity": temporal,
        "producer_identity": producer,
        "payload": exact_payload,
        "document_binding_sha256": "0" * 64,
    }
    _preflight_canonical_json(
        preflight_document,
        max_bytes=MAX_RAW_CONTEXT_V4_BYTES,
    )
    document: dict[str, object] = {
        "schema_version": RAW_CONTEXT_CAPTURE_V4_SCHEMA_VERSION,
        "context_locator": context_locator,
        "snapshot_identity": snapshot,
        "temporal_identity": temporal,
        "producer_identity": producer,
        "payload": exact_payload,
    }
    document["document_binding_sha256"] = _sha256_json(
        document,
        max_bytes=MAX_RAW_CONTEXT_V4_BYTES,
    )
    validated = _validate_raw_context_document(document)
    return _canonical_json(validated, max_bytes=MAX_RAW_CONTEXT_V4_BYTES).encode(
        "ascii"
    )


def _fresh_publication_record(
    publication_ledger: object,
    publication_entry: object,
) -> dict[str, Any]:
    if type(publication_ledger) is not FeatureSnapshotPublicationLedgerV4:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_EXACT_P0D_LEDGER_REQUIRED")
    if type(publication_entry) is not FeatureSnapshotPublicationLedgerEntryV4:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_EXACT_P0D_ENTRY_REQUIRED")
    try:
        supplied = publication_entry.record
        durable_entries = publication_ledger.read_entries()
    except FeatureSnapshotPublicationLedgerV4Error as exc:
        raise RawContextCasReceiptV4ValidationError(
            "RAW_CONTEXT_CAS_RECEIPT_V4_P0D_REVALIDATION_FAILED"
        ) from exc
    matches = tuple(
        entry
        for entry in durable_entries
        if entry.ledger_sequence == publication_entry.ledger_sequence
        and entry.entry_sha256 == publication_entry.entry_sha256
    )
    if len(matches) != 1:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_P0D_ENTRY_NOT_DURABLY_PRESENT")
    try:
        durable = matches[0].record
    except FeatureSnapshotPublicationLedgerV4Error as exc:
        raise RawContextCasReceiptV4ValidationError(
            "RAW_CONTEXT_CAS_RECEIPT_V4_P0D_REVALIDATION_FAILED"
        ) from exc
    if (
        matches[0].entry_json != publication_entry.entry_json
        or supplied != durable
        or durable.get("schema_version")
        != FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_SCHEMA_VERSION
        or durable.get("ledger_namespace")
        != FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_NAMESPACE
        or durable.get("evidence_classification")
        != FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_EVIDENCE_CLASSIFICATION
        or any(durable.get(name) is not False for name in _P0D_FALSE_FIELDS)
    ):
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_P0D_CONTRACT_MISMATCH")
    return durable


def _validate_context_against_publication(
    document: dict[str, Any],
    publication: dict[str, Any],
) -> None:
    snapshot = cast(dict[str, Any], document["snapshot_identity"])
    temporal = cast(dict[str, Any], document["temporal_identity"])
    artifact = cast(dict[str, Any], publication["feature_artifact_binding"])
    source = cast(dict[str, Any], publication["source_provenance_binding"])
    latest = cast(dict[str, Any], source["latest_candle"])
    if any(
        snapshot[name] != artifact[name]
        for name in ("feature_snapshot_id", "symbol", "timeframe")
    ):
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_SNAPSHOT_IDENTITY_MISMATCH")
    raw_open = _parse_clock(
        temporal["candle_open_time"],
        reason="RAW_CONTEXT_V4_CANDLE_OPEN_TIME_INVALID",
    )
    raw_close = _parse_clock(
        temporal["candle_close_time"],
        reason="RAW_CONTEXT_V4_CANDLE_CLOSE_TIME_INVALID",
    )
    raw_economic = _parse_clock(
        temporal["economic_event_time"],
        reason="RAW_CONTEXT_V4_ECONOMIC_EVENT_TIME_INVALID",
    )
    raw_observed = _parse_clock(
        temporal["raw_context_observed_at"],
        reason="RAW_CONTEXT_V4_RAW_CONTEXT_OBSERVED_AT_INVALID",
    )
    raw_available = _parse_clock(
        temporal["raw_context_available_at"],
        reason="RAW_CONTEXT_V4_RAW_CONTEXT_AVAILABLE_AT_INVALID",
    )
    raw_completed = _parse_clock(
        temporal["raw_context_capture_completed_at"],
        reason="RAW_CONTEXT_V4_RAW_CONTEXT_CAPTURE_COMPLETED_AT_INVALID",
    )
    artifact_open = _parse_upstream_clock(
        artifact["candle_open_time"],
        reason="RAW_CONTEXT_CAS_RECEIPT_V4_P0D_CANDLE_OPEN_INVALID",
    )
    artifact_close = _parse_upstream_clock(
        artifact["candle_close_time"],
        reason="RAW_CONTEXT_CAS_RECEIPT_V4_P0D_CANDLE_CLOSE_INVALID",
    )
    latest_economic = _parse_upstream_clock(
        latest["economic_event_time"],
        reason="RAW_CONTEXT_CAS_RECEIPT_V4_P0D_ECONOMIC_EVENT_INVALID",
    )
    source_ingested = _parse_upstream_clock(
        artifact["source_ingested_at"],
        reason="RAW_CONTEXT_CAS_RECEIPT_V4_P0D_SOURCE_INGESTED_AT_INVALID",
    )
    source_available = _parse_upstream_clock(
        artifact["source_available_at"],
        reason="RAW_CONTEXT_CAS_RECEIPT_V4_P0D_SOURCE_AVAILABLE_AT_INVALID",
    )
    generated = _parse_upstream_clock(
        artifact["generated_at"],
        reason="RAW_CONTEXT_CAS_RECEIPT_V4_P0D_GENERATED_AT_INVALID",
    )
    recorded = _parse_upstream_clock(
        publication["ledger_recorded_at"],
        reason="RAW_CONTEXT_CAS_RECEIPT_V4_P0D_LEDGER_RECORDED_AT_INVALID",
    )
    if (raw_open, raw_close, raw_economic) != (
        artifact_open,
        artifact_close,
        latest_economic,
    ):
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_CLOSED_CANDLE_IDENTITY_MISMATCH")
    if not (
        source_ingested
        <= raw_observed
        <= raw_available
        <= raw_completed
        <= generated
        <= recorded
    ):
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_P0D_TEMPORAL_ASSOCIATION_INVALID")
    if source_available > raw_available:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_CONTEXT_AVAILABLE_BEFORE_SOURCE")


def _ledger_association(
    publication_ledger: FeatureSnapshotPublicationLedgerV4,
    publication: dict[str, Any],
) -> dict[str, object]:
    artifact = cast(dict[str, Any], publication["feature_artifact_binding"])
    source = cast(dict[str, Any], publication["source_provenance_binding"])
    root = os.fspath(publication_ledger.root)
    if (
        not os.path.isabs(root)
        or "\x00" in root
        or any(component == ".." for component in Path(root).parts)
    ):
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_P0D_LEDGER_ROOT_INVALID")
    material: dict[str, object] = {
        "schema_version": RAW_CONTEXT_P0D_ASSOCIATION_V4_SCHEMA_VERSION,
        "ledger_schema_version": publication["schema_version"],
        "ledger_namespace": publication["ledger_namespace"],
        "ledger_root": root,
        "ledger_root_sha256": hashlib.sha256(
            root.encode("utf-8", errors="strict")
        ).hexdigest(),
        "ledger_sequence": publication["ledger_sequence"],
        "ledger_entry_sha256": publication["entry_sha256"],
        "ledger_entry_json_sha256": hashlib.sha256(
            _canonical_json(
                publication,
                max_bytes=MAX_RAW_CONTEXT_V4_BYTES,
            ).encode("ascii")
        ).hexdigest(),
        "publication_identity_sha256": publication["publication_identity_sha256"],
        "publication_replay_identity_sha256": publication[
            "publication_replay_identity_sha256"
        ],
        "source_ledger_sequence": source["source_ledger_sequence"],
        "source_ledger_entry_sha256": source["source_ledger_entry_sha256"],
        "artifact_record_id": artifact["artifact_record_id"],
        "artifact_binding_sha256": artifact["artifact_binding_sha256"],
        "artifact_serialization_sha256": artifact["artifact_serialization_sha256"],
        "feature_snapshot_id": artifact["feature_snapshot_id"],
        "symbol": artifact["symbol"],
        "timeframe": artifact["timeframe"],
        "snapshot_generated_at": artifact["generated_at"],
        "ledger_recorded_at": publication["ledger_recorded_at"],
        "durable_atomic_commit_contract": RAW_CONTEXT_P0D_COMMIT_CONTRACT,
        "committed_head_and_owned_cas_fresh_read_verified": True,
    }
    material["association_sha256"] = _sha256_json(material)
    return material


def _cas_binding(
    store: ImmutableSourcePayloadStore,
    address: SourcePayloadAddress,
) -> dict[str, object]:
    root = os.fspath(store.root_path)
    if (
        not os.path.isabs(root)
        or "\x00" in root
        or any(component == ".." for component in Path(root).parts)
    ):
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_STORE_ROOT_INVALID")
    expected_relative = f"sha256/{address.payload_sha256[:2]}/{address.payload_sha256}"
    if (
        address.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or address.relative_path != expected_relative
        or not _valid_sha256(address.payload_sha256)
        or type(address.payload_byte_count) is not int
        or not 1 <= address.payload_byte_count <= MAX_RAW_CONTEXT_V4_BYTES
    ):
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_CAS_ADDRESS_INVALID")
    material: dict[str, object] = {
        "schema_version": RAW_CONTEXT_CAS_BINDING_V4_SCHEMA_VERSION,
        "store_schema_version": SOURCE_PAYLOAD_STORE_SCHEMA_VERSION,
        "address_schema_version": SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        "logical_namespace": RAW_CONTEXT_NAMESPACE,
        "locator_type": RAW_CONTEXT_CAS_LOCATOR_TYPE,
        "store_root": root,
        "store_root_sha256": hashlib.sha256(
            root.encode("utf-8", errors="strict")
        ).hexdigest(),
        "relative_path": address.relative_path,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "canonical_json_verified": True,
    }
    material["cas_binding_sha256"] = _sha256_json(material)
    return material


def _receipt_material(
    *,
    raw_context_bytes: bytes,
    document: dict[str, Any],
    cas_binding: dict[str, object],
    association: dict[str, object],
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": RAW_CONTEXT_CAS_RECEIPT_V4_SCHEMA_VERSION,
        "evidence_classification": RAW_CONTEXT_CAS_RECEIPT_V4_EVIDENCE_CLASSIFICATION,
        "downstream_status": RAW_CONTEXT_CAS_RECEIPT_V4_DOWNSTREAM_STATUS,
        "raw_context_sha256": hashlib.sha256(raw_context_bytes).hexdigest(),
        "raw_context_byte_count": len(raw_context_bytes),
        "raw_context_document_binding_sha256": document["document_binding_sha256"],
        "context_locator": document["context_locator"],
        "snapshot_identity": document["snapshot_identity"],
        "temporal_identity": document["temporal_identity"],
        "producer_identity": document["producer_identity"],
        "raw_context_cas_binding": cas_binding,
        "p0d_ledger_association": association,
        "authentication_limitations": list(RAW_CONTEXT_AUTHENTICATION_LIMITATIONS),
        **{name: True for name in _TRUE_FIELDS},
        **{name: False for name in _FALSE_FIELDS},
    }
    record["receipt_sha256"] = _sha256_json(record)
    return record


def _validate_receipt_shape(value: object) -> dict[str, Any]:
    receipt = _exact_dict(
        value,
        _RECEIPT_FIELDS,
        reason="RAW_CONTEXT_CAS_RECEIPT_V4_FIELDS_INVALID",
    )
    _exact_dict(
        receipt["context_locator"],
        _LOCATOR_FIELDS,
        reason="RAW_CONTEXT_CAS_RECEIPT_V4_LOCATOR_FIELDS_INVALID",
    )
    _exact_dict(
        receipt["snapshot_identity"],
        _SNAPSHOT_FIELDS,
        reason="RAW_CONTEXT_CAS_RECEIPT_V4_SNAPSHOT_FIELDS_INVALID",
    )
    _validate_temporal(receipt["temporal_identity"])
    _exact_dict(
        receipt["producer_identity"],
        _PRODUCER_FIELDS,
        reason="RAW_CONTEXT_CAS_RECEIPT_V4_PRODUCER_FIELDS_INVALID",
    )
    cas = _exact_dict(
        receipt["raw_context_cas_binding"],
        _CAS_FIELDS,
        reason="RAW_CONTEXT_CAS_RECEIPT_V4_CAS_FIELDS_INVALID",
    )
    association = _exact_dict(
        receipt["p0d_ledger_association"],
        _ASSOCIATION_FIELDS,
        reason="RAW_CONTEXT_CAS_RECEIPT_V4_ASSOCIATION_FIELDS_INVALID",
    )
    if (
        receipt["schema_version"] != RAW_CONTEXT_CAS_RECEIPT_V4_SCHEMA_VERSION
        or receipt["evidence_classification"]
        != RAW_CONTEXT_CAS_RECEIPT_V4_EVIDENCE_CLASSIFICATION
        or receipt["downstream_status"] != RAW_CONTEXT_CAS_RECEIPT_V4_DOWNSTREAM_STATUS
        or receipt["authentication_limitations"]
        != list(RAW_CONTEXT_AUTHENTICATION_LIMITATIONS)
        or any(receipt[name] is not True for name in _TRUE_FIELDS)
        or any(receipt[name] is not False for name in _FALSE_FIELDS)
        or cas["canonical_json_verified"] is not True
        or association["committed_head_and_owned_cas_fresh_read_verified"] is not True
        or association["durable_atomic_commit_contract"]
        != RAW_CONTEXT_P0D_COMMIT_CONTRACT
    ):
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_CONSTANT_OR_FLAG_MISMATCH")
    for field_name in (
        "raw_context_sha256",
        "raw_context_document_binding_sha256",
        "receipt_sha256",
    ):
        _required_sha256(
            receipt[field_name],
            reason=f"RAW_CONTEXT_CAS_RECEIPT_V4_{field_name.upper()}_INVALID",
        )
    for mapping in (cas, association):
        for field_name, item in mapping.items():
            if field_name.endswith("sha256"):
                _required_sha256(
                    item,
                    reason="RAW_CONTEXT_CAS_RECEIPT_V4_NESTED_SHA256_INVALID",
                )
    if (
        type(receipt["raw_context_byte_count"]) is not int
        or not 1 <= receipt["raw_context_byte_count"] <= MAX_RAW_CONTEXT_V4_BYTES
    ):
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_RAW_CONTEXT_BYTE_COUNT_INVALID")
    receipt_material = {
        key: item for key, item in receipt.items() if key != "receipt_sha256"
    }
    if receipt["receipt_sha256"] != _sha256_json(receipt_material):
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_SHA256_MISMATCH")
    for mapping, hash_name in (
        (cas, "cas_binding_sha256"),
        (association, "association_sha256"),
    ):
        material = {key: item for key, item in mapping.items() if key != hash_name}
        if mapping[hash_name] != _sha256_json(material):
            _fail("RAW_CONTEXT_CAS_RECEIPT_V4_NESTED_BINDING_SHA256_MISMATCH")
    return receipt


def _fresh_expected(
    *,
    raw_context_bytes: bytes,
    source_payload_store: ImmutableSourcePayloadStore,
    publication_ledger: FeatureSnapshotPublicationLedgerV4,
    publication_entry: FeatureSnapshotPublicationLedgerEntryV4,
) -> dict[str, Any]:
    if type(source_payload_store) is not ImmutableSourcePayloadStore:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_EXACT_CAS_STORE_REQUIRED")
    document = _validate_raw_context_document(_parse_json_bytes(raw_context_bytes))
    digest = hashlib.sha256(raw_context_bytes).hexdigest()
    try:
        stored = source_payload_store.get(
            digest,
            expected_byte_count=len(raw_context_bytes),
        )
    except SourcePayloadStoreError as exc:
        raise RawContextCasReceiptV4ValidationError(
            "RAW_CONTEXT_CAS_RECEIPT_V4_CAS_REVALIDATION_FAILED"
        ) from exc
    if stored != raw_context_bytes:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_CAS_BYTES_CHANGED")
    publication = _fresh_publication_record(publication_ledger, publication_entry)
    _validate_context_against_publication(document, publication)
    address = SourcePayloadAddress(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=digest,
        payload_byte_count=len(raw_context_bytes),
        relative_path=f"sha256/{digest[:2]}/{digest}",
    )
    return _receipt_material(
        raw_context_bytes=raw_context_bytes,
        document=document,
        cas_binding=_cas_binding(source_payload_store, address),
        association=_ledger_association(publication_ledger, publication),
    )


@dataclass(frozen=True, slots=True)
class RawContextCasReceiptArtifactV4:
    """Factory-only receipt that freshly revalidates CAS and P0-D on access."""

    schema_version: str
    raw_context_sha256: str
    raw_context_byte_count: int
    receipt_sha256: str
    receipt_json: str = field(repr=False)
    _raw_context_bytes: bytes = field(repr=False, compare=False)
    _source_payload_store: ImmutableSourcePayloadStore = field(
        repr=False, compare=False
    )
    _publication_ledger: FeatureSnapshotPublicationLedgerV4 = field(
        repr=False,
        compare=False,
    )
    _publication_entry: FeatureSnapshotPublicationLedgerEntryV4 = field(
        repr=False,
        compare=False,
    )
    _construction_token: object = field(repr=False, compare=False)
    audit_receipt_only: bool = field(default=True, init=False)
    exact_canonical_raw_context_bytes_pinned: bool = field(default=True, init=False)
    raw_context_cas_integrity_revalidated: bool = field(default=True, init=False)
    p0d_committed_head_and_owned_cas_freshly_revalidated: bool = field(
        default=True,
        init=False,
    )
    snapshot_and_closed_candle_identity_bound: bool = field(default=True, init=False)
    declared_producer_code_and_configuration_identity_bound: bool = field(
        default=True,
        init=False,
    )
    upstream_payload_construction_independently_attested: bool = field(
        default=False,
        init=False,
    )
    trace_raw_context_binding_verified: bool = field(default=False, init=False)
    resolver_branch_capture_authenticated: bool = field(default=False, init=False)
    producer_identity_independently_authenticated: bool = field(
        default=False, init=False
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
            _fail("RAW_CONTEXT_CAS_RECEIPT_V4_FACTORY_CONSTRUCTION_REQUIRED")
        parsed = _validate_receipt_shape(_parse_receipt_json(self.receipt_json))
        expected = _fresh_expected(
            raw_context_bytes=self._raw_context_bytes,
            source_payload_store=self._source_payload_store,
            publication_ledger=self._publication_ledger,
            publication_entry=self._publication_entry,
        )
        if (
            self.schema_version != RAW_CONTEXT_CAS_RECEIPT_V4_SCHEMA_VERSION
            or self.raw_context_sha256 != expected["raw_context_sha256"]
            or self.raw_context_byte_count != expected["raw_context_byte_count"]
            or self.receipt_sha256 != expected["receipt_sha256"]
            or parsed != expected
            or self.receipt_json
            != _canonical_json(expected, max_bytes=MAX_RAW_CONTEXT_RECEIPT_V4_BYTES)
            or any(getattr(self, name) is not True for name in _TRUE_FIELDS)
            or any(getattr(self, name) is not False for name in _FALSE_FIELDS)
        ):
            _fail("RAW_CONTEXT_CAS_RECEIPT_V4_ARTIFACT_BINDING_MISMATCH")

    @property
    def receipt(self) -> dict[str, Any]:
        """Return a receipt only after a fresh CAS and durable-ledger read."""

        parsed = _validate_receipt_shape(_parse_receipt_json(self.receipt_json))
        expected = _fresh_expected(
            raw_context_bytes=self._raw_context_bytes,
            source_payload_store=self._source_payload_store,
            publication_ledger=self._publication_ledger,
            publication_entry=self._publication_entry,
        )
        if parsed != expected:
            _fail("RAW_CONTEXT_CAS_RECEIPT_V4_UPSTREAM_CHANGED")
        return cast(
            dict[str, Any],
            json.loads(
                _canonical_json(parsed, max_bytes=MAX_RAW_CONTEXT_RECEIPT_V4_BYTES)
            ),
        )

    @property
    def raw_context_bytes(self) -> bytes:
        """Return exact bytes only after the same complete fresh revalidation."""

        _ = self.receipt
        return bytes(self._raw_context_bytes)


def build_raw_context_cas_receipt_v4(
    *,
    raw_context_bytes: bytes,
    source_payload_store: ImmutableSourcePayloadStore,
    publication_ledger: FeatureSnapshotPublicationLedgerV4,
    publication_entry: FeatureSnapshotPublicationLedgerEntryV4,
) -> RawContextCasReceiptArtifactV4:
    """Durably pin exact bytes and bind them to one exact committed P0-D entry."""

    if type(raw_context_bytes) is not bytes:
        _fail("RAW_CONTEXT_V4_EXACT_BYTES_REQUIRED")
    if type(source_payload_store) is not ImmutableSourcePayloadStore:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_EXACT_CAS_STORE_REQUIRED")
    if type(publication_ledger) is not FeatureSnapshotPublicationLedgerV4:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_EXACT_P0D_LEDGER_REQUIRED")
    if type(publication_entry) is not FeatureSnapshotPublicationLedgerEntryV4:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_EXACT_P0D_ENTRY_REQUIRED")
    document = _validate_raw_context_document(_parse_json_bytes(raw_context_bytes))
    first_publication = _fresh_publication_record(publication_ledger, publication_entry)
    _validate_context_against_publication(document, first_publication)
    digest = hashlib.sha256(raw_context_bytes).hexdigest()
    try:
        address = source_payload_store.put(
            raw_context_bytes,
            expected_sha256=digest,
            expected_byte_count=len(raw_context_bytes),
        )
    except SourcePayloadStoreError as exc:
        raise RawContextCasReceiptV4ValidationError(
            "RAW_CONTEXT_CAS_RECEIPT_V4_CAS_PUBLISH_FAILED"
        ) from exc
    first = _receipt_material(
        raw_context_bytes=raw_context_bytes,
        document=document,
        cas_binding=_cas_binding(source_payload_store, address),
        association=_ledger_association(publication_ledger, first_publication),
    )
    # Re-read both durable systems after materialization.  Any path swap,
    # truncation, mutable upstream, or association change prevents construction.
    second = _fresh_expected(
        raw_context_bytes=raw_context_bytes,
        source_payload_store=source_payload_store,
        publication_ledger=publication_ledger,
        publication_entry=publication_entry,
    )
    if first != second:
        _fail("RAW_CONTEXT_CAS_RECEIPT_V4_UPSTREAM_CHANGED_DURING_BIND")
    canonical = _canonical_json(second, max_bytes=MAX_RAW_CONTEXT_RECEIPT_V4_BYTES)
    return RawContextCasReceiptArtifactV4(
        schema_version=RAW_CONTEXT_CAS_RECEIPT_V4_SCHEMA_VERSION,
        raw_context_sha256=cast(str, second["raw_context_sha256"]),
        raw_context_byte_count=cast(int, second["raw_context_byte_count"]),
        receipt_sha256=cast(str, second["receipt_sha256"]),
        receipt_json=canonical,
        _raw_context_bytes=raw_context_bytes,
        _source_payload_store=source_payload_store,
        _publication_ledger=publication_ledger,
        _publication_entry=publication_entry,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "MAX_RAW_CONTEXT_RECEIPT_V4_BYTES",
    "MAX_RAW_CONTEXT_V4_BYTES",
    "RAW_CONTEXT_AUTHENTICATION_LIMITATIONS",
    "RAW_CONTEXT_CAPTURE_V4_SCHEMA_VERSION",
    "RAW_CONTEXT_CAS_RECEIPT_V4_DOWNSTREAM_STATUS",
    "RAW_CONTEXT_CAS_RECEIPT_V4_EVIDENCE_CLASSIFICATION",
    "RAW_CONTEXT_CAS_RECEIPT_V4_SCHEMA_VERSION",
    "RAW_CONTEXT_NAMESPACE",
    "RAW_CONTEXT_NAMESPACE_TYPE",
    "RawContextCasReceiptArtifactV4",
    "RawContextCasReceiptV4ValidationError",
    "build_raw_context_cas_receipt_v4",
    "canonical_raw_context_bytes_v4",
]
