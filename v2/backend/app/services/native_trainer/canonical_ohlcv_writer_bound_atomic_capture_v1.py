"""Bind genuine canonical-OHLCV writer provenance to per-candle receipts.

The existing atomic adapter proves exact Redis bytes, candle finality, ordered
row spans, immutable CAS retention, and one source-read receipt per selected
candle.  It deliberately does not prove which producer published the mutable
canonical Redis value.  The independent writer-receipt consumer proves that
producer identity, but deliberately does not create per-candle receipts.

This module composes those two narrow proofs without changing either one.  It
uses a writer-proof sandwich around the atomic adapter so an intervening
publication is detected even when a new writer revision republishes identical
canonical bytes.  Every child proof is freshly revalidated, their exact bytes,
window, address, producer identity, and clocks are bound into one immutable
manifest, and all downstream authority remains frozen false.

This boundary is standalone and unwired.  It does not append a ledger, publish
features, admit trainer data, produce a prediction, or authorize paper/live
execution.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any, NoReturn, cast

from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    RawRedisSourceClient,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION,
    CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION,
    CanonicalOhlcvAtomicCaptureError,
    CanonicalOhlcvAtomicCaptureIntegrityError,
    CanonicalOhlcvAtomicCaptureTransportError,
    CanonicalOhlcvAtomicCaptureValidationError,
    CanonicalOhlcvAtomicReceiptCapture,
    capture_canonical_closed_ohlcv_atomic_receipts,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_writer_receipt_consumer_v1 import (
    CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_MANIFEST_SCHEMA_VERSION,
    CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_SCHEMA_VERSION,
    CanonicalOhlcvWriterReceiptConsumerCapture,
    CanonicalOhlcvWriterReceiptConsumerIntegrityError,
    CanonicalOhlcvWriterReceiptConsumerTransportError,
    CanonicalOhlcvWriterReceiptConsumerValidationError,
    consume_current_canonical_ohlcv_writer_receipt,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
    ValidatedOHLCVClosedWindow,
)

CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_CAPTURE_SCHEMA_VERSION = (
    "canonical_ohlcv_writer_bound_atomic_capture_v1"
)
CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_MANIFEST_SCHEMA_VERSION = (
    "canonical_ohlcv_writer_bound_atomic_manifest_v1"
)
CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_EVIDENCE_CLASSIFICATION = (
    "GENUINE_WRITER_RECEIPT_SANDWICH_AND_ATOMIC_PER_CANDLE_CAS_VERIFIED"
)
CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_DOWNSTREAM_STATUS = (
    "SOURCE_INPUT_PROOF_ONLY_NO_LEDGER_FEATURE_TRAINER_PREDICTION_OR_EXECUTION_AUTHORITY"
)

# Resource/concurrency integrity limits only. They do not select a market,
# feature, signal, position, risk level, leverage, or margin allocation.
MAX_CAPTURE_ATTEMPTS = 4
MAX_COMPOSITE_MANIFEST_BYTES = 2 * 1024 * 1024

_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\." r"[0-9]{6}Z$",
    re.ASCII,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CONSTRUCTION_TOKEN = object()
_RETRYABLE_WRITER_RACE_REASONS = frozenset(
    {
        "canonical_ohlcv_consumer_pointer_race_retry_exhausted",
        "canonical_ohlcv_consumer_prepare_race_retry_exhausted",
    }
)
_DOWNSTREAM_AUTHORITY_FIELDS = (
    "durable_ledger_appended",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)


class CanonicalOhlcvWriterBoundAtomicCaptureError(RuntimeError):
    """Base fail-closed composite capture error."""


class CanonicalOhlcvWriterBoundAtomicCaptureValidationError(
    CanonicalOhlcvWriterBoundAtomicCaptureError
):
    """Caller input, source finality, freshness, or clock order is invalid."""


class CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError(
    CanonicalOhlcvWriterBoundAtomicCaptureError
):
    """Child proof, exact identity, manifest, or immutable CAS did not bind."""


class CanonicalOhlcvWriterBoundAtomicCaptureTransportError(
    CanonicalOhlcvWriterBoundAtomicCaptureError
):
    """A bounded child Redis transport operation failed."""


class _RetryableWriterPublicationRace(RuntimeError):
    """Internal signal for the two exact writer publication race outcomes."""


class _RetryableCrossProofPublicationChange(RuntimeError):
    """Internal signal when the writer sandwich does not bind one revision."""


@dataclass(frozen=True, slots=True)
class CanonicalOhlcvWriterBoundAtomicCapture:
    """Factory-authenticated writer-bound per-candle source capture."""

    schema_version: str
    manifest_schema_version: str
    evidence_classification: str
    downstream_status: str
    attempt_count: int
    publication_race_retry_count: int
    symbol: str
    timeframe: str
    source_key: str
    revision_id: str
    producer_role: str
    producer_code_sha256: str
    producer_config_sha256: str
    writer_receipt_sha256: str
    trusted_allowlist_sha256: str
    exact_payload_sha256: str
    exact_payload_byte_count: int
    row_count: int
    canonical_payload_address: SourcePayloadAddress
    latest_economic_close_time_ms: int
    max_producer_event_time_ms: int
    max_ingested_at_ms: int
    max_source_available_at_ms: int
    feature_cutoff: str
    max_producer_event_time: str
    max_ingested_at: str
    max_source_available_at: str
    writer_publication_available_at: str
    pre_writer_discovery_observed_at: str
    pre_writer_authoritative_observed_at: str
    pre_writer_consumer_observed_at: str
    atomic_server_observed_at: str
    atomic_consumer_observed_at: str
    post_writer_discovery_observed_at: str
    post_writer_authoritative_observed_at: str
    post_writer_consumer_observed_at: str
    generated_at: str
    generated_at_ms: int
    available_at: None
    decision_time: None
    execution_time: None
    pre_writer_tuple_manifest_sha256: str
    pre_writer_tuple_manifest_address: SourcePayloadAddress
    atomic_batch_id: str
    atomic_batch_material_sha256: str
    atomic_suffix_digest_sha256: str
    atomic_suffix_manifest_sha256: str
    atomic_suffix_manifest_address: SourcePayloadAddress
    ordered_selected_candle_receipt_sha256s: tuple[str, ...]
    post_writer_tuple_manifest_sha256: str
    post_writer_tuple_manifest_address: SourcePayloadAddress
    composite_manifest_sha256: str
    composite_manifest_byte_count: int
    composite_manifest_json: str = field(repr=False)
    composite_manifest_address: SourcePayloadAddress
    _pre_writer_capture: CanonicalOhlcvWriterReceiptConsumerCapture = field(
        repr=False,
        compare=False,
    )
    _atomic_capture: CanonicalOhlcvAtomicReceiptCapture = field(
        repr=False,
        compare=False,
    )
    _post_writer_capture: CanonicalOhlcvWriterReceiptConsumerCapture = field(
        repr=False,
        compare=False,
    )
    _source_payload_store: ImmutableSourcePayloadStore = field(
        repr=False,
        compare=False,
    )
    _construction_token: object = field(repr=False, compare=False)
    writer_receipt_sandwich_verified: bool = field(default=True, init=False)
    producer_identity_verified: bool = field(default=True, init=False)
    exact_payload_coherence_verified: bool = field(default=True, init=False)
    atomic_per_candle_receipts_verified: bool = field(default=True, init=False)
    immutable_cas_reopened: bool = field(default=True, init=False)
    durable_ledger_appended: bool = field(default=False, init=False)
    feature_snapshot_published: bool = field(default=False, init=False)
    feature_publication_receipt_emitted: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)
    market_performance_thresholds_applied: bool = field(default=False, init=False)
    runtime_wired: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _validate_capture(self)

    @property
    def pre_writer_capture(self) -> CanonicalOhlcvWriterReceiptConsumerCapture:
        _validate_capture(self)
        return self._pre_writer_capture

    @property
    def atomic_capture(self) -> CanonicalOhlcvAtomicReceiptCapture:
        _validate_capture(self)
        return self._atomic_capture

    @property
    def post_writer_capture(self) -> CanonicalOhlcvWriterReceiptConsumerCapture:
        _validate_capture(self)
        return self._post_writer_capture

    @property
    def exact_canonical_payload_bytes(self) -> bytes:
        _validate_capture(self)
        return self._atomic_capture.exact_full_source_payload_bytes

    @property
    def composite_manifest(self) -> dict[str, Any]:
        _validate_capture(self)
        return cast(dict[str, Any], json.loads(self.composite_manifest_json))


def _validation_error(reason: str) -> NoReturn:
    raise CanonicalOhlcvWriterBoundAtomicCaptureValidationError(reason) from None


def _integrity_error(reason: str) -> NoReturn:
    raise CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError(reason) from None


def _canonical_json_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _integrity_error("canonical_ohlcv_writer_bound_manifest_encoding_invalid")
    if not encoded or len(encoded) > MAX_COMPOSITE_MANIFEST_BYTES:
        _integrity_error("canonical_ohlcv_writer_bound_manifest_size_invalid")
    return encoded


def _parse_clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        _validation_error(reason)
    try:
        parsed = datetime.strptime(value, _CLOCK_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        _validation_error(reason)
    if parsed.strftime(_CLOCK_FORMAT) != value:
        _validation_error(reason)
    return parsed


def _ms_to_clock(value: object) -> str:
    if type(value) is not int or value < 0:
        _integrity_error("canonical_ohlcv_writer_bound_source_clock_invalid")
    try:
        parsed = _EPOCH + timedelta(milliseconds=value)
    except (OverflowError, ValueError):
        _integrity_error("canonical_ohlcv_writer_bound_source_clock_invalid")
    return parsed.strftime(_CLOCK_FORMAT)


def _clock_to_ms(value: datetime) -> int:
    delta = value - _EPOCH
    return ((delta.days * 86_400 + delta.seconds) * 1_000) + (delta.microseconds // 1_000)


def _sample_clock(clock: Callable[[], datetime]) -> tuple[str, int]:
    if not callable(clock):
        _validation_error("canonical_ohlcv_writer_bound_clock_not_callable")
    try:
        observed = clock()
    except Exception:  # noqa: BLE001 - hostile clock detail must not escape
        _validation_error("canonical_ohlcv_writer_bound_clock_failed")
    if type(observed) is not datetime or observed.tzinfo is None:
        _validation_error("canonical_ohlcv_writer_bound_clock_invalid")
    normalized = observed.astimezone(UTC)
    text = normalized.strftime(_CLOCK_FORMAT)
    parsed = _parse_clock(
        text,
        reason="canonical_ohlcv_writer_bound_clock_invalid",
    )
    return text, _clock_to_ms(parsed)


def _address_material(address: SourcePayloadAddress) -> dict[str, object]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _validate_address(
    address: object,
    *,
    expected_sha256: str,
    expected_byte_count: int,
    reason: str,
) -> SourcePayloadAddress:
    if type(address) is not SourcePayloadAddress:
        _integrity_error(reason)
    if (
        address.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or address.payload_sha256 != expected_sha256
        or address.payload_byte_count != expected_byte_count
        or address.relative_path != f"sha256/{expected_sha256[:2]}/{expected_sha256}"
    ):
        _integrity_error(reason)
    return address


def _fresh_readback(
    store: ImmutableSourcePayloadStore,
    address: SourcePayloadAddress,
    expected: bytes,
    *,
    reason: str,
) -> None:
    try:
        reopened = store.get(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError(reason) from exc
    if not hmac.compare_digest(reopened, expected):
        _integrity_error(reason)


def _capture_writer_once(
    redis_client: RawRedisSourceClient,
    store: ImmutableSourcePayloadStore,
    *,
    expected_symbol: str,
    expected_timeframe: str,
    trusted_writer_code_sha256_by_role: Mapping[str, Collection[str]],
    consumer_clock: Callable[[], datetime],
) -> CanonicalOhlcvWriterReceiptConsumerCapture:
    try:
        return consume_current_canonical_ohlcv_writer_receipt(
            redis_client,
            store,
            expected_symbol=expected_symbol,
            expected_timeframe=expected_timeframe,
            trusted_writer_code_sha256_by_role=(trusted_writer_code_sha256_by_role),
            consumer_clock=consumer_clock,
            max_attempts=1,
        )
    except CanonicalOhlcvWriterReceiptConsumerTransportError as exc:
        raise CanonicalOhlcvWriterBoundAtomicCaptureTransportError(
            "canonical_ohlcv_writer_bound_writer_transport_failed"
        ) from exc
    except CanonicalOhlcvWriterReceiptConsumerValidationError as exc:
        raise CanonicalOhlcvWriterBoundAtomicCaptureValidationError(
            "canonical_ohlcv_writer_bound_writer_validation_failed"
        ) from exc
    except CanonicalOhlcvWriterReceiptConsumerIntegrityError as exc:
        if str(exc) in _RETRYABLE_WRITER_RACE_REASONS:
            raise _RetryableWriterPublicationRace(str(exc)) from exc
        raise CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError(
            "canonical_ohlcv_writer_bound_writer_integrity_failed"
        ) from exc


def _capture_atomic_once(
    redis_client: RawRedisSourceClient,
    store: ImmutableSourcePayloadStore,
    *,
    expected_symbol: str,
    expected_timeframe: str,
    consumer_clock: Callable[[], datetime],
) -> CanonicalOhlcvAtomicReceiptCapture:
    try:
        return capture_canonical_closed_ohlcv_atomic_receipts(
            redis_client,
            store,
            expected_symbol=expected_symbol,
            expected_timeframe=expected_timeframe,
            consumer_clock=consumer_clock,
        )
    except CanonicalOhlcvAtomicCaptureTransportError as exc:
        raise CanonicalOhlcvWriterBoundAtomicCaptureTransportError(
            "canonical_ohlcv_writer_bound_atomic_transport_failed"
        ) from exc
    except CanonicalOhlcvAtomicCaptureValidationError as exc:
        raise CanonicalOhlcvWriterBoundAtomicCaptureValidationError(
            "canonical_ohlcv_writer_bound_atomic_validation_failed"
        ) from exc
    except CanonicalOhlcvAtomicCaptureIntegrityError as exc:
        raise CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError(
            "canonical_ohlcv_writer_bound_atomic_integrity_failed"
        ) from exc


def _child_state(
    pre_writer: CanonicalOhlcvWriterReceiptConsumerCapture,
    atomic: CanonicalOhlcvAtomicReceiptCapture,
    post_writer: CanonicalOhlcvWriterReceiptConsumerCapture,
) -> tuple[bytes, ValidatedOHLCVClosedWindow, tuple[str, ...]]:
    if (
        type(pre_writer) is not CanonicalOhlcvWriterReceiptConsumerCapture
        or type(atomic) is not CanonicalOhlcvAtomicReceiptCapture
        or type(post_writer) is not CanonicalOhlcvWriterReceiptConsumerCapture
    ):
        _integrity_error("canonical_ohlcv_writer_bound_child_type_invalid")
    try:
        pre_bytes = pre_writer.exact_canonical_payload_bytes
        pre_receipt_bytes = pre_writer._receipt_payload_bytes
        atomic_bytes = atomic.exact_full_source_payload_bytes
        selected = atomic._selected_candles
        post_bytes = post_writer.exact_canonical_payload_bytes
        post_receipt_bytes = post_writer._receipt_payload_bytes
    except (
        CanonicalOhlcvAtomicCaptureError,
        CanonicalOhlcvWriterReceiptConsumerIntegrityError,
        CanonicalOhlcvWriterReceiptConsumerValidationError,
    ) as exc:
        raise CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError(
            "canonical_ohlcv_writer_bound_child_revalidation_failed"
        ) from exc
    receipt_hashes = tuple(item.source_read_receipt.receipt_sha256 for item in selected)
    if (
        not hmac.compare_digest(pre_bytes, atomic_bytes)
        or not hmac.compare_digest(atomic_bytes, post_bytes)
        or not hmac.compare_digest(pre_receipt_bytes, post_receipt_bytes)
        or pre_writer.source_key != atomic.source_key
        or atomic.source_key != post_writer.source_key
        or pre_writer.revision_id != post_writer.revision_id
        or pre_writer.producer_role != post_writer.producer_role
        or pre_writer.producer_code_sha256 != post_writer.producer_code_sha256
        or pre_writer.producer_config_sha256 != post_writer.producer_config_sha256
        or pre_writer.writer_receipt_sha256 != post_writer.writer_receipt_sha256
        or pre_writer.writer_publication_available_at != post_writer.writer_publication_available_at
        or pre_writer.trusted_allowlist_sha256 != post_writer.trusted_allowlist_sha256
        or pre_writer.exact_payload_sha256 != atomic.validated_window.exact_payload_sha256
        or atomic.validated_window.exact_payload_sha256 != post_writer.exact_payload_sha256
        or pre_writer.exact_payload_byte_count != atomic.validated_window.exact_payload_byte_count
        or atomic.validated_window.exact_payload_byte_count != post_writer.exact_payload_byte_count
        or pre_writer.row_count != atomic.raw_row_count
        or atomic.raw_row_count != post_writer.row_count
        or pre_writer.validated_window != atomic.validated_window
        or atomic.validated_window != post_writer.validated_window
        or pre_writer.canonical_payload_address != atomic.full_source_payload_address
        or atomic.full_source_payload_address != post_writer.canonical_payload_address
        or not receipt_hashes
        or len(receipt_hashes) != atomic.selected_row_count
        or any(
            type(value) is not str or _SHA256_RE.fullmatch(value) is None
            for value in receipt_hashes
        )
    ):
        raise _RetryableCrossProofPublicationChange(
            "canonical_ohlcv_writer_bound_cross_proof_publication_changed"
        )
    return atomic_bytes, atomic.validated_window, receipt_hashes


def _validated_clock_material(
    *,
    window: ValidatedOHLCVClosedWindow,
    pre_writer: CanonicalOhlcvWriterReceiptConsumerCapture,
    atomic: CanonicalOhlcvAtomicReceiptCapture,
    post_writer: CanonicalOhlcvWriterReceiptConsumerCapture,
    generated_at: str,
    generated_at_ms: int,
) -> dict[str, int | str]:
    source_clocks = {
        "latest_economic_close_time_ms": window.latest_economic_close_time,
        "max_producer_event_time_ms": window.latest_producer_event_time,
        "max_ingested_at_ms": window.max_ingested_at,
        "max_source_available_at_ms": window.max_available_at,
        "feature_cutoff": _ms_to_clock(window.latest_economic_close_time),
        "max_producer_event_time": _ms_to_clock(window.latest_producer_event_time),
        "max_ingested_at": _ms_to_clock(window.max_ingested_at),
        "max_source_available_at": _ms_to_clock(window.max_available_at),
    }
    ordered = (
        _parse_clock(
            source_clocks["feature_cutoff"],
            reason="canonical_ohlcv_writer_bound_feature_cutoff_invalid",
        ),
        _parse_clock(
            source_clocks["max_producer_event_time"],
            reason="canonical_ohlcv_writer_bound_producer_event_time_invalid",
        ),
        _parse_clock(
            source_clocks["max_ingested_at"],
            reason="canonical_ohlcv_writer_bound_ingested_at_invalid",
        ),
        _parse_clock(
            source_clocks["max_source_available_at"],
            reason="canonical_ohlcv_writer_bound_source_available_at_invalid",
        ),
        _parse_clock(
            pre_writer.writer_publication_available_at,
            reason="canonical_ohlcv_writer_bound_publication_clock_invalid",
        ),
        _parse_clock(
            pre_writer.discovery_server_observed_at,
            reason="canonical_ohlcv_writer_bound_pre_discovery_clock_invalid",
        ),
        _parse_clock(
            pre_writer.authoritative_server_observed_at,
            reason="canonical_ohlcv_writer_bound_pre_authoritative_clock_invalid",
        ),
        _parse_clock(
            pre_writer.consumer_observed_at,
            reason="canonical_ohlcv_writer_bound_pre_consumer_clock_invalid",
        ),
        _parse_clock(
            atomic.atomic_server_observed_at,
            reason="canonical_ohlcv_writer_bound_atomic_server_clock_invalid",
        ),
        _parse_clock(
            atomic.consumer_observed_at,
            reason="canonical_ohlcv_writer_bound_atomic_consumer_clock_invalid",
        ),
        _parse_clock(
            post_writer.discovery_server_observed_at,
            reason="canonical_ohlcv_writer_bound_post_discovery_clock_invalid",
        ),
        _parse_clock(
            post_writer.authoritative_server_observed_at,
            reason="canonical_ohlcv_writer_bound_post_authoritative_clock_invalid",
        ),
        _parse_clock(
            post_writer.consumer_observed_at,
            reason="canonical_ohlcv_writer_bound_post_consumer_clock_invalid",
        ),
        _parse_clock(
            generated_at,
            reason="canonical_ohlcv_writer_bound_generated_at_invalid",
        ),
    )
    if any(later < earlier for earlier, later in pairwise(ordered)):
        _validation_error("canonical_ohlcv_writer_bound_clock_order_invalid")
    if _clock_to_ms(ordered[-1]) != generated_at_ms:
        _integrity_error("canonical_ohlcv_writer_bound_generated_at_binding_invalid")
    duration_ms = TIMEFRAME_DURATION_MS.get(window.timeframe)
    if type(duration_ms) is not int or duration_ms <= 0:
        _integrity_error("canonical_ohlcv_writer_bound_timeframe_duration_invalid")
    expected_latest_close = (generated_at_ms // duration_ms) * duration_ms - 1
    if window.latest_economic_close_time != expected_latest_close:
        _validation_error("canonical_ohlcv_writer_bound_stale_at_generation")
    return source_clocks


def _manifest_material(
    *,
    attempt_count: int,
    symbol: str,
    timeframe: str,
    pre_writer: CanonicalOhlcvWriterReceiptConsumerCapture,
    atomic: CanonicalOhlcvAtomicReceiptCapture,
    post_writer: CanonicalOhlcvWriterReceiptConsumerCapture,
    clock_material: Mapping[str, int | str],
    generated_at: str,
    generated_at_ms: int,
    receipt_hashes: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "schema_version": CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_CAPTURE_SCHEMA_VERSION,
        "manifest_schema_version": (CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_MANIFEST_SCHEMA_VERSION),
        "evidence_classification": (CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_EVIDENCE_CLASSIFICATION),
        "downstream_status": (CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_DOWNSTREAM_STATUS),
        "attempt_count": attempt_count,
        "publication_race_retry_count": attempt_count - 1,
        "symbol": symbol,
        "timeframe": timeframe,
        "source_key": atomic.source_key,
        "revision_id": pre_writer.revision_id,
        "producer_role": pre_writer.producer_role,
        "producer_code_sha256": pre_writer.producer_code_sha256,
        "producer_config_sha256": pre_writer.producer_config_sha256,
        "writer_receipt_sha256": pre_writer.writer_receipt_sha256,
        "trusted_allowlist_sha256": pre_writer.trusted_allowlist_sha256,
        "exact_payload_sha256": atomic.validated_window.exact_payload_sha256,
        "exact_payload_byte_count": atomic.validated_window.exact_payload_byte_count,
        "row_count": atomic.raw_row_count,
        "canonical_payload_address": _address_material(atomic.full_source_payload_address),
        **dict(clock_material),
        "writer_publication_available_at": (pre_writer.writer_publication_available_at),
        "pre_writer_discovery_observed_at": (pre_writer.discovery_server_observed_at),
        "pre_writer_authoritative_observed_at": (pre_writer.authoritative_server_observed_at),
        "pre_writer_consumer_observed_at": pre_writer.consumer_observed_at,
        "atomic_server_observed_at": atomic.atomic_server_observed_at,
        "atomic_consumer_observed_at": atomic.consumer_observed_at,
        "post_writer_discovery_observed_at": (post_writer.discovery_server_observed_at),
        "post_writer_authoritative_observed_at": (post_writer.authoritative_server_observed_at),
        "post_writer_consumer_observed_at": post_writer.consumer_observed_at,
        "generated_at": generated_at,
        "generated_at_ms": generated_at_ms,
        "available_at": None,
        "decision_time": None,
        "execution_time": None,
        "pre_writer_capture_schema_version": (
            CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_SCHEMA_VERSION
        ),
        "pre_writer_tuple_manifest_schema_version": (
            CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_MANIFEST_SCHEMA_VERSION
        ),
        "pre_writer_tuple_manifest_sha256": pre_writer.tuple_manifest_sha256,
        "pre_writer_tuple_manifest_address": _address_material(pre_writer.tuple_manifest_address),
        "atomic_capture_schema_version": CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION,
        "atomic_suffix_manifest_schema_version": (CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION),
        "atomic_batch_id": atomic.atomic_batch_id,
        "atomic_batch_material_sha256": atomic.atomic_batch_material_sha256,
        "atomic_suffix_digest_sha256": atomic.suffix_digest_sha256,
        "atomic_suffix_manifest_sha256": (atomic.suffix_manifest_address.payload_sha256),
        "atomic_suffix_manifest_address": _address_material(atomic.suffix_manifest_address),
        "ordered_selected_candle_receipt_sha256s": list(receipt_hashes),
        "post_writer_capture_schema_version": (
            CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_SCHEMA_VERSION
        ),
        "post_writer_tuple_manifest_schema_version": (
            CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_MANIFEST_SCHEMA_VERSION
        ),
        "post_writer_tuple_manifest_sha256": post_writer.tuple_manifest_sha256,
        "post_writer_tuple_manifest_address": _address_material(post_writer.tuple_manifest_address),
        "writer_receipt_sandwich_verified": True,
        "producer_identity_verified": True,
        "exact_payload_coherence_verified": True,
        "atomic_per_candle_receipts_verified": True,
        "immutable_cas_reopened": True,
        "market_performance_thresholds_applied": False,
        "runtime_wired": False,
        **{field_name: False for field_name in _DOWNSTREAM_AUTHORITY_FIELDS},
    }


def _capture_manifest_material(
    capture: CanonicalOhlcvWriterBoundAtomicCapture,
) -> dict[str, Any]:
    clock_material: dict[str, int | str] = {
        "latest_economic_close_time_ms": capture.latest_economic_close_time_ms,
        "max_producer_event_time_ms": capture.max_producer_event_time_ms,
        "max_ingested_at_ms": capture.max_ingested_at_ms,
        "max_source_available_at_ms": capture.max_source_available_at_ms,
        "feature_cutoff": capture.feature_cutoff,
        "max_producer_event_time": capture.max_producer_event_time,
        "max_ingested_at": capture.max_ingested_at,
        "max_source_available_at": capture.max_source_available_at,
    }
    return _manifest_material(
        attempt_count=capture.attempt_count,
        symbol=capture.symbol,
        timeframe=capture.timeframe,
        pre_writer=capture._pre_writer_capture,
        atomic=capture._atomic_capture,
        post_writer=capture._post_writer_capture,
        clock_material=clock_material,
        generated_at=capture.generated_at,
        generated_at_ms=capture.generated_at_ms,
        receipt_hashes=capture.ordered_selected_candle_receipt_sha256s,
    )


def _validate_capture(capture: CanonicalOhlcvWriterBoundAtomicCapture) -> None:
    if capture._construction_token is not _CONSTRUCTION_TOKEN:
        _integrity_error("canonical_ohlcv_writer_bound_factory_construction_required")
    if (
        capture.schema_version != CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_CAPTURE_SCHEMA_VERSION
        or capture.manifest_schema_version
        != CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_MANIFEST_SCHEMA_VERSION
        or capture.evidence_classification
        != CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_EVIDENCE_CLASSIFICATION
        or capture.downstream_status != CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_DOWNSTREAM_STATUS
        or type(capture.attempt_count) is not int
        or not 1 <= capture.attempt_count <= MAX_CAPTURE_ATTEMPTS
        or capture.publication_race_retry_count != capture.attempt_count - 1
        or capture.available_at is not None
        or capture.decision_time is not None
        or capture.execution_time is not None
        or capture.market_performance_thresholds_applied is not False
        or capture.runtime_wired is not False
        or type(capture._source_payload_store) is not ImmutableSourcePayloadStore
        or type(capture._pre_writer_capture) is not CanonicalOhlcvWriterReceiptConsumerCapture
        or type(capture._atomic_capture) is not CanonicalOhlcvAtomicReceiptCapture
        or type(capture._post_writer_capture) is not CanonicalOhlcvWriterReceiptConsumerCapture
        or capture._pre_writer_capture._source_payload_store is not capture._source_payload_store
        or capture._atomic_capture._source_payload_store is not capture._source_payload_store
        or capture._post_writer_capture._source_payload_store is not capture._source_payload_store
        or any(
            getattr(capture, field_name) is not False for field_name in _DOWNSTREAM_AUTHORITY_FIELDS
        )
        or any(
            value is not True
            for value in (
                capture.writer_receipt_sandwich_verified,
                capture.producer_identity_verified,
                capture.exact_payload_coherence_verified,
                capture.atomic_per_candle_receipts_verified,
                capture.immutable_cas_reopened,
            )
        )
    ):
        _integrity_error("canonical_ohlcv_writer_bound_capture_contract_invalid")
    try:
        exact_bytes, window, receipt_hashes = _child_state(
            capture._pre_writer_capture,
            capture._atomic_capture,
            capture._post_writer_capture,
        )
    except _RetryableCrossProofPublicationChange as exc:
        raise CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError(
            "canonical_ohlcv_writer_bound_post_return_child_mismatch"
        ) from exc
    clock_material = _validated_clock_material(
        window=window,
        pre_writer=capture._pre_writer_capture,
        atomic=capture._atomic_capture,
        post_writer=capture._post_writer_capture,
        generated_at=capture.generated_at,
        generated_at_ms=capture.generated_at_ms,
    )
    if (
        capture.symbol != window.symbol
        or capture.timeframe != window.timeframe
        or capture.source_key != window.source_key
        or capture.revision_id != capture._pre_writer_capture.revision_id
        or capture.producer_role != capture._pre_writer_capture.producer_role
        or capture.producer_code_sha256 != capture._pre_writer_capture.producer_code_sha256
        or capture.producer_config_sha256 != capture._pre_writer_capture.producer_config_sha256
        or capture.writer_receipt_sha256 != capture._pre_writer_capture.writer_receipt_sha256
        or capture.trusted_allowlist_sha256 != capture._pre_writer_capture.trusted_allowlist_sha256
        or capture.exact_payload_sha256 != hashlib.sha256(exact_bytes).hexdigest()
        or capture.exact_payload_byte_count != len(exact_bytes)
        or capture.row_count != window.row_count
        or capture.canonical_payload_address != capture._atomic_capture.full_source_payload_address
        or capture.latest_economic_close_time_ms != clock_material["latest_economic_close_time_ms"]
        or capture.max_producer_event_time_ms != clock_material["max_producer_event_time_ms"]
        or capture.max_ingested_at_ms != clock_material["max_ingested_at_ms"]
        or capture.max_source_available_at_ms != clock_material["max_source_available_at_ms"]
        or capture.feature_cutoff != clock_material["feature_cutoff"]
        or capture.max_producer_event_time != clock_material["max_producer_event_time"]
        or capture.max_ingested_at != clock_material["max_ingested_at"]
        or capture.max_source_available_at != clock_material["max_source_available_at"]
        or capture.writer_publication_available_at
        != capture._pre_writer_capture.writer_publication_available_at
        or capture.pre_writer_discovery_observed_at
        != capture._pre_writer_capture.discovery_server_observed_at
        or capture.pre_writer_authoritative_observed_at
        != capture._pre_writer_capture.authoritative_server_observed_at
        or capture.pre_writer_consumer_observed_at
        != capture._pre_writer_capture.consumer_observed_at
        or capture.atomic_server_observed_at != capture._atomic_capture.atomic_server_observed_at
        or capture.atomic_consumer_observed_at != capture._atomic_capture.consumer_observed_at
        or capture.post_writer_discovery_observed_at
        != capture._post_writer_capture.discovery_server_observed_at
        or capture.post_writer_authoritative_observed_at
        != capture._post_writer_capture.authoritative_server_observed_at
        or capture.post_writer_consumer_observed_at
        != capture._post_writer_capture.consumer_observed_at
        or capture.pre_writer_tuple_manifest_sha256
        != capture._pre_writer_capture.tuple_manifest_sha256
        or capture.pre_writer_tuple_manifest_address
        != capture._pre_writer_capture.tuple_manifest_address
        or capture.atomic_batch_id != capture._atomic_capture.atomic_batch_id
        or capture.atomic_batch_material_sha256
        != capture._atomic_capture.atomic_batch_material_sha256
        or capture.atomic_suffix_digest_sha256 != capture._atomic_capture.suffix_digest_sha256
        or capture.atomic_suffix_manifest_sha256
        != capture._atomic_capture.suffix_manifest_address.payload_sha256
        or capture.atomic_suffix_manifest_address != capture._atomic_capture.suffix_manifest_address
        or capture.ordered_selected_candle_receipt_sha256s != receipt_hashes
        or capture.post_writer_tuple_manifest_sha256
        != capture._post_writer_capture.tuple_manifest_sha256
        or capture.post_writer_tuple_manifest_address
        != capture._post_writer_capture.tuple_manifest_address
    ):
        _integrity_error("canonical_ohlcv_writer_bound_capture_binding_invalid")
    _validate_address(
        capture.canonical_payload_address,
        expected_sha256=capture.exact_payload_sha256,
        expected_byte_count=capture.exact_payload_byte_count,
        reason="canonical_ohlcv_writer_bound_canonical_address_invalid",
    )
    _fresh_readback(
        capture._source_payload_store,
        capture.canonical_payload_address,
        exact_bytes,
        reason="canonical_ohlcv_writer_bound_canonical_cas_readback_failed",
    )
    manifest_bytes = _canonical_json_bytes(_capture_manifest_material(capture))
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    try:
        provided_manifest_bytes = capture.composite_manifest_json.encode("ascii")
    except (AttributeError, UnicodeEncodeError):
        _integrity_error("canonical_ohlcv_writer_bound_manifest_json_invalid")
    if (
        not hmac.compare_digest(manifest_bytes, provided_manifest_bytes)
        or capture.composite_manifest_sha256 != manifest_sha256
        or capture.composite_manifest_byte_count != len(manifest_bytes)
    ):
        _integrity_error("canonical_ohlcv_writer_bound_manifest_binding_invalid")
    _validate_address(
        capture.composite_manifest_address,
        expected_sha256=manifest_sha256,
        expected_byte_count=len(manifest_bytes),
        reason="canonical_ohlcv_writer_bound_manifest_address_invalid",
    )
    _fresh_readback(
        capture._source_payload_store,
        capture.composite_manifest_address,
        manifest_bytes,
        reason="canonical_ohlcv_writer_bound_manifest_cas_readback_failed",
    )


def capture_canonical_ohlcv_writer_bound_atomic(
    redis_client: RawRedisSourceClient,
    source_payload_store: ImmutableSourcePayloadStore,
    *,
    expected_symbol: str,
    expected_timeframe: str,
    trusted_writer_code_sha256_by_role: Mapping[str, Collection[str]],
    consumer_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    max_attempts: int = MAX_CAPTURE_ATTEMPTS,
) -> CanonicalOhlcvWriterBoundAtomicCapture:
    """Capture one writer-stable, exact, per-candle canonical OHLCV input."""

    if type(source_payload_store) is not ImmutableSourcePayloadStore:
        _validation_error("canonical_ohlcv_writer_bound_authentic_store_required")
    if type(max_attempts) is not int or not 1 <= max_attempts <= MAX_CAPTURE_ATTEMPTS:
        _validation_error("canonical_ohlcv_writer_bound_attempts_invalid")

    for attempt in range(1, max_attempts + 1):
        try:
            pre_writer = _capture_writer_once(
                redis_client,
                source_payload_store,
                expected_symbol=expected_symbol,
                expected_timeframe=expected_timeframe,
                trusted_writer_code_sha256_by_role=(trusted_writer_code_sha256_by_role),
                consumer_clock=consumer_clock,
            )
            atomic = _capture_atomic_once(
                redis_client,
                source_payload_store,
                expected_symbol=expected_symbol,
                expected_timeframe=expected_timeframe,
                consumer_clock=consumer_clock,
            )
            post_writer = _capture_writer_once(
                redis_client,
                source_payload_store,
                expected_symbol=expected_symbol,
                expected_timeframe=expected_timeframe,
                trusted_writer_code_sha256_by_role=(trusted_writer_code_sha256_by_role),
                consumer_clock=consumer_clock,
            )
            exact_bytes, window, receipt_hashes = _child_state(
                pre_writer,
                atomic,
                post_writer,
            )
        except (
            _RetryableWriterPublicationRace,
            _RetryableCrossProofPublicationChange,
        ) as exc:
            if attempt < max_attempts:
                continue
            raise CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError(
                "canonical_ohlcv_writer_bound_publication_race_retry_exhausted"
            ) from exc

        _fresh_readback(
            source_payload_store,
            atomic.full_source_payload_address,
            exact_bytes,
            reason="canonical_ohlcv_writer_bound_canonical_cas_readback_failed",
        )
        generated_at, generated_at_ms = _sample_clock(consumer_clock)
        clock_material = _validated_clock_material(
            window=window,
            pre_writer=pre_writer,
            atomic=atomic,
            post_writer=post_writer,
            generated_at=generated_at,
            generated_at_ms=generated_at_ms,
        )
        manifest = _manifest_material(
            attempt_count=attempt,
            symbol=window.symbol,
            timeframe=window.timeframe,
            pre_writer=pre_writer,
            atomic=atomic,
            post_writer=post_writer,
            clock_material=clock_material,
            generated_at=generated_at,
            generated_at_ms=generated_at_ms,
            receipt_hashes=receipt_hashes,
        )
        manifest_bytes = _canonical_json_bytes(manifest)
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        try:
            manifest_address = source_payload_store.put(
                manifest_bytes,
                expected_sha256=manifest_sha256,
                expected_byte_count=len(manifest_bytes),
            )
        except SourcePayloadStoreError as exc:
            raise CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError(
                "canonical_ohlcv_writer_bound_manifest_cas_capture_failed"
            ) from exc
        _fresh_readback(
            source_payload_store,
            manifest_address,
            manifest_bytes,
            reason="canonical_ohlcv_writer_bound_manifest_cas_readback_failed",
        )
        return CanonicalOhlcvWriterBoundAtomicCapture(
            schema_version=(CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_CAPTURE_SCHEMA_VERSION),
            manifest_schema_version=(CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_MANIFEST_SCHEMA_VERSION),
            evidence_classification=(CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_EVIDENCE_CLASSIFICATION),
            downstream_status=(CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_DOWNSTREAM_STATUS),
            attempt_count=attempt,
            publication_race_retry_count=attempt - 1,
            symbol=window.symbol,
            timeframe=window.timeframe,
            source_key=window.source_key,
            revision_id=pre_writer.revision_id,
            producer_role=pre_writer.producer_role,
            producer_code_sha256=pre_writer.producer_code_sha256,
            producer_config_sha256=pre_writer.producer_config_sha256,
            writer_receipt_sha256=pre_writer.writer_receipt_sha256,
            trusted_allowlist_sha256=pre_writer.trusted_allowlist_sha256,
            exact_payload_sha256=window.exact_payload_sha256,
            exact_payload_byte_count=window.exact_payload_byte_count,
            row_count=window.row_count,
            canonical_payload_address=atomic.full_source_payload_address,
            latest_economic_close_time_ms=window.latest_economic_close_time,
            max_producer_event_time_ms=window.latest_producer_event_time,
            max_ingested_at_ms=window.max_ingested_at,
            max_source_available_at_ms=window.max_available_at,
            feature_cutoff=cast(str, clock_material["feature_cutoff"]),
            max_producer_event_time=cast(
                str,
                clock_material["max_producer_event_time"],
            ),
            max_ingested_at=cast(str, clock_material["max_ingested_at"]),
            max_source_available_at=cast(
                str,
                clock_material["max_source_available_at"],
            ),
            writer_publication_available_at=(pre_writer.writer_publication_available_at),
            pre_writer_discovery_observed_at=(pre_writer.discovery_server_observed_at),
            pre_writer_authoritative_observed_at=(pre_writer.authoritative_server_observed_at),
            pre_writer_consumer_observed_at=pre_writer.consumer_observed_at,
            atomic_server_observed_at=atomic.atomic_server_observed_at,
            atomic_consumer_observed_at=atomic.consumer_observed_at,
            post_writer_discovery_observed_at=(post_writer.discovery_server_observed_at),
            post_writer_authoritative_observed_at=(post_writer.authoritative_server_observed_at),
            post_writer_consumer_observed_at=post_writer.consumer_observed_at,
            generated_at=generated_at,
            generated_at_ms=generated_at_ms,
            available_at=None,
            decision_time=None,
            execution_time=None,
            pre_writer_tuple_manifest_sha256=pre_writer.tuple_manifest_sha256,
            pre_writer_tuple_manifest_address=pre_writer.tuple_manifest_address,
            atomic_batch_id=atomic.atomic_batch_id,
            atomic_batch_material_sha256=atomic.atomic_batch_material_sha256,
            atomic_suffix_digest_sha256=atomic.suffix_digest_sha256,
            atomic_suffix_manifest_sha256=(atomic.suffix_manifest_address.payload_sha256),
            atomic_suffix_manifest_address=atomic.suffix_manifest_address,
            ordered_selected_candle_receipt_sha256s=receipt_hashes,
            post_writer_tuple_manifest_sha256=post_writer.tuple_manifest_sha256,
            post_writer_tuple_manifest_address=post_writer.tuple_manifest_address,
            composite_manifest_sha256=manifest_sha256,
            composite_manifest_byte_count=len(manifest_bytes),
            composite_manifest_json=manifest_bytes.decode("ascii"),
            composite_manifest_address=manifest_address,
            _pre_writer_capture=pre_writer,
            _atomic_capture=atomic,
            _post_writer_capture=post_writer,
            _source_payload_store=source_payload_store,
            _construction_token=_CONSTRUCTION_TOKEN,
        )
    _integrity_error("canonical_ohlcv_writer_bound_capture_retry_exhausted")


__all__ = [
    "CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_CAPTURE_SCHEMA_VERSION",
    "CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_DOWNSTREAM_STATUS",
    "CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_EVIDENCE_CLASSIFICATION",
    "CANONICAL_OHLCV_WRITER_BOUND_ATOMIC_MANIFEST_SCHEMA_VERSION",
    "CanonicalOhlcvWriterBoundAtomicCapture",
    "CanonicalOhlcvWriterBoundAtomicCaptureError",
    "CanonicalOhlcvWriterBoundAtomicCaptureIntegrityError",
    "CanonicalOhlcvWriterBoundAtomicCaptureTransportError",
    "CanonicalOhlcvWriterBoundAtomicCaptureValidationError",
    "capture_canonical_ohlcv_writer_bound_atomic",
]
