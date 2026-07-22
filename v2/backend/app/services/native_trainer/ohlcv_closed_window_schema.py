"""Strict schema boundary for exact Binance closed-OHLCV Redis bytes.

The validator in this module is deliberately unwired.  It validates the
current 30-field canonical-candle JSON ABI stored at
``v2:market:ohlcv_closed:binance:{SYMBOL}:{TIMEFRAME}``, without decoding and
re-serializing the bytes used for the payload digest.  A successful result is
only a frozen, Python-constructible schema value.  It is not a Redis read
receipt, immutable CAS capture, authenticity proof, trainer admission, or
consumer-eligibility grant.

For a WSS row, the canonical field named ``event_time`` retains Binance's
producer message timestamp.  The economic candle event is
``candle_close_time``.  They are intentionally exposed separately here so a
later receipt adapter cannot silently substitute producer time for economic
event time.

Gaps are reported rather than silently discarded.  ``gap_indices`` are
zero-based indices of rows immediately following a missing interval.
``required_contiguous_lookback`` is caller/feature-derived; it is never a
market-selection threshold.  A caller that needs a lookback must provide it
to :func:`validate_ohlcv_closed_window` or call
:func:`require_contiguous_window`, both of which fail closed when the validated
contiguous suffix is too short.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Final, NoReturn, cast

OHLCV_CLOSED_WINDOW_SCHEMA_VERSION = "trainer_ohlcv_closed_window_v1"
# Byte/row/string limits below are parser resource and fixed source-ABI
# invariants.  They do not select markets or impose trading/feature cutoffs.
MAX_OHLCV_CLOSED_PAYLOAD_BYTES = 1024 * 1024
MAX_OHLCV_CLOSED_ROWS = 1500
SUPPORTED_TRAINER_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
TIMEFRAME_DURATION_MS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "1m": 60_000,
        "5m": 300_000,
        "15m": 900_000,
        "1h": 3_600_000,
        "4h": 14_400_000,
    }
)

_MAX_SIGNED_64 = (1 << 63) - 1
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$")
_LOWER_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CANDLE_ID_RE = re.compile(r"^[0-9a-f]{24}$")

_OHLCV_KEYS = frozenset(
    {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "num_trades",
        "taker_buy_base_vol",
        "taker_buy_quote_vol",
    }
)
_LEGACY_ROW_KEYS = frozenset(
    {
        "symbol",
        "exchange",
        "timeframe",
        "candle_open_time",
        "candle_close_time",
        "event_time",
        "ingested_at",
        "available_at",
        "is_closed",
        "source",
        "source_sequence_id",
        "raw_payload_hash",
        "ohlcv",
        "is_backfilled",
        "feature_eligible",
        "candle_id",
        "open_time",
        "close_time",
        "ts",
        "closed_candle",
        "candle_closed_confirmed",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "num_trades",
        "taker_buy_base_vol",
        "taker_buy_quote_vol",
    }
)
_ROW_KEYS = _LEGACY_ROW_KEYS | frozenset({"venue", "product_type"})

ExactNumber = int | float


class OHLCVClosedWindowValidationError(ValueError):
    """Exact payload or requested-window evidence violates the closed ABI."""


class _DuplicateJSONObjectKey(ValueError):
    """Internal marker used to totalize duplicate JSON object keys."""


@dataclass(frozen=True, slots=True)
class ValidatedOHLCV:
    """Immutable nine-field nested OHLCV value."""

    open: ExactNumber
    high: ExactNumber
    low: ExactNumber
    close: ExactNumber
    volume: ExactNumber
    quote_volume: ExactNumber
    num_trades: int
    taker_buy_base_vol: ExactNumber
    taker_buy_quote_vol: ExactNumber


@dataclass(frozen=True, slots=True)
class ValidatedClosedCandle:
    """Immutable projection of one exact current 30-field canonical row."""

    symbol: str
    exchange: str
    timeframe: str
    candle_open_time: int
    candle_close_time: int
    event_time: int
    ingested_at: int
    available_at: int
    is_closed: bool
    source: str
    source_sequence_id: str
    raw_payload_hash: str
    ohlcv: ValidatedOHLCV
    is_backfilled: bool
    feature_eligible: bool
    candle_id: str
    open_time: int
    close_time: int
    ts: int
    closed_candle: bool
    candle_closed_confirmed: bool
    open: ExactNumber
    high: ExactNumber
    low: ExactNumber
    close: ExactNumber
    volume: ExactNumber
    quote_volume: ExactNumber
    num_trades: int
    taker_buy_base_vol: ExactNumber
    taker_buy_quote_vol: ExactNumber


@dataclass(frozen=True, slots=True)
class ValidatedOHLCVClosedWindow:
    """Frozen source-schema result; explicitly nonconsumable until later gates."""

    schema_version: str
    source_key: str
    symbol: str
    exchange: str
    timeframe: str
    exact_payload_sha256: str
    exact_payload_byte_count: int
    row_count: int
    rows: tuple[ValidatedClosedCandle, ...]
    first_economic_close_time: int
    latest_economic_close_time: int
    latest_producer_event_time: int
    max_ingested_at: int
    max_available_at: int
    binance_wss_row_count: int
    binance_rest_row_count: int
    gap_count: int
    gap_indices: tuple[int, ...]
    gap_missing_interval_counts: tuple[int, ...]
    missing_interval_count: int
    contiguous_suffix_count: int
    required_contiguous_lookback: int | None
    required_contiguous_window_satisfied: bool | None
    exact_source_schema_validated: bool = field(default=True, init=False)
    producer_finality_contract_validated: bool = field(default=True, init=False)
    redis_read_receipt_emitted: bool = field(default=False, init=False)
    immutable_cas_captured: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)


def _invalid(reason: str) -> NoReturn:
    raise OHLCVClosedWindowValidationError(reason) from None


def _duplicate_object_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise _DuplicateJSONObjectKey(key)
        output[key] = value
    return output


def _reject_json_constant(_value: str) -> NoReturn:
    _invalid("ohlcv_closed_json_nonfinite_constant")


def _parse_json_int(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > 19:
        _invalid("ohlcv_closed_json_integer_out_of_range")
    parsed = int(value)
    if not -_MAX_SIGNED_64 - 1 <= parsed <= _MAX_SIGNED_64:
        _invalid("ohlcv_closed_json_integer_out_of_range")
    return parsed


def _parse_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        _invalid("ohlcv_closed_json_number_nonfinite")
    return parsed


def _decode_exact_json(exact_payload_bytes: object) -> tuple[bytes, list[object]]:
    if type(exact_payload_bytes) is not bytes:
        _invalid("ohlcv_closed_payload_requires_exact_bytes")
    payload = exact_payload_bytes
    if not 1 <= len(payload) <= MAX_OHLCV_CLOSED_PAYLOAD_BYTES:
        _invalid("ohlcv_closed_payload_byte_count_invalid")
    if payload.startswith(b"\xef\xbb\xbf"):
        _invalid("ohlcv_closed_payload_utf8_bom_forbidden")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _invalid("ohlcv_closed_payload_utf8_invalid")
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_duplicate_object_hook,
            parse_constant=_reject_json_constant,
            parse_int=_parse_json_int,
            parse_float=_parse_json_float,
        )
    except OHLCVClosedWindowValidationError:
        raise
    except _DuplicateJSONObjectKey:
        _invalid("ohlcv_closed_json_duplicate_object_key")
    except (json.JSONDecodeError, TypeError, ValueError, OverflowError, RecursionError):
        _invalid("ohlcv_closed_json_invalid")
    if type(decoded) is not list:
        _invalid("ohlcv_closed_top_level_requires_exact_list")
    rows = cast(list[object], decoded)
    if not 1 <= len(rows) <= MAX_OHLCV_CLOSED_ROWS:
        _invalid("ohlcv_closed_row_count_invalid")
    return payload, rows


def _validated_symbol(symbol: object) -> str:
    if type(symbol) is not str:
        _invalid("ohlcv_closed_symbol_invalid")
    value = symbol
    if not value.isascii() or _SYMBOL_RE.fullmatch(value) is None:
        _invalid("ohlcv_closed_symbol_invalid")
    return value


def _validated_timeframe(timeframe: object) -> str:
    if type(timeframe) is not str or timeframe not in SUPPORTED_TRAINER_TIMEFRAMES:
        _invalid("ohlcv_closed_timeframe_invalid")
    return timeframe


def _validated_required_lookback(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        _invalid("ohlcv_closed_required_lookback_invalid")
    if not 1 <= value <= _MAX_SIGNED_64:
        _invalid("ohlcv_closed_required_lookback_invalid")
    return value


def _exact_string(row: dict[str, object], key: str) -> str:
    value = row[key]
    if type(value) is not str:
        _invalid(f"ohlcv_closed_{key}_type_invalid")
    return value


def _exact_bool(row: dict[str, object], key: str) -> bool:
    value = row[key]
    if type(value) is not bool:
        _invalid(f"ohlcv_closed_{key}_type_invalid")
    return value


def _nonnegative_int(row: dict[str, object], key: str) -> int:
    value = row[key]
    if type(value) is not int or not 0 <= value <= _MAX_SIGNED_64:
        _invalid(f"ohlcv_closed_{key}_invalid")
    return value


def _finite_number(
    row: dict[str, object],
    key: str,
    *,
    positive: bool,
) -> ExactNumber:
    value = row[key]
    if type(value) is not int and type(value) is not float:
        _invalid(f"ohlcv_closed_{key}_numeric_invalid")
    number = cast(ExactNumber, value)
    if type(number) is int and not -_MAX_SIGNED_64 - 1 <= number <= _MAX_SIGNED_64:
        _invalid(f"ohlcv_closed_{key}_numeric_invalid")
    if type(number) is float and not math.isfinite(number):
        _invalid(f"ohlcv_closed_{key}_numeric_invalid")
    if positive:
        if number <= 0:
            _invalid(f"ohlcv_closed_{key}_must_be_positive")
    elif number < 0:
        _invalid(f"ohlcv_closed_{key}_must_be_nonnegative")
    return number


def _canonical_candle_id(
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    candle_open_time: int,
    candle_close_time: int,
    raw_payload_hash: str,
) -> str:
    # This intentionally preserves canonical_candles.stable_hash's current
    # json.dumps defaults (including separators) as part of the 24-char ABI.
    material = {
        "exchange": exchange,
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_open_time": candle_open_time,
        "candle_close_time": candle_close_time,
        "raw_payload_hash": raw_payload_hash,
    }
    encoded = json.dumps(material, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _validate_nested_ohlcv(row: dict[str, object]) -> ValidatedOHLCV:
    raw_nested = row["ohlcv"]
    if type(raw_nested) is not dict:
        _invalid("ohlcv_closed_ohlcv_requires_exact_dict")
    nested = cast(dict[str, object], raw_nested)
    if frozenset(nested) != _OHLCV_KEYS:
        _invalid("ohlcv_closed_ohlcv_field_set_invalid")

    open_price = _finite_number(nested, "open", positive=True)
    high = _finite_number(nested, "high", positive=True)
    low = _finite_number(nested, "low", positive=True)
    close = _finite_number(nested, "close", positive=True)
    volume = _finite_number(nested, "volume", positive=False)
    quote_volume = _finite_number(nested, "quote_volume", positive=False)
    num_trades = _nonnegative_int(nested, "num_trades")
    taker_buy_base_vol = _finite_number(nested, "taker_buy_base_vol", positive=False)
    taker_buy_quote_vol = _finite_number(nested, "taker_buy_quote_vol", positive=False)

    if high < max(open_price, close) or low > min(open_price, close) or low > high:
        _invalid("ohlcv_closed_ohlc_invariant_invalid")
    return ValidatedOHLCV(
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        quote_volume=quote_volume,
        num_trades=num_trades,
        taker_buy_base_vol=taker_buy_base_vol,
        taker_buy_quote_vol=taker_buy_quote_vol,
    )


def _same_exact_number(top: ExactNumber, nested: ExactNumber) -> bool:
    return type(top) is type(nested) and top == nested


def _validate_row(
    raw_row: object,
    *,
    expected_symbol: str,
    expected_timeframe: str,
    duration_ms: int,
) -> ValidatedClosedCandle:
    if type(raw_row) is not dict:
        _invalid("ohlcv_closed_row_requires_exact_dict")
    row = cast(dict[str, object], raw_row)
    row_keys = frozenset(row)
    if row_keys not in {_LEGACY_ROW_KEYS, _ROW_KEYS}:
        _invalid("ohlcv_closed_row_field_set_invalid")

    symbol = _exact_string(row, "symbol")
    exchange = _exact_string(row, "exchange")
    timeframe = _exact_string(row, "timeframe")
    if symbol != expected_symbol or exchange != "binance" or timeframe != expected_timeframe:
        _invalid("ohlcv_closed_source_binding_invalid")
    # ``venue`` and ``product_type`` were added to the canonical producer in
    # July 2026.  Existing immutable Redis windows can contain the preceding
    # exact ABI until their bounded history rolls forward, so accept that one
    # complete legacy field set during migration.  Any present product binding
    # must be complete and exactly Binance USD-M; partial or alternate product
    # claims fail closed.
    if row_keys == _ROW_KEYS and (
        _exact_string(row, "venue") != "binance_usdm"
        or _exact_string(row, "product_type") != "USD-M"
    ):
        _invalid("ohlcv_closed_product_binding_invalid")

    candle_open_time = _nonnegative_int(row, "candle_open_time")
    candle_close_time = _nonnegative_int(row, "candle_close_time")
    event_time = _nonnegative_int(row, "event_time")
    ingested_at = _nonnegative_int(row, "ingested_at")
    available_at = _nonnegative_int(row, "available_at")
    if candle_open_time % duration_ms != 0:
        _invalid("ohlcv_closed_candle_open_alignment_invalid")
    if candle_close_time != candle_open_time + duration_ms - 1:
        _invalid("ohlcv_closed_candle_close_alignment_invalid")

    open_time = _nonnegative_int(row, "open_time")
    close_time = _nonnegative_int(row, "close_time")
    ts = _nonnegative_int(row, "ts")
    if open_time != candle_open_time or ts != candle_open_time or close_time != candle_close_time:
        _invalid("ohlcv_closed_time_alias_invalid")

    is_closed = _exact_bool(row, "is_closed")
    closed_candle = _exact_bool(row, "closed_candle")
    candle_closed_confirmed = _exact_bool(row, "candle_closed_confirmed")
    feature_eligible = _exact_bool(row, "feature_eligible")
    if not (is_closed and closed_candle and candle_closed_confirmed and feature_eligible):
        _invalid("ohlcv_closed_finality_flags_invalid")

    source = _exact_string(row, "source")
    source_sequence_id = _exact_string(row, "source_sequence_id")
    is_backfilled = _exact_bool(row, "is_backfilled")
    if source == "binance_wss":
        if is_backfilled or not (
            candle_close_time <= event_time <= ingested_at <= available_at
            and available_at == max(candle_close_time, event_time, ingested_at)
            and source_sequence_id == str(event_time)
        ):
            _invalid("ohlcv_closed_wss_source_contract_invalid")
    elif source == "binance_rest":
        if not (
            is_backfilled
            and event_time == candle_close_time
            and candle_close_time <= ingested_at == available_at
            and source_sequence_id == str(candle_close_time)
        ):
            _invalid("ohlcv_closed_rest_source_contract_invalid")
    else:
        _invalid("ohlcv_closed_source_invalid")

    raw_payload_hash = _exact_string(row, "raw_payload_hash")
    if _LOWER_SHA256_RE.fullmatch(raw_payload_hash) is None:
        _invalid("ohlcv_closed_raw_payload_hash_invalid")
    candle_id = _exact_string(row, "candle_id")
    if _CANDLE_ID_RE.fullmatch(candle_id) is None:
        _invalid("ohlcv_closed_candle_id_invalid")
    expected_candle_id = _canonical_candle_id(
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        candle_open_time=candle_open_time,
        candle_close_time=candle_close_time,
        raw_payload_hash=raw_payload_hash,
    )
    if candle_id != expected_candle_id:
        _invalid("ohlcv_closed_candle_id_mismatch")

    nested = _validate_nested_ohlcv(row)
    open_price = _finite_number(row, "open", positive=True)
    high = _finite_number(row, "high", positive=True)
    low = _finite_number(row, "low", positive=True)
    close = _finite_number(row, "close", positive=True)
    volume = _finite_number(row, "volume", positive=False)
    quote_volume = _finite_number(row, "quote_volume", positive=False)
    num_trades = _nonnegative_int(row, "num_trades")
    taker_buy_base_vol = _finite_number(row, "taker_buy_base_vol", positive=False)
    taker_buy_quote_vol = _finite_number(row, "taker_buy_quote_vol", positive=False)
    exact_pairs = (
        (open_price, nested.open),
        (high, nested.high),
        (low, nested.low),
        (close, nested.close),
        (volume, nested.volume),
        (quote_volume, nested.quote_volume),
        (taker_buy_base_vol, nested.taker_buy_base_vol),
        (taker_buy_quote_vol, nested.taker_buy_quote_vol),
    )
    if any(not _same_exact_number(top, inside) for top, inside in exact_pairs):
        _invalid("ohlcv_closed_nested_top_level_mismatch")
    if num_trades != nested.num_trades:
        _invalid("ohlcv_closed_nested_top_level_mismatch")
    if taker_buy_base_vol > volume:
        _invalid("ohlcv_closed_taker_buy_base_exceeds_volume")
    if taker_buy_quote_vol > quote_volume:
        _invalid("ohlcv_closed_taker_buy_quote_exceeds_quote_volume")

    # Repeat the invariant over the top-level fields so this contract remains
    # explicit even if the nested ABI changes in a future schema version.
    if high < max(open_price, close) or low > min(open_price, close) or low > high:
        _invalid("ohlcv_closed_ohlc_invariant_invalid")

    return ValidatedClosedCandle(
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        candle_open_time=candle_open_time,
        candle_close_time=candle_close_time,
        event_time=event_time,
        ingested_at=ingested_at,
        available_at=available_at,
        is_closed=is_closed,
        source=source,
        source_sequence_id=source_sequence_id,
        raw_payload_hash=raw_payload_hash,
        ohlcv=nested,
        is_backfilled=is_backfilled,
        feature_eligible=feature_eligible,
        candle_id=candle_id,
        open_time=open_time,
        close_time=close_time,
        ts=ts,
        closed_candle=closed_candle,
        candle_closed_confirmed=candle_closed_confirmed,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        quote_volume=quote_volume,
        num_trades=num_trades,
        taker_buy_base_vol=taker_buy_base_vol,
        taker_buy_quote_vol=taker_buy_quote_vol,
    )


def validate_ohlcv_closed_window(
    exact_payload_bytes: object,
    *,
    symbol: object,
    timeframe: object,
    required_contiguous_lookback: object = None,
) -> ValidatedOHLCVClosedWindow:
    """Validate exact bytes and return a frozen, explicitly nonconsumable value."""

    expected_symbol = _validated_symbol(symbol)
    expected_timeframe = _validated_timeframe(timeframe)
    required_lookback = _validated_required_lookback(required_contiguous_lookback)
    payload, raw_rows = _decode_exact_json(exact_payload_bytes)
    duration_ms = TIMEFRAME_DURATION_MS[expected_timeframe]

    rows: list[ValidatedClosedCandle] = []
    seen_candle_ids: set[str] = set()
    seen_raw_hashes: set[str] = set()
    seen_source_sequences: set[str] = set()
    gap_indices: list[int] = []
    gap_missing_counts: list[int] = []
    previous_open: int | None = None
    for index, raw_row in enumerate(raw_rows):
        row = _validate_row(
            raw_row,
            expected_symbol=expected_symbol,
            expected_timeframe=expected_timeframe,
            duration_ms=duration_ms,
        )
        if previous_open is not None:
            if row.candle_open_time <= previous_open:
                _invalid("ohlcv_closed_rows_not_strictly_increasing")
            interval_distance = row.candle_open_time - previous_open
            if interval_distance != duration_ms:
                # Every row open is already timeframe-aligned, so this is an
                # exact positive multiple and cannot hide a partial interval.
                gap_indices.append(index)
                gap_missing_counts.append((interval_distance // duration_ms) - 1)
        if (
            row.candle_id in seen_candle_ids
            or row.raw_payload_hash in seen_raw_hashes
            or row.source_sequence_id in seen_source_sequences
        ):
            _invalid("ohlcv_closed_rows_not_unique")
        seen_candle_ids.add(row.candle_id)
        seen_raw_hashes.add(row.raw_payload_hash)
        seen_source_sequences.add(row.source_sequence_id)
        rows.append(row)
        previous_open = row.candle_open_time

    frozen_rows = tuple(rows)
    frozen_gap_indices = tuple(gap_indices)
    frozen_gap_missing_counts = tuple(gap_missing_counts)
    contiguous_suffix_count = (
        len(frozen_rows) if not frozen_gap_indices else len(frozen_rows) - frozen_gap_indices[-1]
    )
    if required_lookback is not None and required_lookback > contiguous_suffix_count:
        _invalid("ohlcv_closed_required_contiguous_window_unavailable")

    wss_count = sum(row.source == "binance_wss" for row in frozen_rows)
    rest_count = len(frozen_rows) - wss_count
    source_key = f"v2:market:ohlcv_closed:binance:{expected_symbol}:{expected_timeframe}"
    return ValidatedOHLCVClosedWindow(
        schema_version=OHLCV_CLOSED_WINDOW_SCHEMA_VERSION,
        source_key=source_key,
        symbol=expected_symbol,
        exchange="binance",
        timeframe=expected_timeframe,
        exact_payload_sha256=hashlib.sha256(payload).hexdigest(),
        exact_payload_byte_count=len(payload),
        row_count=len(frozen_rows),
        rows=frozen_rows,
        first_economic_close_time=frozen_rows[0].candle_close_time,
        latest_economic_close_time=frozen_rows[-1].candle_close_time,
        latest_producer_event_time=max(row.event_time for row in frozen_rows),
        max_ingested_at=max(row.ingested_at for row in frozen_rows),
        max_available_at=max(row.available_at for row in frozen_rows),
        binance_wss_row_count=wss_count,
        binance_rest_row_count=rest_count,
        gap_count=len(frozen_gap_indices),
        gap_indices=frozen_gap_indices,
        gap_missing_interval_counts=frozen_gap_missing_counts,
        missing_interval_count=sum(frozen_gap_missing_counts),
        contiguous_suffix_count=contiguous_suffix_count,
        required_contiguous_lookback=required_lookback,
        required_contiguous_window_satisfied=(True if required_lookback is not None else None),
    )


def require_contiguous_window(
    artifact: object,
    *,
    required_contiguous_lookback: object,
) -> ValidatedOHLCVClosedWindow:
    """Bind a caller-derived lookback to an already validated frozen value.

    The exact class boundary prevents hostile ``__class__`` hooks.  As with the
    dataclass itself, this helper is not an authenticity proof for an instance
    constructed outside :func:`validate_ohlcv_closed_window`.
    """

    required = _validated_required_lookback(required_contiguous_lookback)
    if required is None:  # Kept explicit for type narrowing and future ABI review.
        _invalid("ohlcv_closed_required_lookback_invalid")
    if type(artifact) is not ValidatedOHLCVClosedWindow:
        _invalid("ohlcv_closed_validated_artifact_invalid")
    validated = artifact
    contiguous_suffix_count = validated.contiguous_suffix_count
    if (
        type(contiguous_suffix_count) is not int
        or not 1 <= contiguous_suffix_count <= MAX_OHLCV_CLOSED_ROWS
    ):
        _invalid("ohlcv_closed_validated_artifact_invalid")
    if required > contiguous_suffix_count:
        _invalid("ohlcv_closed_required_contiguous_window_unavailable")
    return replace(
        validated,
        required_contiguous_lookback=required,
        required_contiguous_window_satisfied=True,
    )
