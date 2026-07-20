"""Dormant same-process semantic replay of one canonical OHLCV suffix manifest.

The only external evidence accepted by this boundary is a service-selected
immutable-CAS root, an exact manifest content address, and an exact decision
context.  The manifest, the complete source value, and every selected row are
freshly reopened through :class:`ImmutableSourcePayloadReaderV4`.  Exact JSON,
content addresses, row byte spans, the committed 30-field closed-OHLCV ABI,
the complete latest contiguous suffix, and every v4 source-read receipt are
then independently replayed.

This module is intentionally dormant and audit-only.  A matching digest is not
proof that an authorized factory wrote an object, and Redis transport evidence
is not upstream producer authentication.  Consequently success grants no
factory, upstream, transport, ledger, dependency, feature, trainer,
prediction, paper-trading, live-execution, or runtime authority.  It performs
no writes, signing, key lookup, network I/O, Redis access, trainer admission,
or trading action.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import NoReturn, cast

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
    CANONICAL_OHLCV_FINALITY_VERIFIER,
    CANONICAL_OHLCV_ROW_PAYLOAD_TYPE,
    CANONICAL_OHLCV_SUFFIX_DIGEST_SCHEMA_VERSION,
    CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION,
    MAX_SUFFIX_MANIFEST_BYTES,
)
from v2.backend.app.services.native_trainer.feature_window_dependency_contract import (
    FeatureWindowContractError,
    FullContiguousCoreInputBinding,
    bind_full_contiguous_core_ta_input,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_reader_v4 import (
    ImmutableSourcePayloadReaderV4,
    ImmutableSourcePayloadReaderV4Error,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    SourcePayloadAddress,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    MAX_OHLCV_CLOSED_PAYLOAD_BYTES,
    MAX_OHLCV_CLOSED_ROWS,
    SUPPORTED_TRAINER_TIMEFRAMES,
    TIMEFRAME_DURATION_MS,
    OHLCVClosedWindowValidationError,
    ValidatedClosedCandle,
    ValidatedOHLCVClosedWindow,
    validate_ohlcv_closed_window,
)
from v2.backend.app.services.native_trainer.source_read_receipt_v4 import (
    SOURCE_READ_RECEIPT_V4_FINALITY_TYPE,
    SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION,
    SourceReadReceiptV4Error,
    validate_source_read_receipt_v4,
)

CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_SCHEMA_VERSION = (
    "canonical_ohlcv_manifest_semantic_replay_v4"
)
CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_EVIDENCE_CLASSIFICATION = (
    "CAS_REOPENED_CANONICAL_OHLCV_MANIFEST_SEMANTIC_AUDIT_ONLY"
)
CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_DOWNSTREAM_STATUS = (
    "NO_FACTORY_UPSTREAM_TRANSPORT_LEDGER_DEPENDENCY_FEATURE_TRAINER_OR_EXECUTION_AUTHORITY"
)

_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_SIGNED_64 = (1 << 63) - 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$", re.ASCII)

_ADDRESS_FIELDS = frozenset(
    {"schema_version", "payload_sha256", "payload_byte_count", "relative_path"}
)
_MANIFEST_FIELDS = frozenset(
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
_SELECTED_ROW_FIELDS = frozenset(
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
_SUFFIX_FIELDS = frozenset(
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
_SUFFIX_ROW_FIELDS = frozenset(
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
_ATOMIC_FIELDS = frozenset(
    {
        "schema_version",
        "consumer_eligible",
        "downstream_status",
        "evidence_classification",
        "ledger_receipt_emitted",
        "live_execution_authorized",
        "paper_provenance_only",
        "read_only",
        "redis_payload_read_operation",
        "redis_transaction_command_order_per_key",
        "max_aggregate_payload_bytes",
        "max_batch_materialized_payload_bytes",
        "max_range_reply_bytes",
        "max_source_keys_per_batch",
        "max_source_payload_bytes",
        "results",
        "server_observed_at",
        "server_time_clock_semantics",
        "server_time_is_consumer_observed_at",
        "server_time_microseconds",
        "server_time_seconds",
        "source_finality_attested",
        "source_schema_attested",
        "total_payload_byte_count",
        "transport_authenticity_attested",
    }
)
_ATOMIC_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "source_key",
        "source_key_sha256",
        "redis_type",
        "present",
        "payload_sha256",
        "payload_byte_count",
        "pttl_ms",
        "server_time_clock_semantics",
        "server_time_is_consumer_observed_at",
        "source_finality_attested",
        "source_schema_attested",
        "transport_authenticity_attested",
        "read_only",
        "paper_provenance_only",
        "live_execution_authorized",
        "ledger_receipt_emitted",
        "consumer_eligible",
    }
)
_MANIFEST_FALSE_FIELDS = (
    "durable_ledger_appended",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)
_RESULT_FALSE_AUTHORITY_FIELDS = (
    "factory_capture_authenticated",
    "factory_receipt_authenticated",
    "factory_authorized",
    "upstream_producer_authenticated",
    "atomic_transport_authenticated",
    "transport_authenticated",
    "transport_authenticity_attested",
    "source_attestation_authenticated",
    "ledger_authorized",
    "ledger_receipt_emitted",
    "durable_ledger_appended",
    "durable_ledger_membership_verified",
    "dependency_authorized",
    "dependency_manifest_bound",
    "dependency_complete",
    "per_field_receipt_bound",
    "source_scope_complete",
    "feature_authorized",
    "feature_snapshot_authorized",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "runtime_wired",
)


class CanonicalOhlcvManifestSemanticReplayV4Error(RuntimeError):
    """The exact manifest, CAS, source schema, receipt, or decision replay failed."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _StrictJsonError(ValueError):
    """Internal marker for duplicate keys, floats, constants, or large integers."""


def _fail(reason: str) -> NoReturn:
    raise CanonicalOhlcvManifestSemanticReplayV4Error(reason) from None


def _duplicate_rejecting_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonError("duplicate_key")
        result[key] = value
    return result


def _parse_bounded_int(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 19:
        raise _StrictJsonError("integer_out_of_range")
    parsed = int(value)
    if not -_MAX_SIGNED_64 - 1 <= parsed <= _MAX_SIGNED_64:
        raise _StrictJsonError("integer_out_of_range")
    return parsed


def _reject_float(_value: str) -> NoReturn:
    raise _StrictJsonError("float_forbidden")


def _reject_constant(_value: str) -> NoReturn:
    raise _StrictJsonError("constant_forbidden")


def _canonical_json_bytes(value: object, *, reason: str) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail(reason)


def _parse_exact_canonical_object(
    exact_bytes: object,
    *,
    fields: frozenset[str],
    reason: str,
) -> dict[str, object]:
    if type(exact_bytes) is not bytes:
        _fail(reason)
    payload = exact_bytes
    if not 1 <= len(payload) <= MAX_SUFFIX_MANIFEST_BYTES:
        _fail(reason)
    try:
        text = payload.decode("ascii", errors="strict")
        decoded = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_int=_parse_bounded_int,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        _StrictJsonError,
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
    ):
        _fail(reason)
    if type(decoded) is not dict:
        _fail(reason)
    result = cast(dict[str, object], decoded)
    if frozenset(result) != fields:
        _fail(reason)
    if _canonical_json_bytes(result, reason=reason) != payload:
        _fail(reason)
    return result


def _parse_nested_canonical_object(
    value: object,
    *,
    fields: frozenset[str],
    reason: str,
) -> dict[str, object]:
    if type(value) is not str:
        _fail(reason)
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        _fail(reason)
    return _parse_exact_canonical_object(encoded, fields=fields, reason=reason)


def _exact_dict(
    value: object,
    *,
    fields: frozenset[str],
    reason: str,
) -> dict[str, object]:
    if type(value) is not dict:
        _fail(reason)
    result = cast(dict[str, object], value)
    if frozenset(result) != fields:
        _fail(reason)
    return result


def _exact_list(value: object, *, reason: str) -> list[object]:
    if type(value) is not list:
        _fail(reason)
    return cast(list[object], value)


def _exact_str(value: object, *, reason: str) -> str:
    if type(value) is not str:
        _fail(reason)
    return value


def _exact_int(
    value: object,
    *,
    minimum: int,
    maximum: int = _MAX_SIGNED_64,
    reason: str,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(reason)
    return value


def _required_sha256(value: object, *, reason: str) -> str:
    text = _exact_str(value, reason=reason)
    if _SHA256_RE.fullmatch(text) is None:
        _fail(reason)
    return text


def _parse_clock(value: object, *, reason: str) -> tuple[str, datetime, int]:
    text = _exact_str(value, reason=reason)
    try:
        parsed = datetime.strptime(text, _CLOCK_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        _fail(reason)
    if parsed < _EPOCH:
        _fail(reason)
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if canonical != text:
        _fail(reason)
    delta = parsed - _EPOCH
    milliseconds = ((delta.days * 86_400 + delta.seconds) * 1_000) + (delta.microseconds // 1_000)
    return text, parsed, milliseconds


def _ms_to_clock(value: object, *, reason: str) -> str:
    milliseconds = _exact_int(value, minimum=0, reason=reason)
    try:
        resolved = _EPOCH + timedelta(milliseconds=milliseconds)
    except (OverflowError, ValueError):
        _fail(reason)
    return resolved.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _expected_latest_close(*, observed_at_ms: int, timeframe: str) -> int:
    duration = TIMEFRAME_DURATION_MS[timeframe]
    result = (observed_at_ms // duration) * duration - 1
    if result < 0:
        _fail("canonical_ohlcv_manifest_replay_decision_context_invalid")
    return result


def _address_from_material(
    value: object,
    *,
    maximum_byte_count: int,
    expected_byte_count: int | None = None,
    reason: str,
) -> SourcePayloadAddress:
    material = _exact_dict(value, fields=_ADDRESS_FIELDS, reason=reason)
    schema = _exact_str(material["schema_version"], reason=reason)
    digest = _required_sha256(material["payload_sha256"], reason=reason)
    count = _exact_int(
        material["payload_byte_count"],
        minimum=1,
        maximum=maximum_byte_count,
        reason=reason,
    )
    relative_path = _exact_str(material["relative_path"], reason=reason)
    if (
        schema != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or relative_path != f"sha256/{digest[:2]}/{digest}"
        or expected_byte_count is not None
        and count != expected_byte_count
    ):
        _fail(reason)
    return SourcePayloadAddress(
        schema_version=schema,
        payload_sha256=digest,
        payload_byte_count=count,
        relative_path=relative_path,
    )


def _snapshot_manifest_address(
    value: object,
) -> tuple[SourcePayloadAddress, str, int]:
    """Detach one exact manifest address without invoking caller-controlled hooks."""

    reason = "canonical_ohlcv_manifest_replay_manifest_address_invalid"
    if type(value) is not SourcePayloadAddress:
        _fail(reason)
    try:
        schema_version = object.__getattribute__(value, "schema_version")
        payload_sha256 = object.__getattribute__(value, "payload_sha256")
        payload_byte_count = object.__getattribute__(value, "payload_byte_count")
        relative_path = object.__getattribute__(value, "relative_path")
    except (AttributeError, TypeError):
        _fail(reason)
    detached = _address_from_material(
        {
            "schema_version": schema_version,
            "payload_sha256": payload_sha256,
            "payload_byte_count": payload_byte_count,
            "relative_path": relative_path,
        },
        maximum_byte_count=MAX_SUFFIX_MANIFEST_BYTES,
        reason=reason,
    )
    return detached, detached.payload_sha256, detached.payload_byte_count


def _read_cas(
    reader: ImmutableSourcePayloadReaderV4,
    address: SourcePayloadAddress,
    *,
    reason: str,
) -> bytes:
    try:
        return reader.read(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count,
            address=address,
        )
    except ImmutableSourcePayloadReaderV4Error as exc:
        raise CanonicalOhlcvManifestSemanticReplayV4Error(reason) from exc


def _exact_json_array_element_spans(payload: bytes) -> tuple[tuple[int, int], ...]:
    try:
        text = payload.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        _fail("canonical_ohlcv_manifest_replay_full_payload_span_invalid")
    decoder = json.JSONDecoder()
    length = len(text)

    def skip_whitespace(position: int) -> int:
        while position < length and text[position] in " \t\r\n":
            position += 1
        return position

    index = skip_whitespace(0)
    if index >= length or text[index] != "[":
        _fail("canonical_ohlcv_manifest_replay_full_payload_span_invalid")
    index = skip_whitespace(index + 1)
    spans: list[tuple[int, int]] = []
    if index < length and text[index] == "]":
        _fail("canonical_ohlcv_manifest_replay_full_payload_span_invalid")
    while index < length:
        if len(spans) >= MAX_OHLCV_CLOSED_ROWS:
            _fail("canonical_ohlcv_manifest_replay_full_payload_span_invalid")
        start = index
        try:
            _, end = decoder.raw_decode(text, index)
        except (json.JSONDecodeError, RecursionError):
            _fail("canonical_ohlcv_manifest_replay_full_payload_span_invalid")
        if end <= start:
            _fail("canonical_ohlcv_manifest_replay_full_payload_span_invalid")
        spans.append((start, end))
        index = skip_whitespace(end)
        if index >= length:
            _fail("canonical_ohlcv_manifest_replay_full_payload_span_invalid")
        if text[index] == "]":
            index = skip_whitespace(index + 1)
            if index != length:
                _fail("canonical_ohlcv_manifest_replay_full_payload_span_invalid")
            break
        if text[index] != ",":
            _fail("canonical_ohlcv_manifest_replay_full_payload_span_invalid")
        index = skip_whitespace(index + 1)
    if not spans:
        _fail("canonical_ohlcv_manifest_replay_full_payload_span_invalid")
    return tuple(spans)


def _validate_atomic_material(
    manifest: dict[str, object],
    *,
    source_key: str,
    source_key_sha256: str,
    full_address: SourcePayloadAddress,
) -> None:
    reason = "canonical_ohlcv_manifest_replay_atomic_material_invalid"
    seconds = _exact_int(manifest["atomic_server_time_seconds"], minimum=0, reason=reason)
    microseconds = _exact_int(
        manifest["atomic_server_time_microseconds"],
        minimum=0,
        maximum=999_999,
        reason=reason,
    )
    try:
        server_datetime = _EPOCH + timedelta(
            seconds=seconds,
            microseconds=microseconds,
        )
    except (OverflowError, ValueError):
        _fail(reason)
    server_observed_at = server_datetime.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if _exact_str(manifest["atomic_server_observed_at"], reason=reason) != (server_observed_at):
        _fail(reason)
    pttl_ms = _exact_int(manifest["source_pttl_ms"], minimum=-1, reason=reason)
    material = _parse_nested_canonical_object(
        manifest["atomic_batch_material_json"],
        fields=_ATOMIC_FIELDS,
        reason=reason,
    )
    results = _exact_list(material["results"], reason=reason)
    if len(results) != 1:
        _fail(reason)
    result = _exact_dict(results[0], fields=_ATOMIC_RESULT_FIELDS, reason=reason)
    expected_result: dict[str, object] = {
        "consumer_eligible": False,
        "ledger_receipt_emitted": False,
        "live_execution_authorized": False,
        "paper_provenance_only": True,
        "payload_byte_count": full_address.payload_byte_count,
        "payload_sha256": full_address.payload_sha256,
        "present": True,
        "pttl_ms": pttl_ms,
        "read_only": True,
        "redis_type": "string",
        "schema_version": ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION,
        "server_time_clock_semantics": REDIS_TIME_CLOCK_SEMANTICS,
        "server_time_is_consumer_observed_at": False,
        "source_finality_attested": False,
        "source_key": source_key,
        "source_key_sha256": source_key_sha256,
        "source_schema_attested": False,
        "transport_authenticity_attested": False,
    }
    if result != expected_result:
        _fail(reason)
    expected_material: dict[str, object] = {
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
        "results": [expected_result],
        "schema_version": ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION,
        "server_observed_at": server_observed_at,
        "server_time_clock_semantics": REDIS_TIME_CLOCK_SEMANTICS,
        "server_time_is_consumer_observed_at": False,
        "server_time_microseconds": microseconds,
        "server_time_seconds": seconds,
        "source_finality_attested": False,
        "source_schema_attested": False,
        "total_payload_byte_count": full_address.payload_byte_count,
        "transport_authenticity_attested": False,
    }
    expected_json = _canonical_json_bytes(expected_material, reason=reason).decode("ascii")
    material_json = _exact_str(manifest["atomic_batch_material_json"], reason=reason)
    material_sha256 = hashlib.sha256(expected_json.encode("ascii")).hexdigest()
    expected_batch_id = f"trainer_atomic_redis_source_read_v2_{material_sha256}"
    if (
        material != expected_material
        or material_json != expected_json
        or _required_sha256(manifest["atomic_batch_material_sha256"], reason=reason)
        != material_sha256
        or _exact_str(manifest["atomic_batch_id"], reason=reason) != expected_batch_id
        or _exact_str(manifest["source_key_version"], reason=reason) != expected_batch_id
    ):
        _fail(reason)


def _identity_projection(window: ValidatedOHLCVClosedWindow) -> list[dict[str, object]]:
    return [
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


def _bind_suffix(
    window: ValidatedOHLCVClosedWindow,
    *,
    symbol: str,
    timeframe: str,
    observed_at_ms: int,
    reason: str,
) -> FullContiguousCoreInputBinding:
    try:
        return bind_full_contiguous_core_ta_input(
            _identity_projection(window),
            expected_symbol=symbol,
            timeframe=timeframe,
            consumer_observed_at_ms=observed_at_ms,
            expected_latest_finalized_close_time=_expected_latest_close(
                observed_at_ms=observed_at_ms,
                timeframe=timeframe,
            ),
        )
    except FeatureWindowContractError as exc:
        raise CanonicalOhlcvManifestSemanticReplayV4Error(reason) from exc


def _row_metadata_matches(
    row: dict[str, object],
    source: ValidatedClosedCandle,
    *,
    ordinal: int,
    source_index: int,
    span: tuple[int, int],
) -> bool:
    start, end = span
    exact_pairs: tuple[tuple[object, object], ...] = (
        (row["selected_ordinal"], ordinal),
        (row["source_index"], source_index),
        (row["byte_start"], start),
        (row["byte_end_exclusive"], end),
        (row["exact_payload_byte_count"], end - start),
        (row["candle_id"], source.candle_id),
        (row["candle_open_time_ms"], source.candle_open_time),
        (row["candle_close_time_ms"], source.candle_close_time),
        (row["producer_event_time_ms"], source.event_time),
        (row["ingested_at_ms"], source.ingested_at),
        (row["available_at_ms"], source.available_at),
        (row["source"], source.source),
        (row["source_sequence_id"], source.source_sequence_id),
        (row["raw_payload_hash"], source.raw_payload_hash),
        (row["is_backfilled"], source.is_backfilled),
    )
    return all(
        type(actual) is type(expected) and actual == expected for actual, expected in exact_pairs
    )


def _validate_receipt(
    row: dict[str, object],
    *,
    source: ValidatedClosedCandle,
    source_key: str,
    source_key_version: str,
    consumer_observed_at: str,
    decision_datetime: datetime,
) -> tuple[str, dict[str, object]]:
    reason = "canonical_ohlcv_manifest_replay_source_read_receipt_invalid"
    receipt_input = row["source_read_receipt_v4"]
    if type(receipt_input) is not dict:
        _fail(reason)
    try:
        artifact = validate_source_read_receipt_v4(receipt_input)
        receipt = cast(dict[str, object], artifact.receipt)
    except SourceReadReceiptV4Error as exc:
        raise CanonicalOhlcvManifestSemanticReplayV4Error(reason) from exc
    row_digest = _required_sha256(row["exact_payload_sha256"], reason=reason)
    row_count = _exact_int(row["exact_payload_byte_count"], minimum=1, reason=reason)
    start = _exact_int(row["byte_start"], minimum=0, reason=reason)
    end = _exact_int(row["byte_end_exclusive"], minimum=1, reason=reason)
    close_clock = _ms_to_clock(source.candle_close_time, reason=reason)
    producer_clock = _ms_to_clock(source.event_time, reason=reason)
    ingested_clock = _ms_to_clock(source.ingested_at, reason=reason)
    available_clock = _ms_to_clock(source.available_at, reason=reason)
    expected_label = f"ohlcv_closed:binance:{source.symbol}:{source.timeframe}:{source.candle_id}"
    expected_locator = f"{source_key}@bytes:{start}-{end}"
    if type(receipt["read_evidence"]) is not dict or type(receipt["finality_evidence"]) is not dict:
        _fail(reason)
    read_evidence = cast(dict[str, object], receipt["read_evidence"])
    finality = cast(dict[str, object], receipt["finality_evidence"])
    expected_root_values: dict[str, object] = {
        "schema_version": SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION,
        "source_label": expected_label,
        "payload_type": CANONICAL_OHLCV_ROW_PAYLOAD_TYPE,
        "payload_sha256": row_digest,
        "payload_byte_count": row_count,
        "economic_event_time": close_clock,
        "producer_event_time": producer_clock,
        "ingested_at": ingested_clock,
        "available_at": available_clock,
        "consumer_observed_at": consumer_observed_at,
        "feature_cutoff": close_clock,
    }
    if any(receipt.get(name) != value for name, value in expected_root_values.items()):
        _fail(reason)
    if (
        read_evidence.get("read_locator_type") != "REDIS_VERSIONED_VALUE"
        or read_evidence.get("read_locator") != expected_locator
        or read_evidence.get("read_locator_version") != source_key_version
        or read_evidence.get("read_completed_at") != consumer_observed_at
        or finality.get("finality_type") != SOURCE_READ_RECEIPT_V4_FINALITY_TYPE
        or finality.get("event_final") is not True
        or finality.get("finality_cutoff") != close_clock
        or finality.get("finality_verified_at") != available_clock
        or finality.get("verifier") != CANONICAL_OHLCV_FINALITY_VERIFIER
    ):
        _fail(reason)
    for clock_name in (
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
        "consumer_observed_at",
        "feature_cutoff",
    ):
        _, clock, _ = _parse_clock(receipt[clock_name], reason=reason)
        if clock > decision_datetime:
            _fail(reason)
    return artifact.receipt_sha256, receipt


def _validate_manifest_summary(
    manifest: dict[str, object],
    *,
    window: ValidatedOHLCVClosedWindow,
    binding: FullContiguousCoreInputBinding,
) -> None:
    reason = "canonical_ohlcv_manifest_replay_suffix_summary_invalid"
    gap_pairs = tuple(zip(window.gap_indices, window.gap_missing_interval_counts, strict=True))
    excluded_pairs = tuple(
        pair for pair in gap_pairs if pair[0] <= binding.selected_source_start_index
    )
    internal_gaps = tuple(
        gap
        for gap in window.gap_indices
        if binding.selected_source_start_index < gap < binding.selected_source_end_index_exclusive
    )
    exact_values: tuple[tuple[object, object], ...] = (
        (manifest["raw_row_count"], window.row_count),
        (manifest["source_gap_indices"], list(window.gap_indices)),
        (
            manifest["source_gap_missing_interval_counts"],
            list(window.gap_missing_interval_counts),
        ),
        (manifest["selected_source_start_index"], binding.selected_source_start_index),
        (
            manifest["selected_source_end_index_exclusive"],
            binding.selected_source_end_index_exclusive,
        ),
        (manifest["selected_row_count"], binding.selected_row_count),
        (manifest["excluded_prefix_row_count"], binding.selected_source_start_index),
        (manifest["excluded_prefix_gap_indices"], [pair[0] for pair in excluded_pairs]),
        (
            manifest["excluded_prefix_gap_missing_interval_counts"],
            [pair[1] for pair in excluded_pairs],
        ),
        (manifest["selected_internal_gap_indices"], list(internal_gaps)),
        (manifest["tail_missing_interval_count"], 0),
        (manifest["latest_candle_matches_expected_cutoff"], True),
        (manifest["binding_selection_sha256"], binding.selection_sha256),
        (
            manifest["selected_candle_id_chain_sha256"],
            binding.selected_candle_id_chain_sha256,
        ),
    )
    if any(
        type(actual) is not type(expected) or actual != expected
        for actual, expected in exact_values
    ):
        _fail(reason)


def replay_canonical_ohlcv_manifest_semantics_v4(
    *,
    cas_root: str,
    manifest_address: SourcePayloadAddress,
    expected_symbol: str,
    expected_timeframe: str,
    decision_time: str,
) -> Mapping[str, object]:
    """Freshly replay one manifest and return detached audit-only scalar evidence."""

    if type(cas_root) is not str:
        _fail("canonical_ohlcv_manifest_replay_cas_root_invalid")
    (
        detached_manifest_address,
        manifest_payload_sha256,
        manifest_payload_byte_count,
    ) = _snapshot_manifest_address(manifest_address)
    if (
        type(expected_symbol) is not str
        or not expected_symbol.isascii()
        or _SYMBOL_RE.fullmatch(expected_symbol) is None
    ):
        _fail("canonical_ohlcv_manifest_replay_symbol_invalid")
    if (
        type(expected_timeframe) is not str
        or expected_timeframe not in SUPPORTED_TRAINER_TIMEFRAMES
    ):
        _fail("canonical_ohlcv_manifest_replay_timeframe_invalid")
    decision_text, decision_datetime, decision_ms = _parse_clock(
        decision_time,
        reason="canonical_ohlcv_manifest_replay_decision_context_invalid",
    )
    try:
        reader = ImmutableSourcePayloadReaderV4(cas_root)
    except ImmutableSourcePayloadReaderV4Error as exc:
        raise CanonicalOhlcvManifestSemanticReplayV4Error(
            "canonical_ohlcv_manifest_replay_cas_root_invalid"
        ) from exc

    manifest_bytes = _read_cas(
        reader,
        detached_manifest_address,
        reason="canonical_ohlcv_manifest_replay_manifest_cas_read_failed",
    )
    manifest = _parse_exact_canonical_object(
        manifest_bytes,
        fields=_MANIFEST_FIELDS,
        reason="canonical_ohlcv_manifest_replay_manifest_json_invalid",
    )
    if (
        manifest["schema_version"] != CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION
        or manifest["evidence_classification"]
        != CANONICAL_OHLCV_ATOMIC_CAPTURE_EVIDENCE_CLASSIFICATION
        or manifest["downstream_status"] != CANONICAL_OHLCV_ATOMIC_CAPTURE_DOWNSTREAM_STATUS
        or any(manifest[name] is not False for name in _MANIFEST_FALSE_FIELDS)
    ):
        _fail("canonical_ohlcv_manifest_replay_manifest_contract_invalid")

    source_key = f"v2:market:ohlcv_closed:binance:{expected_symbol}:{expected_timeframe}"
    source_key_sha256 = hashlib.sha256(source_key.encode("ascii")).hexdigest()
    if manifest["source_key"] != source_key or manifest["source_key_sha256"] != source_key_sha256:
        _fail("canonical_ohlcv_manifest_replay_source_identity_invalid")
    consumer_text, consumer_datetime, consumer_ms = _parse_clock(
        manifest["consumer_observed_at"],
        reason="canonical_ohlcv_manifest_replay_consumer_clock_invalid",
    )
    if (
        _exact_int(
            manifest["consumer_observed_at_ms"],
            minimum=1,
            reason="canonical_ohlcv_manifest_replay_consumer_clock_invalid",
        )
        != consumer_ms
        or consumer_datetime > decision_datetime
    ):
        _fail("canonical_ohlcv_manifest_replay_consumer_clock_invalid")

    full_address = _address_from_material(
        manifest["full_source_payload_cas_address"],
        maximum_byte_count=MAX_OHLCV_CLOSED_PAYLOAD_BYTES,
        reason="canonical_ohlcv_manifest_replay_full_payload_address_invalid",
    )
    _validate_atomic_material(
        manifest,
        source_key=source_key,
        source_key_sha256=source_key_sha256,
        full_address=full_address,
    )
    full_payload = _read_cas(
        reader,
        full_address,
        reason="canonical_ohlcv_manifest_replay_full_payload_cas_read_failed",
    )
    try:
        window = validate_ohlcv_closed_window(
            full_payload,
            symbol=expected_symbol,
            timeframe=expected_timeframe,
        )
    except OHLCVClosedWindowValidationError as exc:
        raise CanonicalOhlcvManifestSemanticReplayV4Error(
            "canonical_ohlcv_manifest_replay_full_payload_schema_invalid"
        ) from exc
    if (
        window.source_key != source_key
        or window.exact_payload_sha256 != full_address.payload_sha256
        or window.exact_payload_byte_count != full_address.payload_byte_count
    ):
        _fail("canonical_ohlcv_manifest_replay_full_payload_binding_invalid")
    spans = _exact_json_array_element_spans(full_payload)
    if len(spans) != window.row_count:
        _fail("canonical_ohlcv_manifest_replay_full_payload_span_invalid")

    capture_binding = _bind_suffix(
        window,
        symbol=expected_symbol,
        timeframe=expected_timeframe,
        observed_at_ms=consumer_ms,
        reason="canonical_ohlcv_manifest_replay_capture_suffix_invalid",
    )
    decision_binding = _bind_suffix(
        window,
        symbol=expected_symbol,
        timeframe=expected_timeframe,
        observed_at_ms=decision_ms,
        reason="canonical_ohlcv_manifest_replay_decision_suffix_stale_or_invalid",
    )
    if (
        decision_binding.selected_source_start_index != capture_binding.selected_source_start_index
        or decision_binding.selected_source_end_index_exclusive
        != capture_binding.selected_source_end_index_exclusive
        or decision_binding.selected_candle_ids != capture_binding.selected_candle_ids
    ):
        _fail("canonical_ohlcv_manifest_replay_decision_suffix_stale_or_invalid")
    _validate_manifest_summary(manifest, window=window, binding=capture_binding)

    selected_values = _exact_list(
        manifest["selected_rows"],
        reason="canonical_ohlcv_manifest_replay_selected_rows_invalid",
    )
    if len(selected_values) != capture_binding.selected_row_count:
        _fail("canonical_ohlcv_manifest_replay_selected_rows_invalid")
    suffix_rows: list[dict[str, object]] = []
    receipt_sha256s: list[str] = []
    source_key_version = _exact_str(
        manifest["source_key_version"],
        reason="canonical_ohlcv_manifest_replay_atomic_material_invalid",
    )
    for ordinal, raw_selected in enumerate(selected_values):
        selected = _exact_dict(
            raw_selected,
            fields=_SELECTED_ROW_FIELDS,
            reason="canonical_ohlcv_manifest_replay_selected_row_invalid",
        )
        source_index = capture_binding.selected_source_start_index + ordinal
        source = window.rows[source_index]
        span = spans[source_index]
        start, end = span
        if not _row_metadata_matches(
            selected,
            source,
            ordinal=ordinal,
            source_index=source_index,
            span=span,
        ):
            _fail("canonical_ohlcv_manifest_replay_selected_row_binding_invalid")
        row_address = _address_from_material(
            selected["source_payload_cas_address"],
            maximum_byte_count=end - start,
            expected_byte_count=end - start,
            reason="canonical_ohlcv_manifest_replay_selected_row_address_invalid",
        )
        row_bytes = _read_cas(
            reader,
            row_address,
            reason="canonical_ohlcv_manifest_replay_selected_row_cas_read_failed",
        )
        exact_span = full_payload[start:end]
        exact_digest = hashlib.sha256(exact_span).hexdigest()
        if (
            row_bytes != exact_span
            or row_address.payload_sha256 != exact_digest
            or row_address.payload_byte_count != len(exact_span)
            or selected["exact_payload_sha256"] != exact_digest
            or selected["exact_payload_byte_count"] != len(exact_span)
        ):
            _fail("canonical_ohlcv_manifest_replay_selected_row_exact_span_invalid")
        receipt_sha256, _ = _validate_receipt(
            selected,
            source=source,
            source_key=source_key,
            source_key_version=source_key_version,
            consumer_observed_at=consumer_text,
            decision_datetime=decision_datetime,
        )
        receipt_sha256s.append(receipt_sha256)
        suffix_rows.append(
            {
                "selected_ordinal": ordinal,
                "source_index": source_index,
                "byte_start": start,
                "byte_end_exclusive": end,
                "exact_payload_sha256": exact_digest,
                "exact_payload_byte_count": len(exact_span),
                "candle_id": source.candle_id,
                "candle_open_time_ms": source.candle_open_time,
                "candle_close_time_ms": source.candle_close_time,
                "source_sequence_id": source.source_sequence_id,
                "raw_payload_hash": source.raw_payload_hash,
                "source_read_receipt_sha256": receipt_sha256,
            }
        )

    suffix_reason = "canonical_ohlcv_manifest_replay_suffix_digest_invalid"
    suffix = _parse_nested_canonical_object(
        manifest["suffix_digest_material_json"],
        fields=_SUFFIX_FIELDS,
        reason=suffix_reason,
    )
    suffix_raw_rows = _exact_list(suffix["ordered_selected_rows"], reason=suffix_reason)
    for item in suffix_raw_rows:
        _exact_dict(item, fields=_SUFFIX_ROW_FIELDS, reason=suffix_reason)
    expected_suffix: dict[str, object] = {
        "schema_version": CANONICAL_OHLCV_SUFFIX_DIGEST_SCHEMA_VERSION,
        "source_key": source_key,
        "source_key_version": source_key_version,
        "full_source_payload_sha256": full_address.payload_sha256,
        "full_source_payload_byte_count": full_address.payload_byte_count,
        "binding_selection_sha256": capture_binding.selection_sha256,
        "selected_candle_id_chain_sha256": (capture_binding.selected_candle_id_chain_sha256),
        "selected_source_start_index": capture_binding.selected_source_start_index,
        "selected_source_end_index_exclusive": (
            capture_binding.selected_source_end_index_exclusive
        ),
        "selected_row_count": capture_binding.selected_row_count,
        "ordered_selected_rows": suffix_rows,
    }
    expected_suffix_json = _canonical_json_bytes(expected_suffix, reason=suffix_reason)
    expected_suffix_sha256 = hashlib.sha256(expected_suffix_json).hexdigest()
    if (
        suffix != expected_suffix
        or _exact_str(manifest["suffix_digest_material_json"], reason=suffix_reason)
        != expected_suffix_json.decode("ascii")
        or _required_sha256(manifest["suffix_digest_sha256"], reason=suffix_reason)
        != expected_suffix_sha256
    ):
        _fail(suffix_reason)

    receipt_chain_material = {
        "schema_version": "canonical_ohlcv_source_receipt_chain_v4",
        "source_key": source_key,
        "source_key_version": source_key_version,
        "ordered_source_read_receipt_sha256s": receipt_sha256s,
    }
    receipt_chain_sha256 = hashlib.sha256(
        _canonical_json_bytes(
            receipt_chain_material,
            reason="canonical_ohlcv_manifest_replay_result_invalid",
        )
    ).hexdigest()
    result: dict[str, object] = {
        "schema_version": CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_SCHEMA_VERSION,
        "evidence_classification": (
            CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_EVIDENCE_CLASSIFICATION
        ),
        "downstream_status": (CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_DOWNSTREAM_STATUS),
        "manifest_sha256": manifest_payload_sha256,
        "manifest_byte_count": manifest_payload_byte_count,
        "full_source_payload_sha256": full_address.payload_sha256,
        "full_source_payload_byte_count": full_address.payload_byte_count,
        "source_key": source_key,
        "source_key_version": source_key_version,
        "symbol": expected_symbol,
        "timeframe": expected_timeframe,
        "consumer_observed_at": consumer_text,
        "decision_time": decision_text,
        "feature_cutoff": _ms_to_clock(
            window.latest_economic_close_time,
            reason="canonical_ohlcv_manifest_replay_result_invalid",
        ),
        "generated_at": None,
        "execution_time": None,
        "raw_row_count": window.row_count,
        "selected_row_count": capture_binding.selected_row_count,
        "selected_source_start_index": capture_binding.selected_source_start_index,
        "selected_source_end_index_exclusive": (
            capture_binding.selected_source_end_index_exclusive
        ),
        "binding_selection_sha256": capture_binding.selection_sha256,
        "decision_binding_selection_sha256": decision_binding.selection_sha256,
        "selected_candle_id_chain_sha256": (capture_binding.selected_candle_id_chain_sha256),
        "suffix_digest_sha256": expected_suffix_sha256,
        "source_read_receipt_chain_sha256": receipt_chain_sha256,
        "manifest_cas_reopened": True,
        "full_source_payload_cas_reopened": True,
        "every_selected_row_cas_reopened": True,
        "manifest_exact_canonical_json_verified": True,
        "content_addresses_recomputed": True,
        "exact_row_spans_recomputed": True,
        "committed_ohlcv_30_field_schema_replayed": True,
        "complete_contiguous_suffix_recomputed": True,
        "every_source_read_receipt_revalidated": True,
        "source_clocks_and_finality_recomputed": True,
        "decision_context_bound": True,
        **{name: False for name in _RESULT_FALSE_AUTHORITY_FIELDS},
        "audit_only": True,
    }
    result["semantic_replay_sha256"] = hashlib.sha256(
        _canonical_json_bytes(
            result,
            reason="canonical_ohlcv_manifest_replay_result_invalid",
        )
    ).hexdigest()
    detached = cast(
        dict[str, object],
        json.loads(
            _canonical_json_bytes(
                result,
                reason="canonical_ohlcv_manifest_replay_result_invalid",
            )
        ),
    )
    return MappingProxyType(detached)


__all__ = [
    "CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_DOWNSTREAM_STATUS",
    "CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_EVIDENCE_CLASSIFICATION",
    "CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_SCHEMA_VERSION",
    "CanonicalOhlcvManifestSemanticReplayV4Error",
    "replay_canonical_ohlcv_manifest_semantics_v4",
]
