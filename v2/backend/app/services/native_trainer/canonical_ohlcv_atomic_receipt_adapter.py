"""Unwired atomic canonical-OHLCV capture with truthful per-candle receipts.

The adapter performs exactly one bounded Redis ``MULTI``/``EXEC`` read of the
canonical closed-candle list, samples a local consumer clock only after that
response, validates the exact list bytes, and selects the complete latest
contiguous core-TA suffix. Older prefix gaps are recorded and excluded; no
gap, duplicate identity, unfinished interval, stale tail, or unavailable row
inside the selected suffix can pass.

The exact full Redis value and every selected JSON row byte span are stored in
``ImmutableSourcePayloadStore`` and freshly read back. A canonical suffix
manifest binds the Redis key and atomic batch version, exact full payload,
ordered interval identities, exact selected-row spans/digests/counts/CAS
addresses, selection digest, and one truthful ``source_read_receipt_v4`` per
selected candle. The manifest itself is then content-addressed and read back.

This module is deliberately standalone and unwired. It does not append to a
ledger, publish features, admit trainer data, or authorize prediction, paper,
or live execution. All such flags remain frozen and hash-bound false.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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
    AtomicRedisSourceReadBatch,
    AtomicRedisSourceReadIntegrityError,
    AtomicRedisSourceReadTransportError,
    AtomicRedisSourceReadValidationError,
    AtomicRedisSourceResult,
    RawRedisSourceClient,
    read_atomic_redis_sources,
)
from v2.backend.app.services.native_trainer.feature_window_dependency_contract import (
    FeatureWindowContractError,
    FullContiguousCoreInputBinding,
    bind_full_contiguous_core_ta_input,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
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
    SourceReadReceiptV4,
    SourceReadReceiptV4Error,
    build_source_read_receipt_v4,
    validate_source_read_receipt_v4,
)

CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION = "canonical_ohlcv_atomic_capture_v1"
CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION = "canonical_ohlcv_suffix_manifest_v1"
CANONICAL_OHLCV_SUFFIX_DIGEST_SCHEMA_VERSION = "canonical_ohlcv_suffix_digest_v1"
CANONICAL_OHLCV_ATOMIC_CAPTURE_EVIDENCE_CLASSIFICATION = (
    "ATOMIC_EXACT_CANONICAL_OHLCV_SELECTED_SUFFIX_CAS_V4_RECEIPTS_UNWIRED"
)
CANONICAL_OHLCV_ATOMIC_CAPTURE_DOWNSTREAM_STATUS = (
    "NO_LEDGER_APPEND_FEATURE_PUBLICATION_TRAINER_OR_EXECUTION_AUTHORIZATION"
)
CANONICAL_OHLCV_ROW_PAYLOAD_TYPE = "EXACT_CANONICAL_CLOSED_OHLCV_ROW_BYTES"
CANONICAL_OHLCV_FINALITY_VERIFIER = "trainer-canonical-ohlcv-atomic-adapter-v1"

MAX_SUFFIX_MANIFEST_BYTES = 8 * 1024 * 1024
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CONSTRUCTION_TOKEN = object()
_DOWNSTREAM_FLAG_FIELDS = (
    "durable_ledger_appended",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)


class CanonicalOhlcvAtomicCaptureError(RuntimeError):
    """Base fail-closed canonical atomic-capture error."""


class CanonicalOhlcvAtomicCaptureValidationError(CanonicalOhlcvAtomicCaptureError):
    """Input, exact source schema, selection, or clock validation failed."""


class CanonicalOhlcvAtomicCaptureIntegrityError(CanonicalOhlcvAtomicCaptureError):
    """Atomic evidence, exact byte spans, CAS, manifest, or receipt did not bind."""


class CanonicalOhlcvAtomicCaptureTransportError(CanonicalOhlcvAtomicCaptureError):
    """The single atomic Redis transport operation failed."""


@dataclass(frozen=True, slots=True)
class SelectedClosedCandleReceiptCapture:
    """One exact selected row span, immutable address, identity, and v4 receipt."""

    selected_ordinal: int
    source_index: int
    byte_start: int
    byte_end_exclusive: int
    exact_payload_sha256: str
    exact_payload_byte_count: int
    source_payload_address: SourcePayloadAddress
    candle_id: str
    candle_open_time_ms: int
    candle_close_time_ms: int
    producer_event_time_ms: int
    ingested_at_ms: int
    available_at_ms: int
    source: str
    source_sequence_id: str
    raw_payload_hash: str
    is_backfilled: bool
    source_read_receipt: SourceReadReceiptV4
    _exact_payload_bytes: bytes = field(repr=False)
    durable_ledger_appended: bool = field(default=False, init=False)
    feature_snapshot_published: bool = field(default=False, init=False)
    feature_publication_receipt_emitted: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class CanonicalOhlcvAtomicReceiptCapture:
    """Factory-authenticated complete selected-suffix capture."""

    schema_version: str
    evidence_classification: str
    downstream_status: str
    source_key: str
    source_key_sha256: str
    source_key_version: str
    atomic_batch_id: str
    atomic_batch_material_sha256: str
    atomic_batch_material_json: str = field(repr=False)
    atomic_server_time_seconds: int
    atomic_server_time_microseconds: int
    atomic_server_observed_at: str
    source_pttl_ms: int
    consumer_observed_at: str
    consumer_observed_at_ms: int
    full_source_payload_address: SourcePayloadAddress
    validated_window: ValidatedOHLCVClosedWindow
    full_window_binding: FullContiguousCoreInputBinding
    raw_row_count: int
    selected_source_start_index: int
    selected_source_end_index_exclusive: int
    selected_row_count: int
    excluded_prefix_row_count: int
    excluded_prefix_gap_indices: tuple[int, ...]
    excluded_prefix_gap_missing_interval_counts: tuple[int, ...]
    selected_internal_gap_indices: tuple[int, ...]
    selected_candle_ids: tuple[str, ...]
    selected_exact_payload_sha256s: tuple[str, ...]
    selected_exact_payload_byte_counts: tuple[int, ...]
    suffix_digest_material_json: str = field(repr=False)
    suffix_digest_sha256: str
    suffix_manifest_json: str = field(repr=False)
    suffix_manifest_address: SourcePayloadAddress
    _selected_candles: tuple[SelectedClosedCandleReceiptCapture, ...] = field(
        repr=False,
    )
    _exact_full_source_payload_bytes: bytes = field(repr=False)
    _source_payload_store: ImmutableSourcePayloadStore = field(
        repr=False,
        compare=False,
    )
    _construction_token: object = field(repr=False, compare=False)
    durable_ledger_appended: bool = field(default=False, init=False)
    feature_snapshot_published: bool = field(default=False, init=False)
    feature_publication_receipt_emitted: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _validated_capture(self)

    @property
    def selected_candles(self) -> tuple[SelectedClosedCandleReceiptCapture, ...]:
        """Return frozen selected captures after fresh CAS/manifest verification."""

        _validated_capture(self)
        return self._selected_candles

    @property
    def source_read_receipts(self) -> tuple[SourceReadReceiptV4, ...]:
        """Return the per-candle v4 receipts after fresh complete verification."""

        _validated_capture(self)
        return tuple(selected.source_read_receipt for selected in self._selected_candles)

    @property
    def exact_full_source_payload_bytes(self) -> bytes:
        """Return the exact atomic Redis bytes after fresh complete verification."""

        _validated_capture(self)
        return self._exact_full_source_payload_bytes

    @property
    def suffix_manifest(self) -> dict[str, Any]:
        """Return a fresh copy of the fully verified canonical suffix manifest."""

        _validated_capture(self)
        return cast(dict[str, Any], json.loads(self.suffix_manifest_json))


def _validation_error(reason: str) -> NoReturn:
    raise CanonicalOhlcvAtomicCaptureValidationError(reason) from None


def _integrity_error(reason: str) -> NoReturn:
    raise CanonicalOhlcvAtomicCaptureIntegrityError(reason) from None


def _canonical_json(value: object, *, size_reason: str) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        _integrity_error("canonical_ohlcv_atomic_capture_material_not_strict_json")
    if len(encoded.encode("ascii")) > MAX_SUFFIX_MANIFEST_BYTES:
        _integrity_error(size_reason)
    return encoded


def _stable_sha256(value: object) -> str:
    encoded = _canonical_json(
        value,
        size_reason="canonical_ohlcv_atomic_capture_digest_material_too_large",
    )
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _sample_consumer_clock(clock: object) -> tuple[datetime, str, int]:
    if not callable(clock):
        _validation_error("canonical_ohlcv_consumer_clock_not_callable")
    try:
        observed = cast(Callable[[], object], clock)()
    except Exception:  # noqa: BLE001 - hostile clock details must not escape
        _validation_error("canonical_ohlcv_consumer_clock_failed")
    if type(observed) is not datetime or observed.tzinfo is not UTC:
        _validation_error("canonical_ohlcv_consumer_clock_not_exact_utc_datetime")
    if observed < _EPOCH:
        _validation_error("canonical_ohlcv_consumer_clock_before_epoch")
    canonical = observed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    delta = observed - _EPOCH
    observed_ms = ((delta.days * 86_400 + delta.seconds) * 1_000) + (
        delta.microseconds // 1_000
    )
    return observed, canonical, observed_ms


def _ms_to_utc(value: int) -> str:
    if type(value) is not int or value < 0:
        _validation_error("canonical_ohlcv_source_clock_invalid")
    try:
        resolved = _EPOCH + timedelta(milliseconds=value)
    except (OverflowError, ValueError):
        _validation_error("canonical_ohlcv_source_clock_invalid")
    return resolved.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _expected_latest_finalized_close_ms(*, observed_at_ms: int, timeframe: str) -> int:
    duration_ms = TIMEFRAME_DURATION_MS.get(timeframe)
    if type(duration_ms) is not int or duration_ms <= 0:
        _validation_error("canonical_ohlcv_timeframe_invalid")
    expected = (observed_at_ms // duration_ms) * duration_ms - 1
    if expected < 0:
        _validation_error("canonical_ohlcv_expected_finalized_close_invalid")
    return expected


def _expected_atomic_batch_material(
    batch: AtomicRedisSourceReadBatch,
    result: AtomicRedisSourceResult,
) -> str:
    material = {
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
                "payload_byte_count": result.payload_byte_count,
                "payload_sha256": result.payload_sha256,
                "paper_provenance_only": True,
                "present": result.present,
                "pttl_ms": result.pttl_ms,
                "read_only": True,
                "redis_type": result.redis_type,
                "schema_version": result.schema_version,
                "server_time_clock_semantics": REDIS_TIME_CLOCK_SEMANTICS,
                "server_time_is_consumer_observed_at": False,
                "source_finality_attested": False,
                "source_key": result.source_key,
                "source_key_sha256": result.source_key_sha256,
                "source_schema_attested": False,
                "transport_authenticity_attested": False,
            }
        ],
        "schema_version": ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION,
        "server_observed_at": batch.server_observed_at,
        "server_time_clock_semantics": REDIS_TIME_CLOCK_SEMANTICS,
        "server_time_is_consumer_observed_at": False,
        "server_time_microseconds": batch.server_time_microseconds,
        "server_time_seconds": batch.server_time_seconds,
        "source_finality_attested": False,
        "source_schema_attested": False,
        "total_payload_byte_count": batch.total_payload_byte_count,
        "transport_authenticity_attested": False,
    }
    return json.dumps(
        material,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validated_atomic_result(
    batch: object,
    *,
    expected_source_key: str,
) -> tuple[AtomicRedisSourceReadBatch, AtomicRedisSourceResult, bytes]:
    if type(batch) is not AtomicRedisSourceReadBatch:
        _integrity_error("canonical_ohlcv_atomic_batch_type_invalid")
    typed_batch = batch
    if (
        typed_batch.schema_version != ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION
        or len(typed_batch.results) != 1
        or type(typed_batch.results[0]) is not AtomicRedisSourceResult
    ):
        _integrity_error("canonical_ohlcv_atomic_batch_shape_invalid")
    result = typed_batch.results[0]
    if (
        result.schema_version != ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION
        or result.source_key != expected_source_key
        or result.source_key_sha256
        != hashlib.sha256(expected_source_key.encode("ascii")).hexdigest()
    ):
        _integrity_error("canonical_ohlcv_atomic_source_key_binding_invalid")
    payload = result.exact_payload_bytes
    if (
        result.redis_type != "string"
        or result.present is not True
        or type(payload) is not bytes
        or not payload
    ):
        _validation_error("canonical_ohlcv_atomic_source_missing_or_non_string")
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    if (
        result.payload_sha256 != payload_sha256
        or result.payload_byte_count != len(payload)
        or typed_batch.total_payload_byte_count != len(payload)
        or type(result.pttl_ms) is not int
        or result.pttl_ms < -1
        or result.server_observed_at != typed_batch.server_observed_at
    ):
        _integrity_error("canonical_ohlcv_atomic_payload_evidence_invalid")
    expected_material = _expected_atomic_batch_material(typed_batch, result)
    expected_material_sha256 = hashlib.sha256(expected_material.encode("ascii")).hexdigest()
    if (
        not hmac.compare_digest(typed_batch.batch_material_json, expected_material)
        or typed_batch.batch_material_sha256 != expected_material_sha256
        or typed_batch.batch_id
        != f"trainer_atomic_redis_source_read_v2_{expected_material_sha256}"
    ):
        _integrity_error("canonical_ohlcv_atomic_batch_material_invalid")
    return typed_batch, result, payload


def _exact_json_array_element_spans(payload: bytes) -> tuple[tuple[int, int], ...]:
    try:
        text = payload.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        _validation_error("canonical_ohlcv_exact_payload_ascii_required_for_byte_spans")
    decoder = json.JSONDecoder()
    length = len(text)
    index = 0

    def skip_whitespace(position: int) -> int:
        while position < length and text[position] in " \t\r\n":
            position += 1
        return position

    index = skip_whitespace(index)
    if index >= length or text[index] != "[":
        _integrity_error("canonical_ohlcv_exact_payload_array_span_invalid")
    index = skip_whitespace(index + 1)
    spans: list[tuple[int, int]] = []
    if index < length and text[index] == "]":
        _integrity_error("canonical_ohlcv_exact_payload_array_empty")
    while index < length:
        if len(spans) >= MAX_OHLCV_CLOSED_ROWS:
            _integrity_error("canonical_ohlcv_exact_payload_row_span_limit_exceeded")
        start = index
        try:
            _, end = decoder.raw_decode(text, index)
        except (json.JSONDecodeError, RecursionError):
            _integrity_error("canonical_ohlcv_exact_payload_row_span_invalid")
        if end <= start:
            _integrity_error("canonical_ohlcv_exact_payload_row_span_invalid")
        spans.append((start, end))
        index = skip_whitespace(end)
        if index >= length:
            _integrity_error("canonical_ohlcv_exact_payload_array_span_invalid")
        if text[index] == "]":
            index = skip_whitespace(index + 1)
            if index != length:
                _integrity_error("canonical_ohlcv_exact_payload_trailing_bytes")
            break
        if text[index] != ",":
            _integrity_error("canonical_ohlcv_exact_payload_row_delimiter_invalid")
        index = skip_whitespace(index + 1)
    if not spans:
        _integrity_error("canonical_ohlcv_exact_payload_array_empty")
    return tuple(spans)


def _address_material(address: SourcePayloadAddress) -> dict[str, object]:
    if type(address) is not SourcePayloadAddress:
        _integrity_error("canonical_ohlcv_cas_address_type_invalid")
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _fresh_exact_readback(
    store: ImmutableSourcePayloadStore,
    address: SourcePayloadAddress,
    expected_bytes: bytes,
    *,
    reason: str,
) -> None:
    if (
        type(expected_bytes) is not bytes
        or address.payload_sha256 != hashlib.sha256(expected_bytes).hexdigest()
        or address.payload_byte_count != len(expected_bytes)
    ):
        _integrity_error(reason)
    try:
        readback = store.get(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise CanonicalOhlcvAtomicCaptureIntegrityError(reason) from exc
    if not hmac.compare_digest(readback, expected_bytes):
        _integrity_error(reason)


def _suffix_digest_material(
    *,
    source_key: str,
    source_key_version: str,
    full_source_payload_address: SourcePayloadAddress,
    binding: FullContiguousCoreInputBinding,
    selected: tuple[SelectedClosedCandleReceiptCapture, ...],
) -> dict[str, object]:
    return {
        "schema_version": CANONICAL_OHLCV_SUFFIX_DIGEST_SCHEMA_VERSION,
        "source_key": source_key,
        "source_key_version": source_key_version,
        "full_source_payload_sha256": full_source_payload_address.payload_sha256,
        "full_source_payload_byte_count": full_source_payload_address.payload_byte_count,
        "binding_selection_sha256": binding.selection_sha256,
        "selected_candle_id_chain_sha256": binding.selected_candle_id_chain_sha256,
        "selected_source_start_index": binding.selected_source_start_index,
        "selected_source_end_index_exclusive": binding.selected_source_end_index_exclusive,
        "selected_row_count": len(selected),
        "ordered_selected_rows": [
            {
                "selected_ordinal": row.selected_ordinal,
                "source_index": row.source_index,
                "byte_start": row.byte_start,
                "byte_end_exclusive": row.byte_end_exclusive,
                "exact_payload_sha256": row.exact_payload_sha256,
                "exact_payload_byte_count": row.exact_payload_byte_count,
                "candle_id": row.candle_id,
                "candle_open_time_ms": row.candle_open_time_ms,
                "candle_close_time_ms": row.candle_close_time_ms,
                "source_sequence_id": row.source_sequence_id,
                "raw_payload_hash": row.raw_payload_hash,
                "source_read_receipt_sha256": row.source_read_receipt.receipt_sha256,
            }
            for row in selected
        ],
    }


def _manifest_material(
    *,
    source_key: str,
    source_key_sha256: str,
    source_key_version: str,
    atomic_batch_id: str,
    atomic_batch_material_sha256: str,
    atomic_batch_material_json: str,
    atomic_server_time_seconds: int,
    atomic_server_time_microseconds: int,
    atomic_server_observed_at: str,
    source_pttl_ms: int,
    consumer_observed_at: str,
    consumer_observed_at_ms: int,
    full_source_payload_address: SourcePayloadAddress,
    validated_window: ValidatedOHLCVClosedWindow,
    binding: FullContiguousCoreInputBinding,
    excluded_prefix_gap_indices: tuple[int, ...],
    excluded_prefix_gap_missing_interval_counts: tuple[int, ...],
    selected_internal_gap_indices: tuple[int, ...],
    suffix_digest_material_json: str,
    suffix_digest_sha256: str,
    selected: tuple[SelectedClosedCandleReceiptCapture, ...],
) -> dict[str, object]:
    return {
        "schema_version": CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION,
        "evidence_classification": (
            CANONICAL_OHLCV_ATOMIC_CAPTURE_EVIDENCE_CLASSIFICATION
        ),
        "downstream_status": CANONICAL_OHLCV_ATOMIC_CAPTURE_DOWNSTREAM_STATUS,
        "source_key": source_key,
        "source_key_sha256": source_key_sha256,
        "source_key_version": source_key_version,
        "atomic_batch_id": atomic_batch_id,
        "atomic_batch_material_sha256": atomic_batch_material_sha256,
        "atomic_batch_material_json": atomic_batch_material_json,
        "atomic_server_time_seconds": atomic_server_time_seconds,
        "atomic_server_time_microseconds": atomic_server_time_microseconds,
        "atomic_server_observed_at": atomic_server_observed_at,
        "source_pttl_ms": source_pttl_ms,
        "consumer_observed_at": consumer_observed_at,
        "consumer_observed_at_ms": consumer_observed_at_ms,
        "full_source_payload_cas_address": _address_material(full_source_payload_address),
        "raw_row_count": validated_window.row_count,
        "source_gap_indices": list(validated_window.gap_indices),
        "source_gap_missing_interval_counts": list(
            validated_window.gap_missing_interval_counts
        ),
        "selected_source_start_index": binding.selected_source_start_index,
        "selected_source_end_index_exclusive": binding.selected_source_end_index_exclusive,
        "selected_row_count": len(selected),
        "excluded_prefix_row_count": binding.selected_source_start_index,
        "excluded_prefix_gap_indices": list(excluded_prefix_gap_indices),
        "excluded_prefix_gap_missing_interval_counts": list(
            excluded_prefix_gap_missing_interval_counts
        ),
        "selected_internal_gap_indices": list(selected_internal_gap_indices),
        "tail_missing_interval_count": binding.tail_missing_interval_count,
        "latest_candle_matches_expected_cutoff": binding.latest_candle_matches_expected_cutoff,
        "binding_selection_sha256": binding.selection_sha256,
        "selected_candle_id_chain_sha256": binding.selected_candle_id_chain_sha256,
        "suffix_digest_material_json": suffix_digest_material_json,
        "suffix_digest_sha256": suffix_digest_sha256,
        "selected_rows": [
            {
                "selected_ordinal": row.selected_ordinal,
                "source_index": row.source_index,
                "byte_start": row.byte_start,
                "byte_end_exclusive": row.byte_end_exclusive,
                "exact_payload_sha256": row.exact_payload_sha256,
                "exact_payload_byte_count": row.exact_payload_byte_count,
                "source_payload_cas_address": _address_material(
                    row.source_payload_address
                ),
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
                "source_read_receipt_v4": row.source_read_receipt.receipt,
            }
            for row in selected
        ],
        **{field_name: False for field_name in _DOWNSTREAM_FLAG_FIELDS},
    }


def _validate_atomic_capture_material(
    capture: CanonicalOhlcvAtomicReceiptCapture,
) -> None:
    try:
        material = json.loads(capture.atomic_batch_material_json)
    except (json.JSONDecodeError, TypeError, ValueError, OverflowError, RecursionError):
        _integrity_error("canonical_ohlcv_atomic_capture_batch_material_invalid")
    if type(material) is not dict:
        _integrity_error("canonical_ohlcv_atomic_capture_batch_material_invalid")
    typed_material = cast(dict[str, Any], material)
    results = typed_material.get("results")
    if type(results) is not list or len(results) != 1 or type(results[0]) is not dict:
        _integrity_error("canonical_ohlcv_atomic_capture_batch_material_invalid")
    result = cast(dict[str, Any], results[0])
    try:
        expected_server_clock = _EPOCH + timedelta(
            seconds=capture.atomic_server_time_seconds,
            microseconds=capture.atomic_server_time_microseconds,
        )
    except (OverflowError, ValueError):
        _integrity_error("canonical_ohlcv_atomic_capture_server_clock_invalid")
    expected_server_observed_at = expected_server_clock.isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    fixed_top_level = {
        "schema_version": ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION,
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
        "server_time_clock_semantics": REDIS_TIME_CLOCK_SEMANTICS,
        "server_time_is_consumer_observed_at": False,
        "source_finality_attested": False,
        "source_schema_attested": False,
        "transport_authenticity_attested": False,
        "server_time_seconds": capture.atomic_server_time_seconds,
        "server_time_microseconds": capture.atomic_server_time_microseconds,
        "server_observed_at": expected_server_observed_at,
        "total_payload_byte_count": capture.full_source_payload_address.payload_byte_count,
    }
    fixed_result = {
        "schema_version": ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION,
        "consumer_eligible": False,
        "ledger_receipt_emitted": False,
        "live_execution_authorized": False,
        "paper_provenance_only": True,
        "present": True,
        "read_only": True,
        "redis_type": "string",
        "server_time_clock_semantics": REDIS_TIME_CLOCK_SEMANTICS,
        "server_time_is_consumer_observed_at": False,
        "source_finality_attested": False,
        "source_schema_attested": False,
        "transport_authenticity_attested": False,
        "source_key": capture.source_key,
        "source_key_sha256": capture.source_key_sha256,
        "payload_sha256": capture.full_source_payload_address.payload_sha256,
        "payload_byte_count": capture.full_source_payload_address.payload_byte_count,
        "pttl_ms": capture.source_pttl_ms,
    }
    if (
        set(typed_material) != {*fixed_top_level, "results"}
        or set(result) != set(fixed_result)
        or any(typed_material.get(key) != value for key, value in fixed_top_level.items())
        or any(result.get(key) != value for key, value in fixed_result.items())
        or capture.atomic_server_observed_at != expected_server_observed_at
        or _canonical_json(
            typed_material,
            size_reason="canonical_ohlcv_atomic_batch_material_too_large",
        )
        != capture.atomic_batch_material_json
    ):
        _integrity_error("canonical_ohlcv_atomic_capture_batch_material_invalid")


def _validated_capture(capture: CanonicalOhlcvAtomicReceiptCapture) -> None:
    if capture._construction_token is not _CONSTRUCTION_TOKEN:
        _integrity_error("canonical_ohlcv_atomic_capture_factory_construction_required")
    if (
        capture.schema_version != CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION
        or capture.evidence_classification
        != CANONICAL_OHLCV_ATOMIC_CAPTURE_EVIDENCE_CLASSIFICATION
        or capture.downstream_status != CANONICAL_OHLCV_ATOMIC_CAPTURE_DOWNSTREAM_STATUS
        or type(capture._source_payload_store) is not ImmutableSourcePayloadStore
        or type(capture._exact_full_source_payload_bytes) is not bytes
        or any(getattr(capture, name) is not False for name in _DOWNSTREAM_FLAG_FIELDS)
    ):
        _integrity_error("canonical_ohlcv_atomic_capture_contract_invalid")
    expected_source_key_sha256 = hashlib.sha256(capture.source_key.encode("ascii")).hexdigest()
    if (
        capture.source_key_sha256 != expected_source_key_sha256
        or capture.source_key_version != capture.atomic_batch_id
        or capture.atomic_batch_material_sha256
        != hashlib.sha256(capture.atomic_batch_material_json.encode("ascii")).hexdigest()
        or capture.atomic_batch_id
        != f"trainer_atomic_redis_source_read_v2_{capture.atomic_batch_material_sha256}"
    ):
        _integrity_error("canonical_ohlcv_atomic_capture_batch_binding_invalid")
    _validate_atomic_capture_material(capture)
    _fresh_exact_readback(
        capture._source_payload_store,
        capture.full_source_payload_address,
        capture._exact_full_source_payload_bytes,
        reason="canonical_ohlcv_full_payload_cas_readback_failed",
    )
    try:
        revalidated_window = validate_ohlcv_closed_window(
            capture._exact_full_source_payload_bytes,
            symbol=capture.validated_window.symbol,
            timeframe=capture.validated_window.timeframe,
        )
        identity_rows = [
            {
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "candle_id": row.candle_id,
                "candle_open_time": row.candle_open_time,
                "candle_close_time": row.candle_close_time,
                "available_at": row.available_at,
            }
            for row in revalidated_window.rows
        ]
        rebound_window = bind_full_contiguous_core_ta_input(
            identity_rows,
            expected_symbol=revalidated_window.symbol,
            timeframe=revalidated_window.timeframe,
            consumer_observed_at_ms=capture.consumer_observed_at_ms,
            expected_latest_finalized_close_time=_expected_latest_finalized_close_ms(
                observed_at_ms=capture.consumer_observed_at_ms,
                timeframe=revalidated_window.timeframe,
            ),
        )
    except (OHLCVClosedWindowValidationError, FeatureWindowContractError) as exc:
        raise CanonicalOhlcvAtomicCaptureIntegrityError(
            "canonical_ohlcv_atomic_capture_source_revalidation_failed"
        ) from exc
    if (
        revalidated_window != capture.validated_window
        or rebound_window != capture.full_window_binding
    ):
        _integrity_error("canonical_ohlcv_atomic_capture_source_revalidation_mismatch")
    if (
        capture.validated_window.source_key != capture.source_key
        or capture.validated_window.exact_payload_sha256
        != capture.full_source_payload_address.payload_sha256
        or capture.validated_window.exact_payload_byte_count
        != capture.full_source_payload_address.payload_byte_count
        or capture.raw_row_count != capture.validated_window.row_count
        or capture.selected_source_start_index
        != capture.full_window_binding.selected_source_start_index
        or capture.selected_source_end_index_exclusive
        != capture.full_window_binding.selected_source_end_index_exclusive
        or capture.selected_row_count != len(capture._selected_candles)
        or capture.selected_row_count != capture.full_window_binding.selected_row_count
        or capture.excluded_prefix_row_count != capture.selected_source_start_index
        or capture.selected_internal_gap_indices
        or capture.full_window_binding.tail_missing_interval_count != 0
        or capture.full_window_binding.latest_candle_matches_expected_cutoff is not True
    ):
        _integrity_error("canonical_ohlcv_atomic_capture_selection_binding_invalid")
    if (
        capture.selected_candle_ids
        != tuple(row.candle_id for row in capture._selected_candles)
        or capture.selected_exact_payload_sha256s
        != tuple(row.exact_payload_sha256 for row in capture._selected_candles)
        or capture.selected_exact_payload_byte_counts
        != tuple(row.exact_payload_byte_count for row in capture._selected_candles)
        or capture.selected_candle_ids != capture.full_window_binding.selected_candle_ids
        or len(set(capture.selected_candle_ids)) != capture.selected_row_count
    ):
        _integrity_error("canonical_ohlcv_atomic_capture_ordered_suffix_binding_invalid")

    for expected_ordinal, selected in enumerate(capture._selected_candles):
        source_index = capture.selected_source_start_index + expected_ordinal
        if (
            selected.selected_ordinal != expected_ordinal
            or selected.source_index != source_index
            or any(getattr(selected, name) is not False for name in _DOWNSTREAM_FLAG_FIELDS)
        ):
            _integrity_error("canonical_ohlcv_selected_row_identity_invalid")
        source_row = capture.validated_window.rows[source_index]
        exact_span = capture._exact_full_source_payload_bytes[
            selected.byte_start : selected.byte_end_exclusive
        ]
        if (
            selected.byte_start < 0
            or selected.byte_end_exclusive <= selected.byte_start
            or not hmac.compare_digest(exact_span, selected._exact_payload_bytes)
            or selected.exact_payload_sha256
            != hashlib.sha256(selected._exact_payload_bytes).hexdigest()
            or selected.exact_payload_byte_count != len(selected._exact_payload_bytes)
            or selected.candle_id != source_row.candle_id
            or selected.candle_open_time_ms != source_row.candle_open_time
            or selected.candle_close_time_ms != source_row.candle_close_time
            or selected.producer_event_time_ms != source_row.event_time
            or selected.ingested_at_ms != source_row.ingested_at
            or selected.available_at_ms != source_row.available_at
            or selected.source != source_row.source
            or selected.source_sequence_id != source_row.source_sequence_id
            or selected.raw_payload_hash != source_row.raw_payload_hash
            or selected.is_backfilled is not source_row.is_backfilled
        ):
            _integrity_error("canonical_ohlcv_selected_row_exact_binding_invalid")
        _fresh_exact_readback(
            capture._source_payload_store,
            selected.source_payload_address,
            selected._exact_payload_bytes,
            reason="canonical_ohlcv_selected_row_cas_readback_failed",
        )
        receipt = validate_source_read_receipt_v4(selected.source_read_receipt.receipt)
        receipt_mapping = receipt.receipt
        if (
            receipt.receipt_sha256 != selected.source_read_receipt.receipt_sha256
            or receipt.receipt_json != selected.source_read_receipt.receipt_json
            or receipt_mapping["payload_sha256"] != selected.exact_payload_sha256
            or receipt_mapping["payload_byte_count"] != selected.exact_payload_byte_count
            or receipt_mapping["economic_event_time"]
            != _ms_to_utc(selected.candle_close_time_ms)
            or receipt_mapping["producer_event_time"]
            != _ms_to_utc(selected.producer_event_time_ms)
            or receipt_mapping["ingested_at"] != _ms_to_utc(selected.ingested_at_ms)
            or receipt_mapping["available_at"] != _ms_to_utc(selected.available_at_ms)
            or receipt_mapping["consumer_observed_at"] != capture.consumer_observed_at
            or receipt_mapping["feature_cutoff"]
            != _ms_to_utc(selected.candle_close_time_ms)
        ):
            _integrity_error("canonical_ohlcv_selected_row_receipt_binding_invalid")

    expected_suffix_material = _suffix_digest_material(
        source_key=capture.source_key,
        source_key_version=capture.source_key_version,
        full_source_payload_address=capture.full_source_payload_address,
        binding=capture.full_window_binding,
        selected=capture._selected_candles,
    )
    expected_suffix_json = _canonical_json(
        expected_suffix_material,
        size_reason="canonical_ohlcv_suffix_digest_material_too_large",
    )
    if (
        not hmac.compare_digest(capture.suffix_digest_material_json, expected_suffix_json)
        or capture.suffix_digest_sha256
        != hashlib.sha256(expected_suffix_json.encode("ascii")).hexdigest()
    ):
        _integrity_error("canonical_ohlcv_suffix_digest_binding_invalid")
    expected_manifest = _manifest_material(
        source_key=capture.source_key,
        source_key_sha256=capture.source_key_sha256,
        source_key_version=capture.source_key_version,
        atomic_batch_id=capture.atomic_batch_id,
        atomic_batch_material_sha256=capture.atomic_batch_material_sha256,
        atomic_batch_material_json=capture.atomic_batch_material_json,
        atomic_server_time_seconds=capture.atomic_server_time_seconds,
        atomic_server_time_microseconds=capture.atomic_server_time_microseconds,
        atomic_server_observed_at=capture.atomic_server_observed_at,
        source_pttl_ms=capture.source_pttl_ms,
        consumer_observed_at=capture.consumer_observed_at,
        consumer_observed_at_ms=capture.consumer_observed_at_ms,
        full_source_payload_address=capture.full_source_payload_address,
        validated_window=capture.validated_window,
        binding=capture.full_window_binding,
        excluded_prefix_gap_indices=capture.excluded_prefix_gap_indices,
        excluded_prefix_gap_missing_interval_counts=(
            capture.excluded_prefix_gap_missing_interval_counts
        ),
        selected_internal_gap_indices=capture.selected_internal_gap_indices,
        suffix_digest_material_json=capture.suffix_digest_material_json,
        suffix_digest_sha256=capture.suffix_digest_sha256,
        selected=capture._selected_candles,
    )
    expected_manifest_json = _canonical_json(
        expected_manifest,
        size_reason="canonical_ohlcv_suffix_manifest_too_large",
    )
    if not hmac.compare_digest(capture.suffix_manifest_json, expected_manifest_json):
        _integrity_error("canonical_ohlcv_suffix_manifest_binding_invalid")
    _fresh_exact_readback(
        capture._source_payload_store,
        capture.suffix_manifest_address,
        expected_manifest_json.encode("ascii"),
        reason="canonical_ohlcv_suffix_manifest_cas_readback_failed",
    )


def capture_canonical_closed_ohlcv_atomic_receipts(
    redis_client: RawRedisSourceClient,
    source_payload_store: ImmutableSourcePayloadStore,
    *,
    expected_symbol: str,
    expected_timeframe: str,
    consumer_clock: Callable[[], datetime] = _utc_now,
) -> CanonicalOhlcvAtomicReceiptCapture:
    """Atomically capture and receipt the complete latest contiguous suffix."""

    if type(source_payload_store) is not ImmutableSourcePayloadStore:
        _validation_error("canonical_ohlcv_authentic_source_payload_store_required")
    source_key = (
        f"v2:market:ohlcv_closed:binance:{expected_symbol}:{expected_timeframe}"
    )
    try:
        batch = read_atomic_redis_sources(redis_client, (source_key,))
    except AtomicRedisSourceReadTransportError as exc:
        raise CanonicalOhlcvAtomicCaptureTransportError(str(exc)) from None
    except AtomicRedisSourceReadValidationError as exc:
        raise CanonicalOhlcvAtomicCaptureValidationError(str(exc)) from None
    except AtomicRedisSourceReadIntegrityError as exc:
        raise CanonicalOhlcvAtomicCaptureIntegrityError(str(exc)) from None
    observed_datetime, consumer_observed_at, consumer_observed_at_ms = (
        _sample_consumer_clock(consumer_clock)
    )
    typed_batch, source_result, exact_full_payload = _validated_atomic_result(
        batch,
        expected_source_key=source_key,
    )
    try:
        validated_window = validate_ohlcv_closed_window(
            exact_full_payload,
            symbol=expected_symbol,
            timeframe=expected_timeframe,
        )
        identity_rows = [
            {
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "candle_id": row.candle_id,
                "candle_open_time": row.candle_open_time,
                "candle_close_time": row.candle_close_time,
                "available_at": row.available_at,
            }
            for row in validated_window.rows
        ]
        binding = bind_full_contiguous_core_ta_input(
            identity_rows,
            expected_symbol=expected_symbol,
            timeframe=expected_timeframe,
            consumer_observed_at_ms=consumer_observed_at_ms,
            expected_latest_finalized_close_time=_expected_latest_finalized_close_ms(
                observed_at_ms=consumer_observed_at_ms,
                timeframe=expected_timeframe,
            ),
        )
    except (OHLCVClosedWindowValidationError, FeatureWindowContractError) as exc:
        raise CanonicalOhlcvAtomicCaptureValidationError(str(exc)) from None
    if (
        validated_window.source_key != source_key
        or validated_window.exact_payload_sha256 != source_result.payload_sha256
        or validated_window.exact_payload_byte_count != source_result.payload_byte_count
        or binding.selected_source_end_index_exclusive != validated_window.row_count
        or binding.tail_missing_interval_count != 0
        or binding.latest_candle_matches_expected_cutoff is not True
    ):
        _integrity_error("canonical_ohlcv_schema_selection_transport_binding_invalid")
    if (_EPOCH + timedelta(milliseconds=validated_window.max_available_at)) > observed_datetime:
        _validation_error("canonical_ohlcv_source_available_after_consumer_observation")

    spans = _exact_json_array_element_spans(exact_full_payload)
    if len(spans) != validated_window.row_count:
        _integrity_error("canonical_ohlcv_exact_row_span_count_mismatch")
    selected_start = binding.selected_source_start_index
    selected_end = binding.selected_source_end_index_exclusive
    internal_gaps = tuple(
        gap_index
        for gap_index in validated_window.gap_indices
        if selected_start < gap_index < selected_end
    )
    if internal_gaps:
        _validation_error("canonical_ohlcv_selected_suffix_contains_gap")
    excluded_gap_pairs = tuple(
        (gap_index, missing_count)
        for gap_index, missing_count in zip(
            validated_window.gap_indices,
            validated_window.gap_missing_interval_counts,
            strict=True,
        )
        if gap_index <= selected_start
    )
    if len(set(binding.selected_candle_ids)) != binding.selected_row_count:
        _validation_error("canonical_ohlcv_selected_suffix_duplicate_identity")

    try:
        full_source_address = source_payload_store.put(
            exact_full_payload,
            expected_sha256=validated_window.exact_payload_sha256,
            expected_byte_count=validated_window.exact_payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise CanonicalOhlcvAtomicCaptureIntegrityError(
            "canonical_ohlcv_full_payload_cas_capture_failed"
        ) from exc
    _fresh_exact_readback(
        source_payload_store,
        full_source_address,
        exact_full_payload,
        reason="canonical_ohlcv_full_payload_cas_readback_failed",
    )

    selected_captures: list[SelectedClosedCandleReceiptCapture] = []
    for selected_ordinal, source_index in enumerate(range(selected_start, selected_end)):
        row = validated_window.rows[source_index]
        byte_start, byte_end = spans[source_index]
        exact_row_bytes = exact_full_payload[byte_start:byte_end]
        exact_row_sha256 = hashlib.sha256(exact_row_bytes).hexdigest()
        try:
            row_address = source_payload_store.put(
                exact_row_bytes,
                expected_sha256=exact_row_sha256,
                expected_byte_count=len(exact_row_bytes),
            )
        except SourcePayloadStoreError as exc:
            raise CanonicalOhlcvAtomicCaptureIntegrityError(
                "canonical_ohlcv_selected_row_cas_capture_failed"
            ) from exc
        _fresh_exact_readback(
            source_payload_store,
            row_address,
            exact_row_bytes,
            reason="canonical_ohlcv_selected_row_cas_readback_failed",
        )
        try:
            receipt = build_source_read_receipt_v4(
                source_label=(
                    f"ohlcv_closed:binance:{expected_symbol}:"
                    f"{expected_timeframe}:{row.candle_id}"
                ),
                payload_type=CANONICAL_OHLCV_ROW_PAYLOAD_TYPE,
                payload_sha256=exact_row_sha256,
                payload_byte_count=len(exact_row_bytes),
                economic_event_time=_ms_to_utc(row.candle_close_time),
                producer_event_time=_ms_to_utc(row.event_time),
                ingested_at=_ms_to_utc(row.ingested_at),
                available_at=_ms_to_utc(row.available_at),
                consumer_observed_at=consumer_observed_at,
                feature_cutoff=_ms_to_utc(row.candle_close_time),
                # This clock describes the atomic Redis observation, not the
                # later CAS publication. Bind the exact array-element span to
                # the immutable atomic batch version; CAS is bound separately
                # by the suffix manifest and independently read back.
                read_locator_type="REDIS_VERSIONED_VALUE",
                read_locator=f"{source_key}@bytes:{byte_start}-{byte_end}",
                read_locator_version=typed_batch.batch_id,
                finality_type="CLOSED_INTERVAL",
                finality_cutoff=_ms_to_utc(row.candle_close_time),
                finality_verified_at=_ms_to_utc(row.available_at),
                finality_verifier=CANONICAL_OHLCV_FINALITY_VERIFIER,
            )
        except SourceReadReceiptV4Error as exc:
            raise CanonicalOhlcvAtomicCaptureValidationError(
                "canonical_ohlcv_selected_row_v4_receipt_invalid"
            ) from exc
        selected_captures.append(
            SelectedClosedCandleReceiptCapture(
                selected_ordinal=selected_ordinal,
                source_index=source_index,
                byte_start=byte_start,
                byte_end_exclusive=byte_end,
                exact_payload_sha256=exact_row_sha256,
                exact_payload_byte_count=len(exact_row_bytes),
                source_payload_address=row_address,
                candle_id=row.candle_id,
                candle_open_time_ms=row.candle_open_time,
                candle_close_time_ms=row.candle_close_time,
                producer_event_time_ms=row.event_time,
                ingested_at_ms=row.ingested_at,
                available_at_ms=row.available_at,
                source=row.source,
                source_sequence_id=row.source_sequence_id,
                raw_payload_hash=row.raw_payload_hash,
                is_backfilled=row.is_backfilled,
                source_read_receipt=receipt,
                _exact_payload_bytes=exact_row_bytes,
            )
        )
    frozen_selected = tuple(selected_captures)
    if (
        len(frozen_selected) != binding.selected_row_count
        or tuple(row.candle_id for row in frozen_selected) != binding.selected_candle_ids
    ):
        _integrity_error("canonical_ohlcv_selected_suffix_construction_mismatch")

    suffix_material = _suffix_digest_material(
        source_key=source_key,
        source_key_version=typed_batch.batch_id,
        full_source_payload_address=full_source_address,
        binding=binding,
        selected=frozen_selected,
    )
    suffix_material_json = _canonical_json(
        suffix_material,
        size_reason="canonical_ohlcv_suffix_digest_material_too_large",
    )
    suffix_digest_sha256 = hashlib.sha256(suffix_material_json.encode("ascii")).hexdigest()
    excluded_gap_indices = tuple(item[0] for item in excluded_gap_pairs)
    excluded_gap_counts = tuple(item[1] for item in excluded_gap_pairs)
    manifest = _manifest_material(
        source_key=source_key,
        source_key_sha256=source_result.source_key_sha256,
        source_key_version=typed_batch.batch_id,
        atomic_batch_id=typed_batch.batch_id,
        atomic_batch_material_sha256=typed_batch.batch_material_sha256,
        atomic_batch_material_json=typed_batch.batch_material_json,
        atomic_server_time_seconds=typed_batch.server_time_seconds,
        atomic_server_time_microseconds=typed_batch.server_time_microseconds,
        atomic_server_observed_at=typed_batch.server_observed_at,
        source_pttl_ms=source_result.pttl_ms,
        consumer_observed_at=consumer_observed_at,
        consumer_observed_at_ms=consumer_observed_at_ms,
        full_source_payload_address=full_source_address,
        validated_window=validated_window,
        binding=binding,
        excluded_prefix_gap_indices=excluded_gap_indices,
        excluded_prefix_gap_missing_interval_counts=excluded_gap_counts,
        selected_internal_gap_indices=internal_gaps,
        suffix_digest_material_json=suffix_material_json,
        suffix_digest_sha256=suffix_digest_sha256,
        selected=frozen_selected,
    )
    manifest_json = _canonical_json(
        manifest,
        size_reason="canonical_ohlcv_suffix_manifest_too_large",
    )
    manifest_bytes = manifest_json.encode("ascii")
    try:
        manifest_address = source_payload_store.put(
            manifest_bytes,
            expected_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            expected_byte_count=len(manifest_bytes),
        )
    except SourcePayloadStoreError as exc:
        raise CanonicalOhlcvAtomicCaptureIntegrityError(
            "canonical_ohlcv_suffix_manifest_cas_capture_failed"
        ) from exc
    _fresh_exact_readback(
        source_payload_store,
        manifest_address,
        manifest_bytes,
        reason="canonical_ohlcv_suffix_manifest_cas_readback_failed",
    )

    return CanonicalOhlcvAtomicReceiptCapture(
        schema_version=CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION,
        evidence_classification=CANONICAL_OHLCV_ATOMIC_CAPTURE_EVIDENCE_CLASSIFICATION,
        downstream_status=CANONICAL_OHLCV_ATOMIC_CAPTURE_DOWNSTREAM_STATUS,
        source_key=source_key,
        source_key_sha256=source_result.source_key_sha256,
        source_key_version=typed_batch.batch_id,
        atomic_batch_id=typed_batch.batch_id,
        atomic_batch_material_sha256=typed_batch.batch_material_sha256,
        atomic_batch_material_json=typed_batch.batch_material_json,
        atomic_server_time_seconds=typed_batch.server_time_seconds,
        atomic_server_time_microseconds=typed_batch.server_time_microseconds,
        atomic_server_observed_at=typed_batch.server_observed_at,
        source_pttl_ms=source_result.pttl_ms,
        consumer_observed_at=consumer_observed_at,
        consumer_observed_at_ms=consumer_observed_at_ms,
        full_source_payload_address=full_source_address,
        validated_window=validated_window,
        full_window_binding=binding,
        raw_row_count=validated_window.row_count,
        selected_source_start_index=selected_start,
        selected_source_end_index_exclusive=selected_end,
        selected_row_count=len(frozen_selected),
        excluded_prefix_row_count=selected_start,
        excluded_prefix_gap_indices=excluded_gap_indices,
        excluded_prefix_gap_missing_interval_counts=excluded_gap_counts,
        selected_internal_gap_indices=internal_gaps,
        selected_candle_ids=tuple(row.candle_id for row in frozen_selected),
        selected_exact_payload_sha256s=tuple(
            row.exact_payload_sha256 for row in frozen_selected
        ),
        selected_exact_payload_byte_counts=tuple(
            row.exact_payload_byte_count for row in frozen_selected
        ),
        suffix_digest_material_json=suffix_material_json,
        suffix_digest_sha256=suffix_digest_sha256,
        suffix_manifest_json=manifest_json,
        suffix_manifest_address=manifest_address,
        _selected_candles=frozen_selected,
        _exact_full_source_payload_bytes=exact_full_payload,
        _source_payload_store=source_payload_store,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "CANONICAL_OHLCV_ATOMIC_CAPTURE_DOWNSTREAM_STATUS",
    "CANONICAL_OHLCV_ATOMIC_CAPTURE_EVIDENCE_CLASSIFICATION",
    "CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION",
    "CANONICAL_OHLCV_FINALITY_VERIFIER",
    "CANONICAL_OHLCV_ROW_PAYLOAD_TYPE",
    "CANONICAL_OHLCV_SUFFIX_DIGEST_SCHEMA_VERSION",
    "CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION",
    "CanonicalOhlcvAtomicCaptureError",
    "CanonicalOhlcvAtomicCaptureIntegrityError",
    "CanonicalOhlcvAtomicCaptureTransportError",
    "CanonicalOhlcvAtomicCaptureValidationError",
    "CanonicalOhlcvAtomicReceiptCapture",
    "SelectedClosedCandleReceiptCapture",
    "capture_canonical_closed_ohlcv_atomic_receipts",
]
