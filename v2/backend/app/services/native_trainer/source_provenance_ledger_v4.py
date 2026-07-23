"""Unwired append-only v4 provenance ledger for atomic canonical OHLCV captures.

This module is the durable boundary immediately after
``canonical_ohlcv_atomic_receipt_adapter``.  It accepts only that adapter's
factory-authenticated capture, revalidates its exact source and manifest CAS
bindings, pins the source, manifest, and every selected row in a private
ledger-owned immutable CAS, and records the complete ordered v4 receipt chain
under explicit trainer run/cycle identities.

The ledger is deliberately not imported by a feature worker or trainer.  A
durable provenance append does not publish a feature, admit a sample, or
authorize prediction, paper trading, or live execution.  Those flags are
persisted and returned as false.

Each canonical JSONL entry is hash chained.  A separately fsynced v4 head binds
the committed sequence, exact ledger byte count, and exact ledger prefix hash,
which makes whole-tail truncation detectable.  An advisory interprocess lock is
held across validation, append, flush/fsync, head publication, and post-commit
readback.  One complete entry left ahead of the durable head by a crash can be
recovered only by an exact replay of the same capture/run/cycle material;
partial or conflicting tails fail closed.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn, cast

from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    ATOMIC_REDIS_SOURCE_READ_DOWNSTREAM_STATUS,
    ATOMIC_REDIS_SOURCE_READ_EVIDENCE_CLASSIFICATION,
    ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION,
    ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION,
    MAX_AGGREGATE_PAYLOAD_BYTES,
    MAX_BATCH_MATERIALIZED_PAYLOAD_BYTES,
    MAX_RANGE_REPLY_BYTES,
    MAX_SOURCE_KEYS_PER_BATCH,
    MAX_SOURCE_PAYLOAD_BYTES,
    REDIS_TIME_CLOCK_SEMANTICS,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    CANONICAL_OHLCV_ATOMIC_CAPTURE_DOWNSTREAM_STATUS,
    CANONICAL_OHLCV_ATOMIC_CAPTURE_EVIDENCE_CLASSIFICATION,
    CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION,
    CANONICAL_OHLCV_FINALITY_VERIFIER,
    CANONICAL_OHLCV_ROW_PAYLOAD_TYPE,
    CANONICAL_OHLCV_SUFFIX_DIGEST_SCHEMA_VERSION,
    CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION,
    CanonicalOhlcvAtomicCaptureError,
    CanonicalOhlcvAtomicReceiptCapture,
)
from v2.backend.app.services.native_trainer.feature_window_dependency_contract import (
    FeatureWindowContractError,
    FullContiguousCoreInputBinding,
    bind_full_contiguous_core_ta_input,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    SOURCE_PAYLOAD_STORE_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadIntegrityError,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    MAX_OHLCV_CLOSED_ROWS,
    TIMEFRAME_DURATION_MS,
    OHLCVClosedWindowValidationError,
    ValidatedOHLCVClosedWindow,
    validate_ohlcv_closed_window,
)
from v2.backend.app.services.native_trainer.source_read_receipt_v4 import (
    SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION,
    SourceReadReceiptV4Error,
    validate_source_read_receipt_v4,
)

TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION = "trainer_source_provenance_ledger_entry_v4"
TRAINER_SOURCE_PROVENANCE_LEDGER_V4_HEAD_SCHEMA_VERSION = "trainer_source_provenance_ledger_head_v4"
TRAINER_SOURCE_PROVENANCE_LEDGER_V4_REPLAY_SCHEMA_VERSION = (
    "trainer_source_provenance_replay_identity_v4"
)
TRAINER_SOURCE_PROVENANCE_LEDGER_V4_EVIDENCE_CLASSIFICATION = (
    "DURABLE_ATOMIC_CANONICAL_OHLCV_SOURCE_PROVENANCE_V4_UNWIRED"
)
TRAINER_SOURCE_PROVENANCE_LEDGER_V4_DOWNSTREAM_STATUS = (
    "NO_FEATURE_PUBLICATION_TRAINER_ADMISSION_OR_EXECUTION_AUTHORIZATION"
)
TRAINER_SOURCE_PROVENANCE_LEDGER_V4_NAMESPACE = "trainer-canonical-ohlcv-source-v4"
TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME = "trainer_source_provenance_v4.jsonl"
TRAINER_SOURCE_PROVENANCE_LEDGER_V4_HEAD_FILENAME = "trainer_source_provenance_v4.head.json"
TRAINER_SOURCE_PROVENANCE_LEDGER_V4_LOCK_FILENAME = ".trainer_source_provenance_v4.lock"
TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_SCHEMA_VERSION = (
    "trainer_source_provenance_immutable_cas_v4"
)
TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_NAMESPACE = "trainer-canonical-ohlcv-source-provenance-v4"
TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_ROOT_RELATIVE_PATH = "trainer_source_provenance_v4_cas"
TRAINER_SOURCE_PROVENANCE_LEDGER_V4_GENESIS_SHA256 = hashlib.sha256(
    b"trainer_source_provenance_ledger_v4:genesis"
).hexdigest()

# Resource-integrity ceilings only.  They do not select a market, feature,
# leverage, or training sample.
MAX_LEDGER_ENTRY_BYTES = 16 * 1024 * 1024
MAX_LEDGER_BYTES = 512 * 1024 * 1024
MAX_LEDGER_ENTRIES = 1_000_000
MAX_OPAQUE_ID_BYTES = 256

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_CONSTRUCTION_TOKEN = object()
_APPEND_RESULT_CONSTRUCTION_TOKEN = object()
_APPEND_RESULT_DISPOSITIONS = frozenset(
    {
        "APPENDED",
        "EXACT_REPLAY",
        "RECOVERED_EXACT_PENDING_APPEND",
    }
)
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_MAX_PATH_COMPONENTS = 128
_DOWNSTREAM_FLAG_FIELDS = (
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)
_ENTRY_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "ledger_namespace",
        "ledger_sequence",
        "previous_entry_sha256",
        "trainer_run_id",
        "trainer_cycle_id",
        "cycle_identity_sha256",
        "replay_identity_sha256",
        "ledger_recorded_at",
        "ledger_owned_store",
        "source_capture",
        "suffix_manifest",
        "ordered_rows",
        "temporal_semantics",
        *_DOWNSTREAM_FLAG_FIELDS,
        "entry_sha256",
    }
)
_STORE_FIELDS = frozenset(
    {
        "schema_version",
        "namespace",
        "root_relative_path",
        "underlying_store_schema_version",
        "address_schema_version",
        "store_binding_sha256",
    }
)
_SOURCE_FIELDS = frozenset(
    {
        "capture_schema_version",
        "source_key",
        "source_key_sha256",
        "source_key_version",
        "atomic_batch_id",
        "atomic_batch_material_json",
        "atomic_batch_material_sha256",
        "atomic_batch_material_byte_count",
        "atomic_server_time_seconds",
        "atomic_server_time_microseconds",
        "atomic_server_observed_at",
        "source_pttl_ms",
        "consumer_observed_at",
        "consumer_observed_at_ms",
        "full_source_payload",
    }
)
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "exact_manifest_json",
        "exact_manifest_sha256",
        "exact_manifest_byte_count",
        "manifest_cas_address",
        "suffix_digest_material_json",
        "suffix_digest_sha256",
        "raw_row_count",
        "selected_source_start_index",
        "selected_source_end_index_exclusive",
        "selected_row_count",
        "selected_candle_ids",
    }
)
_ROW_FIELDS = frozenset(
    {
        "selected_ordinal",
        "source_index",
        "byte_start",
        "byte_end_exclusive",
        "exact_payload_sha256",
        "exact_payload_byte_count",
        "source_payload_cas_address",
        "candle_id",
        "candle_open_time_ms",
        "candle_close_time_ms",
        "producer_event_time_ms",
        "ingested_at_ms",
        "available_at_ms",
        "source",
        "source_sequence_id",
        "raw_payload_hash",
        "is_backfilled",
        "source_read_receipt_schema_version",
        "source_read_receipt_sha256",
        "source_read_receipt_json",
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
        "consumer_observed_at",
        "feature_cutoff",
        "read_completed_at",
        "finality_cutoff",
        "finality_verified_at",
    }
)
_ADDRESS_FIELDS = frozenset(
    {"schema_version", "payload_sha256", "payload_byte_count", "relative_path"}
)
_TEMPORAL_FIELDS = frozenset(
    {
        "economic_event_time_semantics",
        "producer_event_time_semantics",
        "ingested_at_semantics",
        "available_at_semantics",
        "consumer_observed_at_semantics",
        "feature_cutoff_semantics",
        "generated_at",
        "decision_time",
        "execution_time",
    }
)
_HEAD_FIELDS = frozenset(
    {
        "schema_version",
        "ledger_schema_version",
        "ledger_filename",
        "ledger_sequence",
        "ledger_byte_count",
        "ledger_sha256",
        "entry_sha256",
        "head_sha256",
    }
)
_P0B_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "source_key",
        "source_key_sha256",
        "source_key_version",
        "atomic_batch_id",
        "atomic_batch_material_sha256",
        "atomic_batch_material_json",
        "atomic_server_time_seconds",
        "atomic_server_time_microseconds",
        "atomic_server_observed_at",
        "source_pttl_ms",
        "consumer_observed_at",
        "consumer_observed_at_ms",
        "full_source_payload_cas_address",
        "raw_row_count",
        "source_gap_indices",
        "source_gap_missing_interval_counts",
        "selected_source_start_index",
        "selected_source_end_index_exclusive",
        "selected_row_count",
        "excluded_prefix_row_count",
        "excluded_prefix_gap_indices",
        "excluded_prefix_gap_missing_interval_counts",
        "selected_internal_gap_indices",
        "tail_missing_interval_count",
        "latest_candle_matches_expected_cutoff",
        "binding_selection_sha256",
        "selected_candle_id_chain_sha256",
        "suffix_digest_material_json",
        "suffix_digest_sha256",
        "selected_rows",
        "durable_ledger_appended",
        "feature_snapshot_published",
        "feature_publication_receipt_emitted",
        "consumer_eligible",
        "trainer_admission_granted",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
    }
)
_P0B_MANIFEST_ROW_FIELDS = frozenset(
    {
        "selected_ordinal",
        "source_index",
        "byte_start",
        "byte_end_exclusive",
        "exact_payload_sha256",
        "exact_payload_byte_count",
        "source_payload_cas_address",
        "candle_id",
        "candle_open_time_ms",
        "candle_close_time_ms",
        "producer_event_time_ms",
        "ingested_at_ms",
        "available_at_ms",
        "source",
        "source_sequence_id",
        "raw_payload_hash",
        "is_backfilled",
        "source_read_receipt_v4",
    }
)
_SUFFIX_DIGEST_FIELDS = frozenset(
    {
        "schema_version",
        "source_key",
        "source_key_version",
        "full_source_payload_sha256",
        "full_source_payload_byte_count",
        "binding_selection_sha256",
        "selected_candle_id_chain_sha256",
        "selected_source_start_index",
        "selected_source_end_index_exclusive",
        "selected_row_count",
        "ordered_selected_rows",
    }
)
_SUFFIX_DIGEST_ROW_FIELDS = frozenset(
    {
        "selected_ordinal",
        "source_index",
        "byte_start",
        "byte_end_exclusive",
        "exact_payload_sha256",
        "exact_payload_byte_count",
        "candle_id",
        "candle_open_time_ms",
        "candle_close_time_ms",
        "source_sequence_id",
        "raw_payload_hash",
        "source_read_receipt_sha256",
    }
)


class TrainerSourceProvenanceLedgerV4Error(RuntimeError):
    """Base fail-closed v4 source-provenance ledger error."""


class TrainerSourceProvenanceLedgerV4ValidationError(TrainerSourceProvenanceLedgerV4Error):
    """Caller input or P0-B capture contract is invalid."""


class TrainerSourceProvenanceLedgerV4IntegrityError(TrainerSourceProvenanceLedgerV4Error):
    """Ledger bytes, chain, durable head, or persisted evidence do not bind."""


class TrainerSourceProvenanceLedgerV4ConflictError(TrainerSourceProvenanceLedgerV4Error):
    """A run/cycle replay conflicts with already appended material."""


class TrainerSourceProvenanceLedgerV4DurabilityError(TrainerSourceProvenanceLedgerV4Error):
    """Append, flush/fsync, head publication, or post-commit readback failed."""


@dataclass(frozen=True, slots=True)
class TrainerSourceProvenanceLedgerEntryV4:
    """Factory-authenticated, freshly read-back v4 ledger entry."""

    schema_version: str
    ledger_sequence: int
    previous_entry_sha256: str
    trainer_run_id: str
    trainer_cycle_id: str
    cycle_identity_sha256: str
    replay_identity_sha256: str
    entry_sha256: str
    entry_json: str = field(repr=False)
    _construction_token: object = field(repr=False, compare=False)
    source_provenance_ledger_recorded: bool = field(default=True, init=False)
    durable_postcommit_readback_verified: bool = field(default=True, init=False)
    feature_snapshot_published: bool = field(default=False, init=False)
    feature_publication_receipt_emitted: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _integrity_error("source_provenance_v4_factory_construction_required")
        record = _parse_entry_line(self.entry_json.encode("ascii"))
        if (
            self.schema_version != TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION
            or self.ledger_sequence != record["ledger_sequence"]
            or self.previous_entry_sha256 != record["previous_entry_sha256"]
            or self.trainer_run_id != record["trainer_run_id"]
            or self.trainer_cycle_id != record["trainer_cycle_id"]
            or self.cycle_identity_sha256 != record["cycle_identity_sha256"]
            or self.replay_identity_sha256 != record["replay_identity_sha256"]
            or self.entry_sha256 != record["entry_sha256"]
            or any(getattr(self, name) is not False for name in _DOWNSTREAM_FLAG_FIELDS)
        ):
            _integrity_error("source_provenance_v4_artifact_binding_invalid")

    @property
    def record(self) -> dict[str, Any]:
        """Return a fresh, fully validated mapping."""

        return _parse_entry_line(self.entry_json.encode("ascii"))


@dataclass(frozen=True, slots=True)
class TrainerSourceProvenanceAppendResultV4:
    """Factory-authenticated durable append, replay, or recovery result."""

    entry: TrainerSourceProvenanceLedgerEntryV4
    disposition: str
    _construction_token: object | None = field(default=None, repr=False, compare=False)
    source_provenance_ledger_recorded: bool = field(default=True, init=False)
    durable_postcommit_readback_verified: bool = field(default=True, init=False)
    feature_snapshot_published: bool = field(default=False, init=False)
    feature_publication_receipt_emitted: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _APPEND_RESULT_CONSTRUCTION_TOKEN:
            _integrity_error("source_provenance_v4_append_result_factory_construction_required")
        if (
            type(self.entry) is not TrainerSourceProvenanceLedgerEntryV4
            or type(self.disposition) is not str
            or self.disposition not in _APPEND_RESULT_DISPOSITIONS
            or self.source_provenance_ledger_recorded is not True
            or self.durable_postcommit_readback_verified is not True
            or self.entry.source_provenance_ledger_recorded is not True
            or self.entry.durable_postcommit_readback_verified is not True
            or any(getattr(self, name) is not False for name in _DOWNSTREAM_FLAG_FIELDS)
            or any(getattr(self.entry, name) is not False for name in _DOWNSTREAM_FLAG_FIELDS)
        ):
            _integrity_error("source_provenance_v4_append_result_binding_invalid")
        # Reparse and fully validate the factory-authenticated, post-commit
        # readback artifact before exposing any true durability property.
        _ = self.entry.record


@dataclass(frozen=True, slots=True)
class _LedgerState:
    raw_bytes: bytes
    records: tuple[dict[str, Any], ...]
    line_end_offsets: tuple[int, ...]
    committed_count: int

    @property
    def pending_record(self) -> dict[str, Any] | None:
        if len(self.records) == self.committed_count:
            return None
        return self.records[-1]


def _validation_error(reason: str) -> NoReturn:
    raise TrainerSourceProvenanceLedgerV4ValidationError(reason) from None


def _integrity_error(reason: str) -> NoReturn:
    raise TrainerSourceProvenanceLedgerV4IntegrityError(reason) from None


def _conflict_error(reason: str) -> NoReturn:
    raise TrainerSourceProvenanceLedgerV4ConflictError(reason) from None


def _durability_error(reason: str, *, cause: BaseException | None = None) -> NoReturn:
    error = TrainerSourceProvenanceLedgerV4DurabilityError(reason)
    if cause is None:
        raise error from None
    raise error from cause


def _canonical_json(value: object, *, max_bytes: int = MAX_LEDGER_ENTRY_BYTES) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        raw = encoded.encode("ascii", errors="strict")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeEncodeError):
        _integrity_error("source_provenance_v4_material_not_strict_json")
    if not raw or len(raw) > max_bytes:
        _integrity_error("source_provenance_v4_material_size_invalid")
    return encoded


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable_sha256(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode("ascii"))


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _integrity_error("source_provenance_v4_duplicate_json_key")
        result[key] = value
    return result


def _parse_json_object(raw: bytes, *, max_bytes: int) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > max_bytes:
        _integrity_error("source_provenance_v4_json_size_invalid")
    try:
        text = raw.decode("ascii", errors="strict")
        parsed = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=lambda _value: _integrity_error(
                "source_provenance_v4_json_constant_forbidden"
            ),
        )
    except TrainerSourceProvenanceLedgerV4Error:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OverflowError, RecursionError):
        _integrity_error("source_provenance_v4_json_invalid")
    if type(parsed) is not dict:
        _integrity_error("source_provenance_v4_json_not_object")
    typed = cast(dict[str, Any], parsed)
    if _canonical_json(typed, max_bytes=max_bytes) != text:
        _integrity_error("source_provenance_v4_json_not_canonical")
    return typed


def _exact_json_array_element_spans(payload: bytes) -> tuple[tuple[int, int], ...]:
    """Re-derive exact canonical-row byte spans from owned source bytes."""

    try:
        text = payload.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        _integrity_error("source_provenance_v4_owned_source_span_ascii_invalid")
    decoder = json.JSONDecoder()
    length = len(text)

    def skip_whitespace(position: int) -> int:
        while position < length and text[position] in " \t\r\n":
            position += 1
        return position

    index = skip_whitespace(0)
    if index >= length or text[index] != "[":
        _integrity_error("source_provenance_v4_owned_source_span_invalid")
    index = skip_whitespace(index + 1)
    spans: list[tuple[int, int]] = []
    if index < length and text[index] == "]":
        _integrity_error("source_provenance_v4_owned_source_span_invalid")
    while index < length:
        if len(spans) >= MAX_OHLCV_CLOSED_ROWS:
            _integrity_error("source_provenance_v4_owned_source_span_limit_exceeded")
        start = index
        try:
            _, end = decoder.raw_decode(text, index)
        except (json.JSONDecodeError, RecursionError):
            _integrity_error("source_provenance_v4_owned_source_span_invalid")
        if end <= start:
            _integrity_error("source_provenance_v4_owned_source_span_invalid")
        spans.append((start, end))
        index = skip_whitespace(end)
        if index >= length:
            _integrity_error("source_provenance_v4_owned_source_span_invalid")
        if text[index] == "]":
            index = skip_whitespace(index + 1)
            if index != length:
                _integrity_error("source_provenance_v4_owned_source_span_invalid")
            break
        if text[index] != ",":
            _integrity_error("source_provenance_v4_owned_source_span_invalid")
        index = skip_whitespace(index + 1)
    if not spans:
        _integrity_error("source_provenance_v4_owned_source_span_invalid")
    return tuple(spans)


def _exact_object(
    value: object,
    fields: frozenset[str],
    *,
    reason: str,
) -> dict[str, Any]:
    if type(value) is not dict or frozenset(cast(dict[object, object], value)) != fields:
        _integrity_error(reason)
    return cast(dict[str, Any], value)


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _is_valid_id(value: object) -> bool:
    return (
        type(value) is str
        and len(value.encode("utf-8")) <= MAX_OPAQUE_ID_BYTES
        and _OPAQUE_ID_RE.fullmatch(value) is not None
    )


def _required_id(value: object, *, reason: str) -> str:
    if not _is_valid_id(value):
        _validation_error(reason)
    return cast(str, value)


def _parse_clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        _integrity_error(reason)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        _integrity_error(reason)
    if parsed < _EPOCH or parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        _integrity_error(reason)
    return parsed


def _clock_to_ms(value: datetime) -> int:
    delta = value - _EPOCH
    return ((delta.days * 86_400 + delta.seconds) * 1_000) + (delta.microseconds // 1_000)


def _ms_to_clock(value: object) -> str:
    if type(value) is not int or value < 0:
        _integrity_error("source_provenance_v4_millisecond_clock_invalid")
    try:
        resolved = _EPOCH + timedelta(milliseconds=value)
    except (OverflowError, ValueError):
        _integrity_error("source_provenance_v4_millisecond_clock_invalid")
    return resolved.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _sample_ledger_clock(clock: object, *, source_observed_at: str) -> str:
    if not callable(clock):
        _validation_error("source_provenance_v4_ledger_clock_not_callable")
    try:
        observed = cast(Callable[[], object], clock)()
    except Exception:  # noqa: BLE001 - hostile clock details must not escape
        _validation_error("source_provenance_v4_ledger_clock_failed")
    if type(observed) is not datetime or observed.tzinfo is not UTC or observed < _EPOCH:
        _validation_error("source_provenance_v4_ledger_clock_not_exact_utc_datetime")
    canonical = observed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    source_clock = _parse_clock(
        source_observed_at,
        reason="source_provenance_v4_consumer_observed_at_invalid",
    )
    if observed < source_clock:
        _validation_error("source_provenance_v4_recorded_before_source_read")
    return canonical


def _address_material(address: object) -> dict[str, object]:
    values = {
        "schema_version": getattr(address, "schema_version", None),
        "payload_sha256": getattr(address, "payload_sha256", None),
        "payload_byte_count": getattr(address, "payload_byte_count", None),
        "relative_path": getattr(address, "relative_path", None),
    }
    _validate_address(values)
    return values


def _validate_address(value: object) -> dict[str, Any]:
    address = _exact_object(
        value,
        _ADDRESS_FIELDS,
        reason="source_provenance_v4_cas_address_invalid",
    )
    if (
        address["schema_version"] != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or not _is_sha256(address["payload_sha256"])
        or type(address["payload_byte_count"]) is not int
        or address["payload_byte_count"] <= 0
        or type(address["relative_path"]) is not str
        or not address["relative_path"]
        or not address["relative_path"].isascii()
        or address["relative_path"].startswith("/")
        or ".." in Path(address["relative_path"]).parts
        or address["relative_path"]
        != (f"sha256/{cast(str, address['payload_sha256'])[:2]}/" f"{address['payload_sha256']}")
    ):
        _integrity_error("source_provenance_v4_cas_address_invalid")
    return address


def _cycle_identity(run_id: str, cycle_id: str) -> str:
    return _stable_sha256(
        {
            "schema_version": "trainer_source_provenance_cycle_identity_v4",
            "trainer_run_id": run_id,
            "trainer_cycle_id": cycle_id,
        }
    )


def _temporal_semantics() -> dict[str, object]:
    return {
        "economic_event_time_semantics": "closed_candle_close_time",
        "producer_event_time_semantics": "producer_message_event_time",
        "ingested_at_semantics": "canonical_ingestor_observation_time",
        "available_at_semantics": "exact_source_value_available_time",
        "consumer_observed_at_semantics": "atomic_redis_read_completion_time",
        "feature_cutoff_semantics": "closed_candle_close_time",
        "generated_at": None,
        "decision_time": None,
        "execution_time": None,
    }


def _owned_store_material() -> dict[str, object]:
    material: dict[str, object] = {
        "schema_version": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_SCHEMA_VERSION,
        "namespace": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_NAMESPACE,
        "root_relative_path": (TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_ROOT_RELATIVE_PATH),
        "underlying_store_schema_version": SOURCE_PAYLOAD_STORE_SCHEMA_VERSION,
        "address_schema_version": SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    }
    material["store_binding_sha256"] = _stable_sha256(material)
    return material


def _validate_owned_store_material(value: object) -> dict[str, Any]:
    material = _exact_object(
        value,
        _STORE_FIELDS,
        reason="source_provenance_v4_owned_store_fields_invalid",
    )
    if material != _owned_store_material():
        _integrity_error("source_provenance_v4_owned_store_binding_invalid")
    return material


def _owned_store_put(
    store: ImmutableSourcePayloadStore,
    payload: bytes,
    *,
    expected_sha256: str,
    expected_byte_count: int,
) -> dict[str, object]:
    try:
        address = store.put(
            payload,
            expected_sha256=expected_sha256,
            expected_byte_count=expected_byte_count,
        )
    except SourcePayloadIntegrityError as exc:
        raise TrainerSourceProvenanceLedgerV4IntegrityError(
            "source_provenance_v4_owned_cas_put_integrity_failed"
        ) from exc
    except SourcePayloadStoreError as exc:
        raise TrainerSourceProvenanceLedgerV4DurabilityError(
            "source_provenance_v4_owned_cas_put_failed"
        ) from exc
    material = _address_material(address)
    try:
        readback = store.get(
            expected_sha256,
            expected_byte_count=expected_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise TrainerSourceProvenanceLedgerV4IntegrityError(
            "source_provenance_v4_owned_cas_post_put_readback_failed"
        ) from exc
    if readback != payload:
        _integrity_error("source_provenance_v4_owned_cas_post_put_bytes_mismatch")
    return material


def _capture_replay_material(
    capture: object,
    store: ImmutableSourcePayloadStore,
    *,
    trainer_run_id: str,
    trainer_cycle_id: str,
) -> dict[str, object]:
    if type(capture) is not CanonicalOhlcvAtomicReceiptCapture:
        _validation_error("source_provenance_v4_p0b_capture_type_required")
    if type(store) is not ImmutableSourcePayloadStore:
        _integrity_error("source_provenance_v4_owned_store_type_invalid")
    typed_capture = capture
    try:
        exact_source_bytes = typed_capture.exact_full_source_payload_bytes
        selected = typed_capture.selected_candles
        manifest = typed_capture.suffix_manifest
    except CanonicalOhlcvAtomicCaptureError as exc:
        raise TrainerSourceProvenanceLedgerV4ValidationError(
            "source_provenance_v4_p0b_capture_revalidation_failed"
        ) from exc
    if typed_capture.schema_version != CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION:
        _validation_error("source_provenance_v4_p0b_capture_schema_required")

    upstream_source_address = _address_material(typed_capture.full_source_payload_address)
    source_sha = _sha256_bytes(exact_source_bytes)
    if upstream_source_address["payload_sha256"] != source_sha or upstream_source_address[
        "payload_byte_count"
    ] != len(exact_source_bytes):
        _integrity_error("source_provenance_v4_exact_source_bytes_not_bound")
    source_address = _owned_store_put(
        store,
        exact_source_bytes,
        expected_sha256=source_sha,
        expected_byte_count=len(exact_source_bytes),
    )
    atomic_bytes = typed_capture.atomic_batch_material_json.encode("ascii", errors="strict")
    if _sha256_bytes(atomic_bytes) != typed_capture.atomic_batch_material_sha256:
        _integrity_error("source_provenance_v4_atomic_batch_material_not_bound")

    manifest_bytes = typed_capture.suffix_manifest_json.encode("ascii", errors="strict")
    upstream_manifest_address = _address_material(typed_capture.suffix_manifest_address)
    manifest_sha = _sha256_bytes(manifest_bytes)
    if (
        upstream_manifest_address["payload_sha256"] != manifest_sha
        or upstream_manifest_address["payload_byte_count"] != len(manifest_bytes)
        or manifest.get("schema_version") != CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION
    ):
        _integrity_error("source_provenance_v4_exact_manifest_bytes_not_bound")
    manifest_address = _owned_store_put(
        store,
        manifest_bytes,
        expected_sha256=manifest_sha,
        expected_byte_count=len(manifest_bytes),
    )

    rows: list[dict[str, object]] = []
    for expected_ordinal, row in enumerate(selected):
        try:
            receipt = validate_source_read_receipt_v4(row.source_read_receipt.receipt)
        except SourceReadReceiptV4Error as exc:
            raise TrainerSourceProvenanceLedgerV4ValidationError(
                "source_provenance_v4_row_receipt_revalidation_failed"
            ) from exc
        receipt_mapping = receipt.receipt
        read_evidence = cast(dict[str, Any], receipt_mapping["read_evidence"])
        finality = cast(dict[str, Any], receipt_mapping["finality_evidence"])
        if row.selected_ordinal != expected_ordinal:
            _integrity_error("source_provenance_v4_row_order_invalid")
        exact_row_bytes = exact_source_bytes[row.byte_start : row.byte_end_exclusive]
        if (
            exact_row_bytes != row._exact_payload_bytes
            or _sha256_bytes(exact_row_bytes) != row.exact_payload_sha256
            or len(exact_row_bytes) != row.exact_payload_byte_count
            or _address_material(row.source_payload_address)["payload_sha256"]
            != row.exact_payload_sha256
        ):
            _integrity_error("source_provenance_v4_row_source_slice_invalid")
        row_address = _owned_store_put(
            store,
            exact_row_bytes,
            expected_sha256=row.exact_payload_sha256,
            expected_byte_count=row.exact_payload_byte_count,
        )
        rows.append(
            {
                "selected_ordinal": row.selected_ordinal,
                "source_index": row.source_index,
                "byte_start": row.byte_start,
                "byte_end_exclusive": row.byte_end_exclusive,
                "exact_payload_sha256": row.exact_payload_sha256,
                "exact_payload_byte_count": row.exact_payload_byte_count,
                "source_payload_cas_address": row_address,
                "candle_id": row.candle_id,
                "candle_open_time_ms": row.candle_open_time_ms,
                "candle_close_time_ms": row.candle_close_time_ms,
                "producer_event_time_ms": row.producer_event_time_ms,
                "ingested_at_ms": row.ingested_at_ms,
                "available_at_ms": row.available_at_ms,
                "source": row.source,
                "source_sequence_id": row.source_sequence_id,
                "raw_payload_hash": row.raw_payload_hash,
                "is_backfilled": row.is_backfilled,
                "source_read_receipt_schema_version": receipt.schema_version,
                "source_read_receipt_sha256": receipt.receipt_sha256,
                "source_read_receipt_json": receipt.receipt_json,
                "economic_event_time": receipt_mapping["economic_event_time"],
                "producer_event_time": receipt_mapping["producer_event_time"],
                "ingested_at": receipt_mapping["ingested_at"],
                "available_at": receipt_mapping["available_at"],
                "consumer_observed_at": receipt_mapping["consumer_observed_at"],
                "feature_cutoff": receipt_mapping["feature_cutoff"],
                "read_completed_at": read_evidence["read_completed_at"],
                "finality_cutoff": finality["finality_cutoff"],
                "finality_verified_at": finality["finality_verified_at"],
            }
        )

    source_material: dict[str, object] = {
        "capture_schema_version": typed_capture.schema_version,
        "source_key": typed_capture.source_key,
        "source_key_sha256": typed_capture.source_key_sha256,
        "source_key_version": typed_capture.source_key_version,
        "atomic_batch_id": typed_capture.atomic_batch_id,
        "atomic_batch_material_json": typed_capture.atomic_batch_material_json,
        "atomic_batch_material_sha256": typed_capture.atomic_batch_material_sha256,
        "atomic_batch_material_byte_count": len(atomic_bytes),
        "atomic_server_time_seconds": typed_capture.atomic_server_time_seconds,
        "atomic_server_time_microseconds": typed_capture.atomic_server_time_microseconds,
        "atomic_server_observed_at": typed_capture.atomic_server_observed_at,
        "source_pttl_ms": typed_capture.source_pttl_ms,
        "consumer_observed_at": typed_capture.consumer_observed_at,
        "consumer_observed_at_ms": typed_capture.consumer_observed_at_ms,
        "full_source_payload": source_address,
    }
    manifest_material: dict[str, object] = {
        "schema_version": CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION,
        "exact_manifest_json": typed_capture.suffix_manifest_json,
        "exact_manifest_sha256": manifest_sha,
        "exact_manifest_byte_count": len(manifest_bytes),
        "manifest_cas_address": manifest_address,
        "suffix_digest_material_json": typed_capture.suffix_digest_material_json,
        "suffix_digest_sha256": typed_capture.suffix_digest_sha256,
        "raw_row_count": typed_capture.raw_row_count,
        "selected_source_start_index": typed_capture.selected_source_start_index,
        "selected_source_end_index_exclusive": (typed_capture.selected_source_end_index_exclusive),
        "selected_row_count": typed_capture.selected_row_count,
        "selected_candle_ids": list(typed_capture.selected_candle_ids),
    }
    try:
        final_source_readback = typed_capture.exact_full_source_payload_bytes
        final_manifest_readback = typed_capture.suffix_manifest_json
        final_selected = typed_capture.selected_candles
    except CanonicalOhlcvAtomicCaptureError as exc:
        raise TrainerSourceProvenanceLedgerV4ValidationError(
            "source_provenance_v4_p0b_capture_final_revalidation_failed"
        ) from exc
    if (
        final_source_readback != exact_source_bytes
        or final_manifest_readback != manifest_bytes.decode("ascii")
        or tuple(row.exact_payload_sha256 for row in final_selected)
        != tuple(row["exact_payload_sha256"] for row in rows)
    ):
        _integrity_error("source_provenance_v4_p0b_capture_changed_during_pin")
    return {
        "schema_version": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_REPLAY_SCHEMA_VERSION,
        "trainer_run_id": trainer_run_id,
        "trainer_cycle_id": trainer_cycle_id,
        "ledger_owned_store": _owned_store_material(),
        "source_capture": source_material,
        "suffix_manifest": manifest_material,
        "ordered_rows": rows,
        "temporal_semantics": _temporal_semantics(),
        **{name: False for name in _DOWNSTREAM_FLAG_FIELDS},
    }


def _replay_material_from_record(record: dict[str, Any]) -> dict[str, object]:
    return {
        "schema_version": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_REPLAY_SCHEMA_VERSION,
        "trainer_run_id": record["trainer_run_id"],
        "trainer_cycle_id": record["trainer_cycle_id"],
        "ledger_owned_store": record["ledger_owned_store"],
        "source_capture": record["source_capture"],
        "suffix_manifest": record["suffix_manifest"],
        "ordered_rows": record["ordered_rows"],
        "temporal_semantics": record["temporal_semantics"],
        **{name: record[name] for name in _DOWNSTREAM_FLAG_FIELDS},
    }


def _expected_atomic_batch_material(
    source: dict[str, Any],
    source_address: dict[str, Any],
) -> dict[str, object]:
    """Rebuild every P0-A field that P0-B embedded in its capture."""

    return {
        "consumer_eligible": False,
        "downstream_status": ATOMIC_REDIS_SOURCE_READ_DOWNSTREAM_STATUS,
        "evidence_classification": ATOMIC_REDIS_SOURCE_READ_EVIDENCE_CLASSIFICATION,
        "ledger_receipt_emitted": False,
        "live_execution_authorized": False,
        "paper_provenance_only": True,
        "read_only": True,
        "redis_payload_read_operation": "GETRANGE_INCLUSIVE_CAP_PLUS_ONE",
        "redis_transaction_command_order_per_key": ["TYPE", "GETRANGE", "PTTL"],
        "max_aggregate_payload_bytes": MAX_AGGREGATE_PAYLOAD_BYTES,
        "max_batch_materialized_payload_bytes": MAX_BATCH_MATERIALIZED_PAYLOAD_BYTES,
        "max_range_reply_bytes": MAX_RANGE_REPLY_BYTES,
        "max_source_keys_per_batch": MAX_SOURCE_KEYS_PER_BATCH,
        "max_source_payload_bytes": MAX_SOURCE_PAYLOAD_BYTES,
        "results": [
            {
                "consumer_eligible": False,
                "ledger_receipt_emitted": False,
                "live_execution_authorized": False,
                "payload_byte_count": source_address["payload_byte_count"],
                "payload_sha256": source_address["payload_sha256"],
                "paper_provenance_only": True,
                "present": True,
                "pttl_ms": source["source_pttl_ms"],
                "read_only": True,
                "redis_type": "string",
                "schema_version": ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION,
                "server_time_clock_semantics": REDIS_TIME_CLOCK_SEMANTICS,
                "server_time_is_consumer_observed_at": False,
                "source_finality_attested": False,
                "source_key": source["source_key"],
                "source_key_sha256": source["source_key_sha256"],
                "source_schema_attested": False,
                "transport_authenticity_attested": False,
            }
        ],
        "schema_version": ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION,
        "server_observed_at": source["atomic_server_observed_at"],
        "server_time_clock_semantics": REDIS_TIME_CLOCK_SEMANTICS,
        "server_time_is_consumer_observed_at": False,
        "server_time_microseconds": source["atomic_server_time_microseconds"],
        "server_time_seconds": source["atomic_server_time_seconds"],
        "source_finality_attested": False,
        "source_schema_attested": False,
        "total_payload_byte_count": source_address["payload_byte_count"],
        "transport_authenticity_attested": False,
    }


def _validate_source_and_manifest(record: dict[str, Any]) -> None:
    source = _exact_object(
        record["source_capture"],
        _SOURCE_FIELDS,
        reason="source_provenance_v4_source_fields_invalid",
    )
    manifest_record = _exact_object(
        record["suffix_manifest"],
        _MANIFEST_FIELDS,
        reason="source_provenance_v4_manifest_fields_invalid",
    )
    source_address = _validate_address(source["full_source_payload"])
    manifest_address = _validate_address(manifest_record["manifest_cas_address"])
    if (
        source["capture_schema_version"] != CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION
        or type(source["source_key"]) is not str
        or not source["source_key"].isascii()
        or source["source_key_sha256"] != _sha256_bytes(source["source_key"].encode("ascii"))
        or source["source_key_version"] != source["atomic_batch_id"]
        or type(source["atomic_batch_material_json"]) is not str
        or type(source["atomic_batch_material_byte_count"]) is not int
        or type(source["atomic_server_time_seconds"]) is not int
        or type(source["atomic_server_time_microseconds"]) is not int
        or not 0 <= source["atomic_server_time_microseconds"] <= 999_999
        or type(source["source_pttl_ms"]) is not int
        or source["source_pttl_ms"] < -1
        or type(source["consumer_observed_at_ms"]) is not int
    ):
        _integrity_error("source_provenance_v4_source_identity_invalid")
    try:
        atomic_bytes = source["atomic_batch_material_json"].encode("ascii", errors="strict")
    except UnicodeEncodeError:
        _integrity_error("source_provenance_v4_atomic_material_invalid")
    atomic_sha = _sha256_bytes(atomic_bytes)
    if (
        source["atomic_batch_material_sha256"] != atomic_sha
        or source["atomic_batch_material_byte_count"] != len(atomic_bytes)
        or source["atomic_batch_id"] != f"trainer_atomic_redis_source_read_v2_{atomic_sha}"
    ):
        _integrity_error("source_provenance_v4_atomic_material_invalid")
    atomic_material = _parse_json_object(
        atomic_bytes,
        max_bytes=MAX_LEDGER_ENTRY_BYTES,
    )
    atomic_results = atomic_material.get("results")
    if (
        atomic_material != _expected_atomic_batch_material(source, source_address)
        or type(atomic_results) is not list
        or len(atomic_results) != 1
        or type(atomic_results[0]) is not dict
        or cast(dict[str, Any], atomic_results[0]).get("source_key") != source["source_key"]
        or cast(dict[str, Any], atomic_results[0]).get("source_key_sha256")
        != source["source_key_sha256"]
        or cast(dict[str, Any], atomic_results[0]).get("payload_sha256")
        != source_address["payload_sha256"]
        or cast(dict[str, Any], atomic_results[0]).get("payload_byte_count")
        != source_address["payload_byte_count"]
        or atomic_material.get("server_time_seconds") != source["atomic_server_time_seconds"]
        or atomic_material.get("server_time_microseconds")
        != source["atomic_server_time_microseconds"]
        or atomic_material.get("server_observed_at") != source["atomic_server_observed_at"]
    ):
        _integrity_error("source_provenance_v4_atomic_source_binding_invalid")
    consumer_clock = _parse_clock(
        source["consumer_observed_at"],
        reason="source_provenance_v4_consumer_observed_at_invalid",
    )
    server_clock = _parse_clock(
        source["atomic_server_observed_at"],
        reason="source_provenance_v4_atomic_server_clock_invalid",
    )
    try:
        expected_server = _EPOCH + timedelta(
            seconds=source["atomic_server_time_seconds"],
            microseconds=source["atomic_server_time_microseconds"],
        )
    except (OverflowError, ValueError):
        _integrity_error("source_provenance_v4_atomic_server_clock_invalid")
    if (
        server_clock != expected_server
        or _clock_to_ms(consumer_clock) != source["consumer_observed_at_ms"]
        or not _is_sha256(source_address["payload_sha256"])
    ):
        _integrity_error("source_provenance_v4_source_clock_binding_invalid")

    if manifest_record["schema_version"] != CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION:
        _integrity_error("source_provenance_v4_manifest_schema_invalid")
    if type(manifest_record["exact_manifest_json"]) is not str:
        _integrity_error("source_provenance_v4_manifest_material_invalid")
    try:
        manifest_bytes = manifest_record["exact_manifest_json"].encode("ascii", errors="strict")
    except UnicodeEncodeError:
        _integrity_error("source_provenance_v4_manifest_material_invalid")
    manifest_sha = _sha256_bytes(manifest_bytes)
    if type(manifest_record["suffix_digest_material_json"]) is not str:
        _integrity_error("source_provenance_v4_manifest_material_invalid")
    try:
        suffix_digest_bytes = manifest_record["suffix_digest_material_json"].encode(
            "ascii", errors="strict"
        )
    except UnicodeEncodeError:
        _integrity_error("source_provenance_v4_manifest_material_invalid")
    if (
        manifest_record["exact_manifest_sha256"] != manifest_sha
        or manifest_record["exact_manifest_byte_count"] != len(manifest_bytes)
        or manifest_address["payload_sha256"] != manifest_sha
        or manifest_address["payload_byte_count"] != len(manifest_bytes)
        or manifest_record["suffix_digest_sha256"] != _sha256_bytes(suffix_digest_bytes)
    ):
        _integrity_error("source_provenance_v4_manifest_material_invalid")
    manifest = _exact_object(
        _parse_json_object(manifest_bytes, max_bytes=MAX_LEDGER_ENTRY_BYTES),
        _P0B_MANIFEST_FIELDS,
        reason="source_provenance_v4_exact_manifest_fields_invalid",
    )
    manifest_rows = manifest.get("selected_rows")
    if (
        type(manifest_rows) is not list
        or any(type(row) is not dict for row in manifest_rows)
        or type(manifest_record["raw_row_count"]) is not int
        or manifest_record["raw_row_count"] <= 0
        or type(manifest_record["selected_source_start_index"]) is not int
        or manifest_record["selected_source_start_index"] < 0
        or type(manifest_record["selected_source_end_index_exclusive"]) is not int
        or manifest_record["selected_source_end_index_exclusive"] <= 0
        or type(manifest_record["selected_row_count"]) is not int
        or manifest_record["selected_row_count"] <= 0
        or type(manifest_record["selected_candle_ids"]) is not list
        or any(type(value) is not str for value in manifest_record["selected_candle_ids"])
        or manifest_record["selected_source_end_index_exclusive"]
        - manifest_record["selected_source_start_index"]
        != manifest_record["selected_row_count"]
        or manifest_record["raw_row_count"] < manifest_record["selected_source_end_index_exclusive"]
        or len(manifest_rows) != manifest_record["selected_row_count"]
        or len(manifest_record["selected_candle_ids"]) != manifest_record["selected_row_count"]
    ):
        _integrity_error("source_provenance_v4_manifest_selection_invalid")
    for row in manifest_rows:
        _exact_object(
            row,
            _P0B_MANIFEST_ROW_FIELDS,
            reason="source_provenance_v4_exact_manifest_row_fields_invalid",
        )
    suffix_material = _exact_object(
        _parse_json_object(
            suffix_digest_bytes,
            max_bytes=MAX_LEDGER_ENTRY_BYTES,
        ),
        _SUFFIX_DIGEST_FIELDS,
        reason="source_provenance_v4_suffix_digest_fields_invalid",
    )
    suffix_rows = suffix_material.get("ordered_selected_rows")
    if type(suffix_rows) is not list or len(suffix_rows) != manifest_record["selected_row_count"]:
        _integrity_error("source_provenance_v4_suffix_digest_rows_invalid")
    for row in suffix_rows:
        _exact_object(
            row,
            _SUFFIX_DIGEST_ROW_FIELDS,
            reason="source_provenance_v4_suffix_digest_row_fields_invalid",
        )
    if (
        manifest.get("schema_version") != CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION
        or manifest.get("evidence_classification")
        != CANONICAL_OHLCV_ATOMIC_CAPTURE_EVIDENCE_CLASSIFICATION
        or manifest.get("downstream_status") != CANONICAL_OHLCV_ATOMIC_CAPTURE_DOWNSTREAM_STATUS
        or manifest.get("source_key") != source["source_key"]
        or manifest.get("source_key_sha256") != source["source_key_sha256"]
        or manifest.get("source_key_version") != source["source_key_version"]
        or manifest.get("atomic_batch_id") != source["atomic_batch_id"]
        or manifest.get("atomic_batch_material_sha256") != source["atomic_batch_material_sha256"]
        or manifest.get("atomic_batch_material_json") != source["atomic_batch_material_json"]
        or manifest.get("atomic_server_time_seconds") != source["atomic_server_time_seconds"]
        or manifest.get("atomic_server_time_microseconds")
        != source["atomic_server_time_microseconds"]
        or manifest.get("atomic_server_observed_at") != source["atomic_server_observed_at"]
        or manifest.get("source_pttl_ms") != source["source_pttl_ms"]
        or manifest.get("consumer_observed_at") != source["consumer_observed_at"]
        or manifest.get("consumer_observed_at_ms") != source["consumer_observed_at_ms"]
        or manifest.get("full_source_payload_cas_address") != source_address
        or manifest.get("suffix_digest_material_json")
        != manifest_record["suffix_digest_material_json"]
        or manifest.get("suffix_digest_sha256") != manifest_record["suffix_digest_sha256"]
        or any(manifest.get(name) is not False for name in _DOWNSTREAM_FLAG_FIELDS)
        or manifest.get("durable_ledger_appended") is not False
        or suffix_material["source_key"] != source["source_key"]
        or suffix_material["source_key_version"] != source["source_key_version"]
        or suffix_material["full_source_payload_sha256"] != source_address["payload_sha256"]
        or suffix_material["full_source_payload_byte_count"] != source_address["payload_byte_count"]
        or suffix_material["binding_selection_sha256"] != manifest["binding_selection_sha256"]
        or suffix_material["selected_candle_id_chain_sha256"]
        != manifest["selected_candle_id_chain_sha256"]
        or suffix_material["selected_source_start_index"]
        != manifest_record["selected_source_start_index"]
        or suffix_material["selected_source_end_index_exclusive"]
        != manifest_record["selected_source_end_index_exclusive"]
        or suffix_material["selected_row_count"] != manifest_record["selected_row_count"]
    ):
        _integrity_error("source_provenance_v4_manifest_source_binding_invalid")
    for key in (
        "raw_row_count",
        "selected_source_start_index",
        "selected_source_end_index_exclusive",
        "selected_row_count",
        "selected_candle_ids",
    ):
        manifest_value = (
            [cast(dict[str, Any], row).get("candle_id") for row in manifest_rows]
            if key == "selected_candle_ids"
            else manifest.get(key)
        )
        if manifest_record[key] != manifest_value:
            _integrity_error("source_provenance_v4_manifest_selection_binding_invalid")


def _validate_rows(record: dict[str, Any]) -> None:
    source = cast(dict[str, Any], record["source_capture"])
    source_key_parts = cast(str, source["source_key"]).split(":")
    if (
        len(source_key_parts) != 6
        or source_key_parts[:4] != ["v2", "market", "ohlcv_closed", "binance"]
        or not source_key_parts[4]
        or not source_key_parts[5]
    ):
        _integrity_error("source_provenance_v4_canonical_source_key_invalid")
    capture_symbol = source_key_parts[4]
    capture_timeframe = source_key_parts[5]
    manifest_record = cast(dict[str, Any], record["suffix_manifest"])
    manifest = _parse_json_object(
        cast(str, manifest_record["exact_manifest_json"]).encode("ascii"),
        max_bytes=MAX_LEDGER_ENTRY_BYTES,
    )
    manifest_rows = manifest.get("selected_rows")
    suffix_material = _parse_json_object(
        cast(str, manifest_record["suffix_digest_material_json"]).encode("ascii"),
        max_bytes=MAX_LEDGER_ENTRY_BYTES,
    )
    suffix_rows = suffix_material.get("ordered_selected_rows")
    rows = record["ordered_rows"]
    if (
        type(rows) is not list
        or type(manifest_rows) is not list
        or type(suffix_rows) is not list
        or len(rows) != manifest_record["selected_row_count"]
        or len(manifest_rows) != len(rows)
        or len(suffix_rows) != len(rows)
        or not rows
    ):
        _integrity_error("source_provenance_v4_ordered_rows_invalid")
    previous_close: int | None = None
    previous_byte_end: int | None = None
    for ordinal, (raw_row, raw_manifest_row, raw_suffix_row) in enumerate(
        zip(rows, manifest_rows, suffix_rows, strict=True)
    ):
        row = _exact_object(
            raw_row,
            _ROW_FIELDS,
            reason="source_provenance_v4_row_fields_invalid",
        )
        if type(raw_manifest_row) is not dict:
            _integrity_error("source_provenance_v4_manifest_row_invalid")
        manifest_row = cast(dict[str, Any], raw_manifest_row)
        if type(raw_suffix_row) is not dict:
            _integrity_error("source_provenance_v4_suffix_digest_row_invalid")
        suffix_row = cast(dict[str, Any], raw_suffix_row)
        address = _validate_address(row["source_payload_cas_address"])
        integer_fields = (
            "selected_ordinal",
            "source_index",
            "byte_start",
            "byte_end_exclusive",
            "exact_payload_byte_count",
            "candle_open_time_ms",
            "candle_close_time_ms",
            "producer_event_time_ms",
            "ingested_at_ms",
            "available_at_ms",
        )
        if any(type(row[name]) is not int for name in integer_fields):
            _integrity_error("source_provenance_v4_row_integer_invalid")
        if (
            row["selected_ordinal"] != ordinal
            or row["source_index"] != manifest_record["selected_source_start_index"] + ordinal
            or row["byte_start"] < 0
            or row["byte_end_exclusive"] <= row["byte_start"]
            or row["byte_end_exclusive"]
            > cast(dict[str, Any], source["full_source_payload"])["payload_byte_count"]
            or row["exact_payload_byte_count"] != row["byte_end_exclusive"] - row["byte_start"]
            or row["exact_payload_byte_count"] <= 0
            or not _is_sha256(row["exact_payload_sha256"])
            or address["payload_sha256"] != row["exact_payload_sha256"]
            or address["payload_byte_count"] != row["exact_payload_byte_count"]
            or type(row["candle_id"]) is not str
            or type(row["source"]) is not str
            or type(row["source_sequence_id"]) is not str
            or type(row["raw_payload_hash"]) is not str
            or not _is_sha256(row["raw_payload_hash"])
            or type(row["is_backfilled"]) is not bool
            or row["source_read_receipt_schema_version"] != SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION
            or not _is_sha256(row["source_read_receipt_sha256"])
            or type(row["source_read_receipt_json"]) is not str
        ):
            _integrity_error("source_provenance_v4_row_identity_invalid")
        if (
            row["candle_id"] != manifest_record["selected_candle_ids"][ordinal]
            or any(
                row[name] != manifest_row.get(name)
                for name in (
                    "selected_ordinal",
                    "source_index",
                    "byte_start",
                    "byte_end_exclusive",
                    "exact_payload_sha256",
                    "exact_payload_byte_count",
                    "candle_id",
                    "candle_open_time_ms",
                    "candle_close_time_ms",
                    "producer_event_time_ms",
                    "ingested_at_ms",
                    "available_at_ms",
                    "source",
                    "source_sequence_id",
                    "raw_payload_hash",
                    "is_backfilled",
                )
            )
            or manifest_row.get("source_payload_cas_address") != address
            or any(
                row[name] != suffix_row.get(name)
                for name in (
                    "selected_ordinal",
                    "source_index",
                    "byte_start",
                    "byte_end_exclusive",
                    "exact_payload_sha256",
                    "exact_payload_byte_count",
                    "candle_id",
                    "candle_open_time_ms",
                    "candle_close_time_ms",
                    "source_sequence_id",
                    "raw_payload_hash",
                )
            )
            or row["source_read_receipt_sha256"] != suffix_row.get("source_read_receipt_sha256")
        ):
            _integrity_error("source_provenance_v4_row_manifest_binding_invalid")
        try:
            receipt = validate_source_read_receipt_v4(
                _parse_json_object(
                    row["source_read_receipt_json"].encode("ascii"),
                    max_bytes=MAX_LEDGER_ENTRY_BYTES,
                )
            )
        except (SourceReadReceiptV4Error, UnicodeEncodeError) as exc:
            raise TrainerSourceProvenanceLedgerV4IntegrityError(
                "source_provenance_v4_row_receipt_invalid"
            ) from exc
        receipt_mapping = receipt.receipt
        read_evidence = cast(dict[str, Any], receipt_mapping["read_evidence"])
        finality = cast(dict[str, Any], receipt_mapping["finality_evidence"])
        if (
            receipt.receipt_sha256 != row["source_read_receipt_sha256"]
            or manifest_row.get("source_read_receipt_v4") != receipt_mapping
            or receipt_mapping["payload_sha256"] != row["exact_payload_sha256"]
            or receipt_mapping["payload_byte_count"] != row["exact_payload_byte_count"]
            or receipt_mapping["payload_type"] != CANONICAL_OHLCV_ROW_PAYLOAD_TYPE
            or receipt_mapping["source_label"]
            != (f"ohlcv_closed:binance:{capture_symbol}:" f"{capture_timeframe}:{row['candle_id']}")
            or any(
                row[field_name] != receipt_mapping[field_name]
                for field_name in (
                    "economic_event_time",
                    "producer_event_time",
                    "ingested_at",
                    "available_at",
                    "consumer_observed_at",
                    "feature_cutoff",
                )
            )
            or row["read_completed_at"] != read_evidence["read_completed_at"]
            or row["finality_cutoff"] != finality["finality_cutoff"]
            or row["finality_verified_at"] != finality["finality_verified_at"]
            or read_evidence["read_locator_type"] != "REDIS_VERSIONED_VALUE"
            or read_evidence["read_locator_version"] != source["atomic_batch_id"]
            or read_evidence["read_locator"]
            != (f"{source['source_key']}@bytes:" f"{row['byte_start']}-{row['byte_end_exclusive']}")
            or finality["verifier"] != CANONICAL_OHLCV_FINALITY_VERIFIER
            or row["consumer_observed_at"] != source["consumer_observed_at"]
            or row["economic_event_time"] != _ms_to_clock(row["candle_close_time_ms"])
            or row["producer_event_time"] != _ms_to_clock(row["producer_event_time_ms"])
            or row["ingested_at"] != _ms_to_clock(row["ingested_at_ms"])
            or row["available_at"] != _ms_to_clock(row["available_at_ms"])
            or row["feature_cutoff"] != row["economic_event_time"]
            or row["finality_cutoff"] != row["economic_event_time"]
        ):
            _integrity_error("source_provenance_v4_row_receipt_binding_invalid")
        economic = _parse_clock(
            row["economic_event_time"], reason="source_provenance_v4_economic_time_invalid"
        )
        producer = _parse_clock(
            row["producer_event_time"], reason="source_provenance_v4_producer_time_invalid"
        )
        ingested = _parse_clock(
            row["ingested_at"], reason="source_provenance_v4_ingested_at_invalid"
        )
        available = _parse_clock(
            row["available_at"], reason="source_provenance_v4_available_at_invalid"
        )
        observed = _parse_clock(
            row["consumer_observed_at"],
            reason="source_provenance_v4_consumer_observed_at_invalid",
        )
        if not economic <= producer <= ingested <= available <= observed:
            _integrity_error("source_provenance_v4_point_in_time_order_invalid")
        if (
            row["candle_open_time_ms"] >= row["candle_close_time_ms"]
            or previous_byte_end is not None
            and row["byte_start"] <= previous_byte_end
            or previous_close is not None
            and row["candle_open_time_ms"] != previous_close + 1
        ):
            _integrity_error("source_provenance_v4_candle_order_invalid")
        previous_close = row["candle_close_time_ms"]
        previous_byte_end = row["byte_end_exclusive"]


def _validate_entry_record(record: dict[str, Any]) -> None:
    if frozenset(record) != _ENTRY_FIELDS:
        _integrity_error("source_provenance_v4_entry_fields_invalid")
    if (
        record["schema_version"] != TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION
        or record["evidence_classification"]
        != TRAINER_SOURCE_PROVENANCE_LEDGER_V4_EVIDENCE_CLASSIFICATION
        or record["downstream_status"] != TRAINER_SOURCE_PROVENANCE_LEDGER_V4_DOWNSTREAM_STATUS
        or record["ledger_namespace"] != TRAINER_SOURCE_PROVENANCE_LEDGER_V4_NAMESPACE
        or type(record["ledger_sequence"]) is not int
        or record["ledger_sequence"] <= 0
        or not _is_sha256(record["previous_entry_sha256"])
        or not _is_sha256(record["cycle_identity_sha256"])
        or not _is_sha256(record["replay_identity_sha256"])
        or not _is_sha256(record["entry_sha256"])
        or any(record[name] is not False for name in _DOWNSTREAM_FLAG_FIELDS)
    ):
        _integrity_error("source_provenance_v4_entry_contract_invalid")
    if not _is_valid_id(record["trainer_run_id"]) or not _is_valid_id(record["trainer_cycle_id"]):
        _integrity_error("source_provenance_v4_persisted_run_cycle_id_invalid")
    run_id = cast(str, record["trainer_run_id"])
    cycle_id = cast(str, record["trainer_cycle_id"])
    if record["cycle_identity_sha256"] != _cycle_identity(run_id, cycle_id):
        _integrity_error("source_provenance_v4_cycle_identity_invalid")
    temporal = _exact_object(
        record["temporal_semantics"],
        _TEMPORAL_FIELDS,
        reason="source_provenance_v4_temporal_semantics_invalid",
    )
    if temporal != _temporal_semantics():
        _integrity_error("source_provenance_v4_temporal_semantics_invalid")
    _validate_owned_store_material(record["ledger_owned_store"])
    _validate_source_and_manifest(record)
    _validate_rows(record)
    recorded_at = _parse_clock(
        record["ledger_recorded_at"], reason="source_provenance_v4_recorded_at_invalid"
    )
    consumer_at = _parse_clock(
        cast(dict[str, Any], record["source_capture"])["consumer_observed_at"],
        reason="source_provenance_v4_consumer_observed_at_invalid",
    )
    if recorded_at < consumer_at:
        _integrity_error("source_provenance_v4_recorded_before_source_read")
    expected_replay = _stable_sha256(_replay_material_from_record(record))
    if record["replay_identity_sha256"] != expected_replay:
        _integrity_error("source_provenance_v4_replay_identity_invalid")
    material_without_hash = {key: value for key, value in record.items() if key != "entry_sha256"}
    if record["entry_sha256"] != _stable_sha256(material_without_hash):
        _integrity_error("source_provenance_v4_entry_sha256_invalid")


def _owned_store_get(
    store: ImmutableSourcePayloadStore,
    address_value: object,
    *,
    reason: str,
) -> bytes:
    address = _validate_address(address_value)
    try:
        payload = store.get(
            cast(str, address["payload_sha256"]),
            expected_byte_count=cast(int, address["payload_byte_count"]),
        )
    except SourcePayloadStoreError as exc:
        raise TrainerSourceProvenanceLedgerV4IntegrityError(reason) from exc
    if (
        _sha256_bytes(payload) != address["payload_sha256"]
        or len(payload) != address["payload_byte_count"]
    ):
        _integrity_error(reason)
    return payload


def _expected_p0b_suffix_and_manifest(
    record: dict[str, Any],
    *,
    window: ValidatedOHLCVClosedWindow,
    binding: FullContiguousCoreInputBinding,
) -> tuple[str, dict[str, object]]:
    """Re-derive P0-B's nested material from durable P0-C evidence."""

    source = cast(dict[str, Any], record["source_capture"])
    source_address = cast(dict[str, Any], source["full_source_payload"])
    rows = cast(list[dict[str, Any]], record["ordered_rows"])
    suffix_material: dict[str, object] = {
        "schema_version": CANONICAL_OHLCV_SUFFIX_DIGEST_SCHEMA_VERSION,
        "source_key": source["source_key"],
        "source_key_version": source["source_key_version"],
        "full_source_payload_sha256": source_address["payload_sha256"],
        "full_source_payload_byte_count": source_address["payload_byte_count"],
        "binding_selection_sha256": binding.selection_sha256,
        "selected_candle_id_chain_sha256": binding.selected_candle_id_chain_sha256,
        "selected_source_start_index": binding.selected_source_start_index,
        "selected_source_end_index_exclusive": (binding.selected_source_end_index_exclusive),
        "selected_row_count": binding.selected_row_count,
        "ordered_selected_rows": [
            {
                "selected_ordinal": row["selected_ordinal"],
                "source_index": row["source_index"],
                "byte_start": row["byte_start"],
                "byte_end_exclusive": row["byte_end_exclusive"],
                "exact_payload_sha256": row["exact_payload_sha256"],
                "exact_payload_byte_count": row["exact_payload_byte_count"],
                "candle_id": row["candle_id"],
                "candle_open_time_ms": row["candle_open_time_ms"],
                "candle_close_time_ms": row["candle_close_time_ms"],
                "source_sequence_id": row["source_sequence_id"],
                "raw_payload_hash": row["raw_payload_hash"],
                "source_read_receipt_sha256": row["source_read_receipt_sha256"],
            }
            for row in rows
        ],
    }
    suffix_json = _canonical_json(suffix_material)
    suffix_sha256 = _sha256_bytes(suffix_json.encode("ascii"))
    excluded_gap_pairs = tuple(
        (gap_index, missing_count)
        for gap_index, missing_count in zip(
            window.gap_indices,
            window.gap_missing_interval_counts,
            strict=True,
        )
        if gap_index <= binding.selected_source_start_index
    )
    selected_internal_gaps = tuple(
        gap_index
        for gap_index in window.gap_indices
        if binding.selected_source_start_index
        < gap_index
        < binding.selected_source_end_index_exclusive
    )
    manifest: dict[str, object] = {
        "schema_version": CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION,
        "evidence_classification": (CANONICAL_OHLCV_ATOMIC_CAPTURE_EVIDENCE_CLASSIFICATION),
        "downstream_status": CANONICAL_OHLCV_ATOMIC_CAPTURE_DOWNSTREAM_STATUS,
        "source_key": source["source_key"],
        "source_key_sha256": source["source_key_sha256"],
        "source_key_version": source["source_key_version"],
        "atomic_batch_id": source["atomic_batch_id"],
        "atomic_batch_material_sha256": source["atomic_batch_material_sha256"],
        "atomic_batch_material_json": source["atomic_batch_material_json"],
        "atomic_server_time_seconds": source["atomic_server_time_seconds"],
        "atomic_server_time_microseconds": source["atomic_server_time_microseconds"],
        "atomic_server_observed_at": source["atomic_server_observed_at"],
        "source_pttl_ms": source["source_pttl_ms"],
        "consumer_observed_at": source["consumer_observed_at"],
        "consumer_observed_at_ms": source["consumer_observed_at_ms"],
        "full_source_payload_cas_address": source_address,
        "raw_row_count": window.row_count,
        "source_gap_indices": list(window.gap_indices),
        "source_gap_missing_interval_counts": list(window.gap_missing_interval_counts),
        "selected_source_start_index": binding.selected_source_start_index,
        "selected_source_end_index_exclusive": (binding.selected_source_end_index_exclusive),
        "selected_row_count": binding.selected_row_count,
        "excluded_prefix_row_count": binding.selected_source_start_index,
        "excluded_prefix_gap_indices": [pair[0] for pair in excluded_gap_pairs],
        "excluded_prefix_gap_missing_interval_counts": [pair[1] for pair in excluded_gap_pairs],
        "selected_internal_gap_indices": list(selected_internal_gaps),
        "tail_missing_interval_count": binding.tail_missing_interval_count,
        "latest_candle_matches_expected_cutoff": (binding.latest_candle_matches_expected_cutoff),
        "binding_selection_sha256": binding.selection_sha256,
        "selected_candle_id_chain_sha256": binding.selected_candle_id_chain_sha256,
        "suffix_digest_material_json": suffix_json,
        "suffix_digest_sha256": suffix_sha256,
        "selected_rows": [
            {
                "selected_ordinal": row["selected_ordinal"],
                "source_index": row["source_index"],
                "byte_start": row["byte_start"],
                "byte_end_exclusive": row["byte_end_exclusive"],
                "exact_payload_sha256": row["exact_payload_sha256"],
                "exact_payload_byte_count": row["exact_payload_byte_count"],
                "source_payload_cas_address": row["source_payload_cas_address"],
                "candle_id": row["candle_id"],
                "candle_open_time_ms": row["candle_open_time_ms"],
                "candle_close_time_ms": row["candle_close_time_ms"],
                "producer_event_time_ms": row["producer_event_time_ms"],
                "ingested_at_ms": row["ingested_at_ms"],
                "available_at_ms": row["available_at_ms"],
                "source": row["source"],
                "source_sequence_id": row["source_sequence_id"],
                "raw_payload_hash": row["raw_payload_hash"],
                "is_backfilled": row["is_backfilled"],
                "source_read_receipt_v4": _parse_json_object(
                    cast(str, row["source_read_receipt_json"]).encode("ascii"),
                    max_bytes=MAX_LEDGER_ENTRY_BYTES,
                ),
            }
            for row in rows
        ],
        "durable_ledger_appended": False,
        **{name: False for name in _DOWNSTREAM_FLAG_FIELDS},
    }
    return suffix_json, manifest


def _verify_record_owned_cas(
    record: dict[str, Any],
    store: ImmutableSourcePayloadStore,
    *,
    expected_store_root: Path,
) -> None:
    _validate_owned_store_material(record["ledger_owned_store"])
    if store.root_path != expected_store_root:
        _integrity_error("source_provenance_v4_owned_cas_root_binding_invalid")
    source = cast(dict[str, Any], record["source_capture"])
    manifest_record = cast(dict[str, Any], record["suffix_manifest"])
    full_source_bytes = _owned_store_get(
        store,
        source["full_source_payload"],
        reason="source_provenance_v4_owned_full_source_cas_invalid",
    )
    manifest_bytes = _owned_store_get(
        store,
        manifest_record["manifest_cas_address"],
        reason="source_provenance_v4_owned_manifest_cas_invalid",
    )
    if manifest_bytes != cast(str, manifest_record["exact_manifest_json"]).encode("ascii"):
        _integrity_error("source_provenance_v4_owned_manifest_bytes_mismatch")
    # Reparse the exact durable manifest on every admission-neutral read.  This
    # repeats duplicate-key and exact nested-field validation independently of
    # the outer ledger envelope.
    durable_manifest = _exact_object(
        _parse_json_object(manifest_bytes, max_bytes=MAX_LEDGER_ENTRY_BYTES),
        _P0B_MANIFEST_FIELDS,
        reason="source_provenance_v4_owned_manifest_fields_invalid",
    )
    if durable_manifest["full_source_payload_cas_address"] != source["full_source_payload"]:
        _integrity_error("source_provenance_v4_owned_manifest_source_mismatch")

    source_parts = cast(str, source["source_key"]).split(":")
    if len(source_parts) != 6:
        _integrity_error("source_provenance_v4_owned_source_key_invalid")
    try:
        window = validate_ohlcv_closed_window(
            full_source_bytes,
            symbol=source_parts[4],
            timeframe=source_parts[5],
        )
    except OHLCVClosedWindowValidationError as exc:
        raise TrainerSourceProvenanceLedgerV4IntegrityError(
            "source_provenance_v4_owned_full_source_schema_invalid"
        ) from exc
    if (
        window.source_key != source["source_key"]
        or window.exact_payload_sha256
        != cast(dict[str, Any], source["full_source_payload"])["payload_sha256"]
        or window.exact_payload_byte_count != len(full_source_bytes)
        or window.row_count != manifest_record["raw_row_count"]
    ):
        _integrity_error("source_provenance_v4_owned_full_source_binding_invalid")
    exact_row_spans = _exact_json_array_element_spans(full_source_bytes)
    if len(exact_row_spans) != window.row_count:
        _integrity_error("source_provenance_v4_owned_source_span_count_invalid")

    rows = cast(list[dict[str, Any]], record["ordered_rows"])
    duration_ms = TIMEFRAME_DURATION_MS.get(source_parts[5])
    observed_at_ms = source["consumer_observed_at_ms"]
    if type(duration_ms) is not int or duration_ms <= 0 or type(observed_at_ms) is not int:
        _integrity_error("source_provenance_v4_owned_selection_clock_invalid")
    expected_latest_close = (observed_at_ms // duration_ms) * duration_ms - 1
    if expected_latest_close < 0:
        _integrity_error("source_provenance_v4_owned_selection_clock_invalid")
    identity_rows = [
        {
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "candle_id": row.candle_id,
            "candle_open_time": row.candle_open_time,
            "candle_close_time": row.candle_close_time,
            "available_at": row.available_at,
        }
        for row in window.rows
    ]
    try:
        binding = bind_full_contiguous_core_ta_input(
            identity_rows,
            expected_symbol=window.symbol,
            timeframe=window.timeframe,
            consumer_observed_at_ms=observed_at_ms,
            expected_latest_finalized_close_time=expected_latest_close,
        )
    except FeatureWindowContractError as exc:
        raise TrainerSourceProvenanceLedgerV4IntegrityError(
            "source_provenance_v4_owned_selection_revalidation_failed"
        ) from exc
    if (
        binding.selected_source_end_index_exclusive != window.row_count
        or binding.tail_missing_interval_count != 0
        or binding.latest_candle_matches_expected_cutoff is not True
        or window.max_available_at > observed_at_ms
        or len(rows) != binding.selected_row_count
        or tuple(row["candle_id"] for row in rows) != binding.selected_candle_ids
    ):
        _integrity_error("source_provenance_v4_owned_selection_binding_invalid")
    expected_suffix_json, expected_manifest = _expected_p0b_suffix_and_manifest(
        record,
        window=window,
        binding=binding,
    )
    if (
        manifest_record["suffix_digest_material_json"] != expected_suffix_json
        or durable_manifest != expected_manifest
    ):
        _integrity_error("source_provenance_v4_owned_manifest_semantic_binding_invalid")

    manifest_rows = cast(list[dict[str, Any]], durable_manifest["selected_rows"])
    for row, manifest_row in zip(rows, manifest_rows, strict=True):
        source_index = cast(int, row["source_index"])
        if not 0 <= source_index < window.row_count:
            _integrity_error("source_provenance_v4_owned_row_source_index_invalid")
        start = cast(int, row["byte_start"])
        end = cast(int, row["byte_end_exclusive"])
        exact_slice = full_source_bytes[start:end]
        if (
            (start, end) != exact_row_spans[source_index]
            or not exact_slice
            or _sha256_bytes(exact_slice) != row["exact_payload_sha256"]
            or len(exact_slice) != row["exact_payload_byte_count"]
        ):
            _integrity_error("source_provenance_v4_owned_row_slice_invalid")
        row_object = _owned_store_get(
            store,
            row["source_payload_cas_address"],
            reason="source_provenance_v4_owned_row_cas_invalid",
        )
        if row_object != exact_slice:
            _integrity_error("source_provenance_v4_owned_row_cas_slice_mismatch")
        if manifest_row["source_payload_cas_address"] != row["source_payload_cas_address"]:
            _integrity_error("source_provenance_v4_owned_row_address_mismatch")
        source_row = window.rows[source_index]
        if (
            source_row.candle_id != row["candle_id"]
            or source_row.candle_open_time != row["candle_open_time_ms"]
            or source_row.candle_close_time != row["candle_close_time_ms"]
            or source_row.event_time != row["producer_event_time_ms"]
            or source_row.ingested_at != row["ingested_at_ms"]
            or source_row.available_at != row["available_at_ms"]
            or source_row.source != row["source"]
            or source_row.source_sequence_id != row["source_sequence_id"]
            or source_row.raw_payload_hash != row["raw_payload_hash"]
            or source_row.is_backfilled is not row["is_backfilled"]
        ):
            _integrity_error("source_provenance_v4_owned_row_source_binding_invalid")


def _parse_entry_line(raw: bytes) -> dict[str, Any]:
    record = _parse_json_object(raw, max_bytes=MAX_LEDGER_ENTRY_BYTES)
    _validate_entry_record(record)
    return record


def _artifact(record: dict[str, Any]) -> TrainerSourceProvenanceLedgerEntryV4:
    entry_json = _canonical_json(record)
    return TrainerSourceProvenanceLedgerEntryV4(
        schema_version=TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION,
        ledger_sequence=cast(int, record["ledger_sequence"]),
        previous_entry_sha256=cast(str, record["previous_entry_sha256"]),
        trainer_run_id=cast(str, record["trainer_run_id"]),
        trainer_cycle_id=cast(str, record["trainer_cycle_id"]),
        cycle_identity_sha256=cast(str, record["cycle_identity_sha256"]),
        replay_identity_sha256=cast(str, record["replay_identity_sha256"]),
        entry_sha256=cast(str, record["entry_sha256"]),
        entry_json=entry_json,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def _append_result(
    entry: TrainerSourceProvenanceLedgerEntryV4,
    *,
    disposition: str,
) -> TrainerSourceProvenanceAppendResultV4:
    return TrainerSourceProvenanceAppendResultV4(
        entry=entry,
        disposition=disposition,
        _construction_token=_APPEND_RESULT_CONSTRUCTION_TOKEN,
    )


def _head_material(*, raw_prefix: bytes, sequence: int, entry_sha256: str) -> dict[str, object]:
    material: dict[str, object] = {
        "schema_version": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_HEAD_SCHEMA_VERSION,
        "ledger_schema_version": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION,
        "ledger_filename": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME,
        "ledger_sequence": sequence,
        "ledger_byte_count": len(raw_prefix),
        "ledger_sha256": _sha256_bytes(raw_prefix),
        "entry_sha256": entry_sha256,
    }
    material["head_sha256"] = _stable_sha256(material)
    return material


def _validate_head(raw: bytes) -> dict[str, Any]:
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
        _integrity_error("source_provenance_v4_head_framing_invalid")
    head = _parse_json_object(raw[:-1], max_bytes=64 * 1024)
    if frozenset(head) != _HEAD_FIELDS:
        _integrity_error("source_provenance_v4_head_fields_invalid")
    if (
        head["schema_version"] != TRAINER_SOURCE_PROVENANCE_LEDGER_V4_HEAD_SCHEMA_VERSION
        or head["ledger_schema_version"] != TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION
        or head["ledger_filename"] != TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME
        or type(head["ledger_sequence"]) is not int
        or head["ledger_sequence"] <= 0
        or type(head["ledger_byte_count"]) is not int
        or head["ledger_byte_count"] <= 0
        or not _is_sha256(head["ledger_sha256"])
        or not _is_sha256(head["entry_sha256"])
        or not _is_sha256(head["head_sha256"])
    ):
        _integrity_error("source_provenance_v4_head_contract_invalid")
    material = {key: value for key, value in head.items() if key != "head_sha256"}
    if head["head_sha256"] != _stable_sha256(material):
        _integrity_error("source_provenance_v4_head_sha256_invalid")
    return head


@dataclass(frozen=True, slots=True)
class _DirectoryBinding:
    parent_fd: int
    name: str
    child_fd: int
    identity: tuple[int, int]


class _VerifiedRootChain:
    """Descriptor-retained lexical root chain with no-follow verification."""

    __slots__ = ("_bindings", "_closed", "_descriptors", "path")

    def __init__(self, path: Path, anchor_fd: int) -> None:
        self.path = path
        self._descriptors = [anchor_fd]
        self._bindings: list[_DirectoryBinding] = []
        self._closed = False

    @property
    def final_fd(self) -> int:
        if self._closed:
            _integrity_error("source_provenance_v4_root_chain_closed")
        return self._descriptors[-1]

    @property
    def identity(self) -> tuple[int, int]:
        details = os.fstat(self.final_fd)
        return (int(details.st_dev), int(details.st_ino))

    def append(self, name: str, *, create: bool) -> None:
        if not name or name in {".", ".."} or "/" in name or "\x00" in name:
            _validation_error("source_provenance_v4_root_component_invalid")
        parent_fd = self.final_fd
        if create:
            try:
                os.mkdir(name, mode=_PRIVATE_DIRECTORY_MODE, dir_fd=parent_fd)
            except FileExistsError:
                pass
            except OSError as exc:
                _durability_error("source_provenance_v4_root_create_failed", cause=exc)
            else:
                _fsync_directory_fd(parent_fd)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            child_fd = os.open(name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise TrainerSourceProvenanceLedgerV4IntegrityError(
                "source_provenance_v4_root_ancestor_or_final_open_failed"
            ) from exc
        try:
            descriptor_stat = os.fstat(child_fd)
            path_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            identity = (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
            if (
                not stat.S_ISDIR(descriptor_stat.st_mode)
                or not stat.S_ISDIR(path_stat.st_mode)
                or identity != (int(path_stat.st_dev), int(path_stat.st_ino))
            ):
                _integrity_error("source_provenance_v4_root_directory_binding_invalid")
        except BaseException:
            os.close(child_fd)
            raise
        self._descriptors.append(child_fd)
        self._bindings.append(
            _DirectoryBinding(
                parent_fd=parent_fd,
                name=name,
                child_fd=child_fd,
                identity=identity,
            )
        )

    def require_private_final(self) -> None:
        descriptor_stat = os.fstat(self.final_fd)
        final = self._bindings[-1]
        path_stat = os.stat(final.name, dir_fd=final.parent_fd, follow_symlinks=False)
        if (
            descriptor_stat.st_uid != os.geteuid()
            or path_stat.st_uid != os.geteuid()
            or stat.S_IMODE(descriptor_stat.st_mode) != _PRIVATE_DIRECTORY_MODE
            or stat.S_IMODE(path_stat.st_mode) != _PRIVATE_DIRECTORY_MODE
        ):
            _integrity_error("source_provenance_v4_root_private_owner_mode_required")

    def verify(self) -> None:
        if self._closed:
            _integrity_error("source_provenance_v4_root_chain_closed")
        for binding in self._bindings:
            try:
                descriptor_stat = os.fstat(binding.child_fd)
                path_stat = os.stat(
                    binding.name,
                    dir_fd=binding.parent_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise TrainerSourceProvenanceLedgerV4IntegrityError(
                    "source_provenance_v4_root_binding_missing"
                ) from exc
            if (
                not stat.S_ISDIR(descriptor_stat.st_mode)
                or not stat.S_ISDIR(path_stat.st_mode)
                or (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino)) != binding.identity
                or (int(path_stat.st_dev), int(path_stat.st_ino)) != binding.identity
            ):
                _integrity_error("source_provenance_v4_root_replaced")
        self.require_private_final()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor in reversed(self._descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        self._descriptors.clear()
        self._bindings.clear()


def _lexical_absolute_root(path: Path) -> Path:
    if not isinstance(path, Path):
        _validation_error("source_provenance_v4_root_exact_path_required")
    raw = os.fspath(path)
    if (
        "\x00" in raw
        or not os.path.isabs(raw)
        or any(component == ".." for component in Path(raw).parts)
    ):
        _validation_error("source_provenance_v4_root_lexical_absolute_required")
    exact = Path(raw)
    if (
        exact == Path(exact.anchor)
        or exact.name in {"", ".", ".."}
        or len(exact.parts) - 1 > _MAX_PATH_COMPONENTS
    ):
        _validation_error("source_provenance_v4_root_path_invalid")
    return exact


def _open_verified_root(path: Path, *, create_final: bool) -> _VerifiedRootChain:
    exact = _lexical_absolute_root(path)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        anchor_fd = os.open(exact.anchor, flags)
    except OSError as exc:
        raise TrainerSourceProvenanceLedgerV4IntegrityError(
            "source_provenance_v4_root_anchor_open_failed"
        ) from exc
    chain = _VerifiedRootChain(exact, anchor_fd)
    try:
        components = exact.parts[1:]
        for index, component in enumerate(components):
            chain.append(
                component,
                create=create_final and index == len(components) - 1,
            )
        chain.verify()
        return chain
    except BaseException:
        chain.close()
        raise


def _validate_regular_file(
    root_fd: int,
    name: str,
    descriptor: int,
    *,
    reason: str,
) -> os.stat_result:
    try:
        descriptor_stat = os.fstat(descriptor)
        path_stat = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except OSError as exc:
        raise TrainerSourceProvenanceLedgerV4IntegrityError(reason) from exc
    if (
        not stat.S_ISREG(descriptor_stat.st_mode)
        or not stat.S_ISREG(path_stat.st_mode)
        or descriptor_stat.st_nlink != 1
        or path_stat.st_nlink != 1
        or descriptor_stat.st_uid != os.geteuid()
        or path_stat.st_uid != os.geteuid()
        or stat.S_IMODE(descriptor_stat.st_mode) != _PRIVATE_FILE_MODE
        or stat.S_IMODE(path_stat.st_mode) != _PRIVATE_FILE_MODE
        or (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
        != (int(path_stat.st_dev), int(path_stat.st_ino))
    ):
        _integrity_error(reason)
    return descriptor_stat


def _read_regular_file(
    root: _VerifiedRootChain,
    name: str,
    *,
    max_bytes: int,
    required: bool,
) -> bytes | None:
    root.verify()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=root.final_fd)
    except FileNotFoundError:
        if required:
            _integrity_error("source_provenance_v4_file_missing")
        return None
    except OSError as exc:
        raise TrainerSourceProvenanceLedgerV4IntegrityError(
            "source_provenance_v4_file_open_failed"
        ) from exc
    try:
        details = _validate_regular_file(
            root.final_fd,
            name,
            descriptor,
            reason="source_provenance_v4_file_identity_invalid",
        )
        if details.st_size < 0 or details.st_size > max_bytes:
            _integrity_error("source_provenance_v4_file_size_invalid")
        initial_change = (int(details.st_mtime_ns), int(details.st_ctime_ns))
        chunks: list[bytes] = []
        remaining = details.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                _integrity_error("source_provenance_v4_file_truncated_during_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            _integrity_error("source_provenance_v4_file_grew_during_read")
        final_details = _validate_regular_file(
            root.final_fd,
            name,
            descriptor,
            reason="source_provenance_v4_file_changed_during_read",
        )
        raw = b"".join(chunks)
        if (
            len(raw) != details.st_size
            or final_details.st_size != details.st_size
            or (int(final_details.st_mtime_ns), int(final_details.st_ctime_ns)) != initial_change
        ):
            _integrity_error("source_provenance_v4_file_changed_during_read")
        root.verify()
        return raw
    except OSError as exc:
        raise TrainerSourceProvenanceLedgerV4IntegrityError(
            "source_provenance_v4_file_read_failed"
        ) from exc
    finally:
        os.close(descriptor)


def _load_state(
    root: _VerifiedRootChain,
    store: ImmutableSourcePayloadStore,
    *,
    expected_store_root: Path,
) -> _LedgerState:
    raw = (
        _read_regular_file(
            root,
            TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME,
            max_bytes=MAX_LEDGER_BYTES,
            required=False,
        )
        or b""
    )
    head_raw = _read_regular_file(
        root,
        TRAINER_SOURCE_PROVENANCE_LEDGER_V4_HEAD_FILENAME,
        max_bytes=64 * 1024,
        required=False,
    )
    if not raw:
        if head_raw is not None:
            _integrity_error("source_provenance_v4_head_without_ledger")
        return _LedgerState(b"", (), (), 0)
    if not raw.endswith(b"\n"):
        _integrity_error("source_provenance_v4_ledger_truncated_or_partial_tail")
    lines = raw.splitlines(keepends=True)
    if not lines or len(lines) > MAX_LEDGER_ENTRIES:
        _integrity_error("source_provenance_v4_ledger_entry_count_invalid")
    records: list[dict[str, Any]] = []
    offsets: list[int] = []
    offset = 0
    previous = TRAINER_SOURCE_PROVENANCE_LEDGER_V4_GENESIS_SHA256
    for sequence, framed in enumerate(lines, start=1):
        if not framed.endswith(b"\n") or framed == b"\n" or b"\r" in framed:
            _integrity_error("source_provenance_v4_ledger_framing_invalid")
        record = _parse_entry_line(framed[:-1])
        _verify_record_owned_cas(
            record,
            store,
            expected_store_root=expected_store_root,
        )
        if record["ledger_sequence"] != sequence or record["previous_entry_sha256"] != previous:
            _integrity_error("source_provenance_v4_hash_chain_invalid")
        records.append(record)
        previous = cast(str, record["entry_sha256"])
        offset += len(framed)
        offsets.append(offset)
    if head_raw is None:
        if len(records) != 1:
            _integrity_error("source_provenance_v4_durable_head_missing")
        return _LedgerState(raw, tuple(records), tuple(offsets), 0)
    head = _validate_head(head_raw)
    committed = cast(int, head["ledger_sequence"])
    if committed > len(records) or len(records) - committed > 1:
        _integrity_error("source_provenance_v4_head_sequence_invalid")
    prefix_end = offsets[committed - 1]
    prefix = raw[:prefix_end]
    if (
        head["ledger_byte_count"] != len(prefix)
        or head["ledger_sha256"] != _sha256_bytes(prefix)
        or head["entry_sha256"] != records[committed - 1]["entry_sha256"]
    ):
        _integrity_error("source_provenance_v4_head_ledger_binding_invalid")
    return _LedgerState(raw, tuple(records), tuple(offsets), committed)


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    written = 0
    while written < len(payload):
        count = os.write(descriptor, view[written:])
        if count <= 0:
            _durability_error("source_provenance_v4_write_made_no_progress")
        written += count


def _fsync_directory_fd(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as exc:
        _durability_error("source_provenance_v4_directory_fsync_failed", cause=exc)


def _fsync_ledger(root: _VerifiedRootChain) -> None:
    root.verify()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(
            TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME,
            flags,
            dir_fd=root.final_fd,
        )
        try:
            _validate_regular_file(
                root.final_fd,
                TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME,
                descriptor,
                reason="source_provenance_v4_ledger_identity_invalid",
            )
            os.fsync(descriptor)
            _validate_regular_file(
                root.final_fd,
                TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME,
                descriptor,
                reason="source_provenance_v4_ledger_changed_during_fsync",
            )
        finally:
            os.close(descriptor)
        root.verify()
    except TrainerSourceProvenanceLedgerV4Error:
        raise
    except OSError as exc:
        _durability_error("source_provenance_v4_ledger_fsync_failed", cause=exc)


def _append_fsync(root: _VerifiedRootChain, payload: bytes) -> None:
    root.verify()
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(
            TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME,
            flags,
            _PRIVATE_FILE_MODE,
            dir_fd=root.final_fd,
        )
        try:
            _validate_regular_file(
                root.final_fd,
                TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME,
                descriptor,
                reason="source_provenance_v4_ledger_identity_invalid",
            )
            with os.fdopen(descriptor, "ab", buffering=0, closefd=False) as stream:
                _write_all(stream.fileno(), payload)
                stream.flush()
                os.fsync(stream.fileno())
            _validate_regular_file(
                root.final_fd,
                TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME,
                descriptor,
                reason="source_provenance_v4_ledger_changed_during_append",
            )
        finally:
            os.close(descriptor)
        _fsync_directory_fd(root.final_fd)
        root.verify()
    except TrainerSourceProvenanceLedgerV4Error:
        raise
    except OSError as exc:
        _durability_error("source_provenance_v4_ledger_append_or_fsync_failed", cause=exc)


def _write_head_atomic(
    root: _VerifiedRootChain,
    head: dict[str, object],
) -> None:
    root.verify()
    payload = _canonical_json(head, max_bytes=64 * 1024).encode("ascii") + b"\n"
    temporary = (
        f".{TRAINER_SOURCE_PROVENANCE_LEDGER_V4_HEAD_FILENAME}."
        f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    replaced = False
    try:
        descriptor = os.open(
            temporary,
            flags,
            _PRIVATE_FILE_MODE,
            dir_fd=root.final_fd,
        )
        try:
            _validate_regular_file(
                root.final_fd,
                temporary,
                descriptor,
                reason="source_provenance_v4_head_temp_identity_invalid",
            )
            with os.fdopen(descriptor, "wb", buffering=0, closefd=False) as stream:
                _write_all(stream.fileno(), payload)
                stream.flush()
                os.fsync(stream.fileno())
            _validate_regular_file(
                root.final_fd,
                temporary,
                descriptor,
                reason="source_provenance_v4_head_temp_changed",
            )
        finally:
            os.close(descriptor)
        root.verify()
        os.replace(
            temporary,
            TRAINER_SOURCE_PROVENANCE_LEDGER_V4_HEAD_FILENAME,
            src_dir_fd=root.final_fd,
            dst_dir_fd=root.final_fd,
        )
        replaced = True
        _fsync_directory_fd(root.final_fd)
        _read_regular_file(
            root,
            TRAINER_SOURCE_PROVENANCE_LEDGER_V4_HEAD_FILENAME,
            max_bytes=64 * 1024,
            required=True,
        )
        root.verify()
    except TrainerSourceProvenanceLedgerV4Error:
        raise
    except OSError as exc:
        _durability_error("source_provenance_v4_head_publish_failed", cause=exc)
    finally:
        if not replaced:
            try:
                os.unlink(temporary, dir_fd=root.final_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _postcommit_readback(
    root: _VerifiedRootChain,
    store: ImmutableSourcePayloadStore,
    *,
    expected_store_root: Path,
    expected_entry_json: str,
    expected_sequence: int,
) -> dict[str, Any]:
    state = _load_state(
        root,
        store,
        expected_store_root=expected_store_root,
    )
    if (
        state.pending_record is not None
        or state.committed_count != len(state.records)
        or state.committed_count != expected_sequence
        or not state.records
        or _canonical_json(state.records[-1]) != expected_entry_json
    ):
        _durability_error("source_provenance_v4_postcommit_readback_mismatch")
    return state.records[-1]


class TrainerSourceProvenanceLedgerV4:
    """Private v4 JSONL ledger rooted at an operator-supplied directory."""

    def __init__(self, root: Path) -> None:
        self.root = _lexical_absolute_root(root)
        self.path = self.root / TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME
        self.head_path = self.root / TRAINER_SOURCE_PROVENANCE_LEDGER_V4_HEAD_FILENAME
        self.lock_path = self.root / TRAINER_SOURCE_PROVENANCE_LEDGER_V4_LOCK_FILENAME
        self.store_root = self.root / TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_ROOT_RELATIVE_PATH
        self._root_identity: tuple[int, int] | None = None
        self._root_identity_lock = threading.Lock()

    def _pin_root_identity(self, root: _VerifiedRootChain) -> None:
        root.verify()
        identity = root.identity
        with self._root_identity_lock:
            if self._root_identity is None:
                self._root_identity = identity
            elif self._root_identity != identity:
                _integrity_error("source_provenance_v4_root_instance_replaced")

    def _open_owned_store(
        self,
        root: _VerifiedRootChain,
    ) -> ImmutableSourcePayloadStore:
        root.verify()
        try:
            store = ImmutableSourcePayloadStore(self.store_root)
        except SourcePayloadIntegrityError as exc:
            raise TrainerSourceProvenanceLedgerV4IntegrityError(
                "source_provenance_v4_owned_cas_root_integrity_invalid"
            ) from exc
        except SourcePayloadStoreError as exc:
            raise TrainerSourceProvenanceLedgerV4DurabilityError(
                "source_provenance_v4_owned_cas_root_open_failed"
            ) from exc
        root.verify()
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(
                TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_ROOT_RELATIVE_PATH,
                flags,
                dir_fd=root.final_fd,
            )
        except OSError as exc:
            raise TrainerSourceProvenanceLedgerV4IntegrityError(
                "source_provenance_v4_owned_cas_root_binding_missing"
            ) from exc
        try:
            descriptor_stat = os.fstat(descriptor)
            path_stat = os.stat(
                TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_ROOT_RELATIVE_PATH,
                dir_fd=root.final_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(descriptor_stat.st_mode)
                or not stat.S_ISDIR(path_stat.st_mode)
                or descriptor_stat.st_uid != os.geteuid()
                or path_stat.st_uid != os.geteuid()
                or stat.S_IMODE(descriptor_stat.st_mode) != _PRIVATE_DIRECTORY_MODE
                or stat.S_IMODE(path_stat.st_mode) != _PRIVATE_DIRECTORY_MODE
                or (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
                != (int(path_stat.st_dev), int(path_stat.st_ino))
            ):
                _integrity_error("source_provenance_v4_owned_cas_root_binding_invalid")
        finally:
            os.close(descriptor)
        if store.root_path != self.store_root:
            _integrity_error("source_provenance_v4_owned_cas_root_path_invalid")
        root.verify()
        return store

    @contextmanager
    def _exclusive_lock(self) -> Iterator[_VerifiedRootChain]:
        root = _open_verified_root(self.root, create_final=True)
        try:
            self._pin_root_identity(root)
        except BaseException:
            root.close()
            raise
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        created = False
        try:
            descriptor = os.open(
                TRAINER_SOURCE_PROVENANCE_LEDGER_V4_LOCK_FILENAME,
                flags,
                _PRIVATE_FILE_MODE,
                dir_fd=root.final_fd,
            )
            created = True
        except FileExistsError:
            try:
                descriptor = os.open(
                    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_LOCK_FILENAME,
                    os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=root.final_fd,
                )
            except OSError as exc:
                root.close()
                _durability_error("source_provenance_v4_lock_open_failed", cause=exc)
        except OSError as exc:
            root.close()
            _durability_error("source_provenance_v4_lock_open_failed", cause=exc)
        try:
            if created:
                _fsync_directory_fd(root.final_fd)
            _validate_regular_file(
                root.final_fd,
                TRAINER_SOURCE_PROVENANCE_LEDGER_V4_LOCK_FILENAME,
                descriptor,
                reason="source_provenance_v4_lock_identity_invalid",
            )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except OSError as exc:
                _durability_error("source_provenance_v4_lock_acquire_failed", cause=exc)
            root.verify()
            _validate_regular_file(
                root.final_fd,
                TRAINER_SOURCE_PROVENANCE_LEDGER_V4_LOCK_FILENAME,
                descriptor,
                reason="source_provenance_v4_lock_changed",
            )
            yield root
            root.verify()
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
                root.close()

    @contextmanager
    def _shared_read_lock(self) -> Iterator[_VerifiedRootChain]:
        """Hold the existing writer lock read-only for a coherent snapshot.

        The strict trainer observer is filesystem-read-only.  It must still
        serialize with ``append_atomic_capture()``, but it must never create or
        open the lock for write merely to verify committed provenance.  The
        writer creates the owner-only lock before any committed ledger can
        exist; absence therefore fails closed rather than being repaired by a
        reader.
        """

        root = _open_verified_root(self.root, create_final=False)
        try:
            self._pin_root_identity(root)
        except BaseException:
            root.close()
            raise
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(
                TRAINER_SOURCE_PROVENANCE_LEDGER_V4_LOCK_FILENAME,
                flags,
                dir_fd=root.final_fd,
            )
        except OSError as exc:
            root.close()
            _durability_error("source_provenance_v4_read_lock_open_failed", cause=exc)
        try:
            _validate_regular_file(
                root.final_fd,
                TRAINER_SOURCE_PROVENANCE_LEDGER_V4_LOCK_FILENAME,
                descriptor,
                reason="source_provenance_v4_read_lock_identity_invalid",
            )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH)
            except OSError as exc:
                _durability_error("source_provenance_v4_read_lock_acquire_failed", cause=exc)
            root.verify()
            _validate_regular_file(
                root.final_fd,
                TRAINER_SOURCE_PROVENANCE_LEDGER_V4_LOCK_FILENAME,
                descriptor,
                reason="source_provenance_v4_read_lock_changed",
            )
            yield root
            root.verify()
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
                root.close()

    def append_atomic_capture(
        self,
        capture: CanonicalOhlcvAtomicReceiptCapture,
        *,
        trainer_run_id: str,
        trainer_cycle_id: str,
        ledger_clock: Callable[[], datetime] | object = lambda: datetime.now(UTC),
    ) -> TrainerSourceProvenanceAppendResultV4:
        """Durably append or exactly replay one validated P0-B capture."""

        run_id = _required_id(trainer_run_id, reason="source_provenance_v4_run_id_invalid")
        cycle_id = _required_id(trainer_cycle_id, reason="source_provenance_v4_cycle_id_invalid")
        with self._exclusive_lock() as root:
            store = self._open_owned_store(root)
            # This is the authoritative P0-B validation and durable pin.  It
            # intentionally occurs after LOCK_EX, not in an earlier preflight.
            replay_material = _capture_replay_material(
                capture,
                store,
                trainer_run_id=run_id,
                trainer_cycle_id=cycle_id,
            )
            replay_identity = _stable_sha256(replay_material)
            cycle_identity = _cycle_identity(run_id, cycle_id)
            source_observed_at = cast(
                str,
                cast(dict[str, object], replay_material["source_capture"])["consumer_observed_at"],
            )
            state = _load_state(
                root,
                store,
                expected_store_root=self.store_root,
            )
            for index, existing in enumerate(state.records):
                if existing["cycle_identity_sha256"] != cycle_identity:
                    continue
                if existing["replay_identity_sha256"] != replay_identity:
                    _conflict_error("source_provenance_v4_conflicting_cycle_replay")
                if index >= state.committed_count:
                    return self._recover_pending(
                        root,
                        store,
                        state,
                        existing,
                    )
                return self._finish_existing(
                    root,
                    store,
                    existing,
                    disposition="EXACT_REPLAY",
                )

            pending = state.pending_record
            if pending is not None:
                _conflict_error("source_provenance_v4_uncommitted_tail_conflict")
            recorded_at = _sample_ledger_clock(
                ledger_clock,
                source_observed_at=source_observed_at,
            )
            sequence = len(state.records) + 1
            previous = (
                TRAINER_SOURCE_PROVENANCE_LEDGER_V4_GENESIS_SHA256
                if not state.records
                else cast(str, state.records[-1]["entry_sha256"])
            )
            record: dict[str, object] = {
                "schema_version": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION,
                "evidence_classification": (
                    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_EVIDENCE_CLASSIFICATION
                ),
                "downstream_status": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_DOWNSTREAM_STATUS,
                "ledger_namespace": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_NAMESPACE,
                "ledger_sequence": sequence,
                "previous_entry_sha256": previous,
                "trainer_run_id": run_id,
                "trainer_cycle_id": cycle_id,
                "cycle_identity_sha256": cycle_identity,
                "replay_identity_sha256": replay_identity,
                "ledger_recorded_at": recorded_at,
                "ledger_owned_store": replay_material["ledger_owned_store"],
                "source_capture": replay_material["source_capture"],
                "suffix_manifest": replay_material["suffix_manifest"],
                "ordered_rows": replay_material["ordered_rows"],
                "temporal_semantics": replay_material["temporal_semantics"],
                **{name: False for name in _DOWNSTREAM_FLAG_FIELDS},
            }
            record["entry_sha256"] = _stable_sha256(record)
            entry_json = _canonical_json(record)
            validated_record = _parse_entry_line(entry_json.encode("ascii"))
            _verify_record_owned_cas(
                validated_record,
                store,
                expected_store_root=self.store_root,
            )
            root.verify()
            framed = entry_json.encode("ascii") + b"\n"
            if len(state.raw_bytes) + len(framed) > MAX_LEDGER_BYTES:
                _durability_error("source_provenance_v4_ledger_size_limit_exceeded")
            _append_fsync(root, framed)
            committed_raw = state.raw_bytes + framed
            head = _head_material(
                raw_prefix=committed_raw,
                sequence=sequence,
                entry_sha256=cast(str, record["entry_sha256"]),
            )
            _write_head_atomic(root, head)
            readback = _postcommit_readback(
                root,
                store,
                expected_store_root=self.store_root,
                expected_entry_json=entry_json,
                expected_sequence=sequence,
            )
            return _append_result(
                _artifact(readback),
                disposition="APPENDED",
            )

    def _recover_pending(
        self,
        root: _VerifiedRootChain,
        store: ImmutableSourcePayloadStore,
        state: _LedgerState,
        pending: dict[str, Any],
    ) -> TrainerSourceProvenanceAppendResultV4:
        if state.pending_record is not pending or len(state.records) != state.committed_count + 1:
            _integrity_error("source_provenance_v4_pending_tail_shape_invalid")
        _verify_record_owned_cas(
            pending,
            store,
            expected_store_root=self.store_root,
        )
        _fsync_ledger(root)
        _fsync_directory_fd(root.final_fd)
        head = _head_material(
            raw_prefix=state.raw_bytes,
            sequence=len(state.records),
            entry_sha256=cast(str, pending["entry_sha256"]),
        )
        _write_head_atomic(root, head)
        entry_json = _canonical_json(pending)
        readback = _postcommit_readback(
            root,
            store,
            expected_store_root=self.store_root,
            expected_entry_json=entry_json,
            expected_sequence=len(state.records),
        )
        return _append_result(
            _artifact(readback),
            disposition="RECOVERED_EXACT_PENDING_APPEND",
        )

    def _finish_existing(
        self,
        root: _VerifiedRootChain,
        store: ImmutableSourcePayloadStore,
        existing: dict[str, Any],
        *,
        disposition: str,
    ) -> TrainerSourceProvenanceAppendResultV4:
        # Exact replay also takes over durability: both data and head are
        # re-fsynced, then re-read under the same interprocess lock.
        state = _load_state(
            root,
            store,
            expected_store_root=self.store_root,
        )
        if state.pending_record is not None or not state.records:
            _integrity_error("source_provenance_v4_exact_replay_state_invalid")
        _fsync_ledger(root)
        head = _head_material(
            raw_prefix=state.raw_bytes,
            sequence=len(state.records),
            entry_sha256=cast(str, state.records[-1]["entry_sha256"]),
        )
        _write_head_atomic(root, head)
        _postcommit_readback(
            root,
            store,
            expected_store_root=self.store_root,
            expected_entry_json=_canonical_json(state.records[-1]),
            expected_sequence=len(state.records),
        )
        return _append_result(
            _artifact(existing),
            disposition=disposition,
        )

    def read_entries(self) -> tuple[TrainerSourceProvenanceLedgerEntryV4, ...]:
        """Read only a completely committed, fully chained v4 ledger."""

        with self._exclusive_lock() as root:
            store = self._open_owned_store(root)
            state = _load_state(
                root,
                store,
                expected_store_root=self.store_root,
            )
            if state.pending_record is not None:
                _integrity_error("source_provenance_v4_uncommitted_tail_present")
            return tuple(_artifact(record) for record in state.records)

    def read_entries_read_only(self) -> tuple[TrainerSourceProvenanceLedgerEntryV4, ...]:
        """Verify one committed snapshot without any filesystem write access."""

        with self._shared_read_lock() as root:
            store = self._open_owned_store(root)
            state = _load_state(
                root,
                store,
                expected_store_root=self.store_root,
            )
            if state.pending_record is not None:
                _integrity_error("source_provenance_v4_uncommitted_tail_present")
            return tuple(_artifact(record) for record in state.records)


__all__ = [
    "MAX_LEDGER_BYTES",
    "MAX_LEDGER_ENTRIES",
    "MAX_LEDGER_ENTRY_BYTES",
    "TRAINER_SOURCE_PROVENANCE_LEDGER_V4_DOWNSTREAM_STATUS",
    "TRAINER_SOURCE_PROVENANCE_LEDGER_V4_EVIDENCE_CLASSIFICATION",
    "TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME",
    "TRAINER_SOURCE_PROVENANCE_LEDGER_V4_GENESIS_SHA256",
    "TRAINER_SOURCE_PROVENANCE_LEDGER_V4_HEAD_FILENAME",
    "TRAINER_SOURCE_PROVENANCE_LEDGER_V4_HEAD_SCHEMA_VERSION",
    "TRAINER_SOURCE_PROVENANCE_LEDGER_V4_LOCK_FILENAME",
    "TRAINER_SOURCE_PROVENANCE_LEDGER_V4_NAMESPACE",
    "TRAINER_SOURCE_PROVENANCE_LEDGER_V4_REPLAY_SCHEMA_VERSION",
    "TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION",
    "TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_NAMESPACE",
    "TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_ROOT_RELATIVE_PATH",
    "TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_SCHEMA_VERSION",
    "TrainerSourceProvenanceAppendResultV4",
    "TrainerSourceProvenanceLedgerEntryV4",
    "TrainerSourceProvenanceLedgerV4",
    "TrainerSourceProvenanceLedgerV4ConflictError",
    "TrainerSourceProvenanceLedgerV4DurabilityError",
    "TrainerSourceProvenanceLedgerV4Error",
    "TrainerSourceProvenanceLedgerV4IntegrityError",
    "TrainerSourceProvenanceLedgerV4ValidationError",
]
