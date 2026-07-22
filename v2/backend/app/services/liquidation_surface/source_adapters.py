"""Strict adapters from exact Redis evidence into liquidation-surface inputs.

The adapters do not call providers and do not write Redis.  Every input is the
exact byte string observed by the caller at a supplied consumer clock.  The
SHA-256 of those bytes becomes lineage; producer timestamps are validated but
never mistaken for a Redis commit receipt.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .contracts import (
    CandleObservation,
    MarkPriceObservation,
    OpenInterestObservation,
)

BINANCE_USDM_VENUE = "binance_usdm"
COINANK_OPEN_INTEREST_ENDPOINT = "openInterest_kline"
MAX_RAW_REDIS_BYTES = 16 * 1024 * 1024
MAX_SOURCE_ROWS = 250_000
_MAX_SIGNED_64_BIT_INTEGER = (1 << 63) - 1

_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_BINANCE_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,30}$")
_TIMEFRAME_RE = re.compile(r"^([1-9][0-9]*)([smhdw])$")
_TIMEFRAME_UNIT_MS = {
    "s": 1_000,
    "m": 60_000,
    "h": 3_600_000,
    "d": 86_400_000,
    "w": 604_800_000,
}


class SourceAdapterError(ValueError):
    """Raised when exact source bytes violate identity, PIT, or finality."""


@dataclass(frozen=True)
class RawRedisEvidence:
    key: str
    raw: bytes
    consumer_observed_at_ms: int

    @classmethod
    def from_value(
        cls,
        *,
        key: Any,
        value: Any,
        consumer_observed_at_ms: Any,
    ) -> RawRedisEvidence:
        if not isinstance(key, str) or not key or key.strip() != key:
            raise SourceAdapterError("REDIS_KEY_INVALID")
        if isinstance(value, str):
            raw = value.encode("utf-8")
        elif isinstance(value, bytes):
            raw = value
        else:
            raise SourceAdapterError("REDIS_VALUE_NOT_EXACT_TEXT_OR_BYTES")
        if not raw:
            raise SourceAdapterError("REDIS_VALUE_EMPTY")
        if len(raw) > MAX_RAW_REDIS_BYTES:
            raise SourceAdapterError("REDIS_VALUE_EXCEEDS_HARD_RESOURCE_MAXIMUM")
        observed = _positive_epoch_ms(
            consumer_observed_at_ms,
            name="CONSUMER_OBSERVED_AT",
        )
        return cls(key=key, raw=raw, consumer_observed_at_ms=observed)

    @property
    def raw_sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()

    def json_value(self) -> Any:
        try:
            text = self.raw.decode("utf-8", errors="strict")
            return json.loads(text, parse_constant=_reject_nonfinite_json)
        except (RecursionError, UnicodeDecodeError, TypeError, ValueError) as exc:
            raise SourceAdapterError("REDIS_VALUE_NOT_STRICT_JSON") from exc


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"NONFINITE_JSON_CONSTANT:{value}")


def _positive_epoch_ms(value: Any, *, name: str) -> int:
    if isinstance(value, bool):
        raise SourceAdapterError(f"{name}_NOT_INTEGER_MS")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value and value.strip() == value:
        if value.isdigit():
            if len(value) > 19:
                raise SourceAdapterError(f"{name}_OUTSIDE_SIGNED_64_BIT_MS")
            parsed = int(value)
        else:
            try:
                timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise SourceAdapterError(f"{name}_INVALID") from exc
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise SourceAdapterError(f"{name}_NAIVE")
            parsed = int(timestamp.astimezone(UTC).timestamp() * 1_000)
    else:
        raise SourceAdapterError(f"{name}_NOT_INTEGER_MS")
    if parsed <= 0:
        raise SourceAdapterError(f"{name}_NOT_POSITIVE")
    if parsed > _MAX_SIGNED_64_BIT_INTEGER:
        raise SourceAdapterError(f"{name}_OUTSIDE_SIGNED_64_BIT_MS")
    return parsed


def _finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or value in (None, ""):
        raise SourceAdapterError(f"{name}_MISSING_OR_BOOLEAN")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SourceAdapterError(f"{name}_NOT_NUMERIC") from exc
    if not math.isfinite(parsed):
        raise SourceAdapterError(f"{name}_NOT_FINITE")
    return parsed


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SourceAdapterError(f"{name}_NOT_POSITIVE_INTEGER")
    return value


def _timeframe_duration_ms(timeframe: Any) -> int:
    if not isinstance(timeframe, str) or timeframe.strip().lower() != timeframe:
        raise SourceAdapterError("TIMEFRAME_NOT_CANONICAL")
    matched = _TIMEFRAME_RE.fullmatch(timeframe)
    if matched is None:
        raise SourceAdapterError("TIMEFRAME_UNSUPPORTED")
    count_text = matched.group(1)
    if len(count_text) > 19:
        raise SourceAdapterError("TIMEFRAME_DURATION_OUTSIDE_SIGNED_64_BIT_MS")
    duration_ms = int(count_text) * _TIMEFRAME_UNIT_MS[matched.group(2)]
    if duration_ms > _MAX_SIGNED_64_BIT_INTEGER:
        raise SourceAdapterError("TIMEFRAME_DURATION_OUTSIDE_SIGNED_64_BIT_MS")
    return duration_ms


def _canonical_symbol(value: Any, *, expected: str) -> str:
    if (
        not isinstance(value, str)
        or value != expected
        or value != value.upper()
        or _BINANCE_SYMBOL_RE.fullmatch(value) is None
    ):
        raise SourceAdapterError("SYMBOL_MISMATCH_OR_NOT_CANONICAL")
    return value


def _require_no_positive_authority_claim(value: Any) -> None:
    stack: list[Any] = [value]
    nodes = 0
    while stack:
        current = stack.pop()
        nodes += 1
        if nodes > 65_536:
            raise SourceAdapterError("SOURCE_AUTHORITY_SCAN_LIMIT_EXCEEDED")
        if isinstance(current, Mapping):
            for raw_key, nested in current.items():
                key = str(raw_key).strip().lower()
                if (key == "authority" or key.endswith("_authority")) and nested is not False:
                    raise SourceAdapterError("UNVERIFIED_SOURCE_AUTHORITY_CLAIM")
                if isinstance(nested, Mapping | list | tuple):
                    stack.append(nested)
        elif isinstance(current, list | tuple):
            stack.extend(nested for nested in current if isinstance(nested, Mapping | list | tuple))


def _latest_contiguous_candle_suffix(
    rows: list[CandleObservation],
    *,
    duration_ms: int,
    max_rows: int,
) -> tuple[CandleObservation, ...]:
    ordered = sorted(rows, key=lambda row: row.open_time_ms)
    if len({row.open_time_ms for row in ordered}) != len(ordered):
        raise SourceAdapterError("DUPLICATE_CANDLE_OPEN_TIME")
    start = len(ordered) - 1
    while start > 0:
        left = ordered[start - 1]
        right = ordered[start]
        if (
            right.open_time_ms - left.open_time_ms != duration_ms
            or right.close_time_ms - left.close_time_ms != duration_ms
        ):
            break
        start -= 1
    return tuple(ordered[start:][-max_rows:])


def adapt_binance_finalized_candles(
    evidence: RawRedisEvidence,
    *,
    symbol: str,
    timeframe: str,
    max_rows: int = 4_096,
) -> tuple[CandleObservation, ...]:
    """Adapt canonical native-ingestor OHLCV bytes for one USD-M market."""

    canonical_symbol = _canonical_symbol(symbol, expected=symbol)
    duration_ms = _timeframe_duration_ms(timeframe)
    row_limit = _positive_int(max_rows, name="MAX_ROWS")
    allowed_keys = {
        f"v2:market:ohlcv:binance:{canonical_symbol}:{timeframe}",
        f"v2:market:ohlcv_closed:binance:{canonical_symbol}:{timeframe}",
    }
    if evidence.key not in allowed_keys:
        raise SourceAdapterError("CANDLE_REDIS_KEY_IDENTITY_MISMATCH")
    payload = evidence.json_value()
    if not isinstance(payload, list) or not payload:
        raise SourceAdapterError("CANDLE_PAYLOAD_NOT_NONEMPTY_LIST")
    if len(payload) > MAX_SOURCE_ROWS:
        raise SourceAdapterError("CANDLE_SOURCE_ROWS_EXCEED_HARD_RESOURCE_MAXIMUM")
    _require_no_positive_authority_claim(payload)
    parsed: list[CandleObservation] = []
    for row in payload:
        if not isinstance(row, Mapping):
            raise SourceAdapterError("CANDLE_ROW_NOT_OBJECT")
        _canonical_symbol(row.get("symbol"), expected=canonical_symbol)
        closed_window_key = (
            evidence.key
            == f"v2:market:ohlcv_closed:binance:{canonical_symbol}:{timeframe}"
        )
        product_identity = (row.get("venue"), row.get("product_type"))
        product_identity_valid = product_identity == (BINANCE_USDM_VENUE, "USD-M")
        product_identity_legacy_absent = product_identity == (None, None)
        if (
            row.get("exchange") != "binance"
            or row.get("timeframe") != timeframe
            or not (
                product_identity_valid
                or (closed_window_key and product_identity_legacy_absent)
            )
        ):
            raise SourceAdapterError("CANDLE_ROW_VENUE_OR_TIMEFRAME_MISMATCH")
        if row.get("is_closed") is not True:
            raise SourceAdapterError("CANDLE_ROW_NOT_FINAL")
        for alias in ("closed_candle", "candle_closed_confirmed", "feature_eligible"):
            if row.get(alias) is not True:
                raise SourceAdapterError(f"CANDLE_ROW_{alias.upper()}_NOT_TRUE")
        source = str(row.get("source") or "").lower()
        if source not in {"binance_wss", "binance_rest"}:
            if not source.startswith("v2_closed_candle_resampler:"):
                raise SourceAdapterError("CANDLE_SOURCE_NOT_BINANCE_CANONICAL")
            resampled_from = row.get("resampled_from_timeframe")
            if source != f"v2_closed_candle_resampler:{resampled_from}":
                raise SourceAdapterError("CANDLE_RESAMPLER_SOURCE_IDENTITY_MISMATCH")
            source_duration_ms = _timeframe_duration_ms(resampled_from)
            expected_source_count = duration_ms // source_duration_ms
            if (
                source_duration_ms >= duration_ms
                or duration_ms % source_duration_ms != 0
                or row.get("resampled_source_candle_count") != expected_source_count
            ):
                raise SourceAdapterError("CANDLE_RESAMPLER_COVERAGE_INVALID")
        raw_payload_hash = row.get("raw_payload_hash")
        if not isinstance(raw_payload_hash, str) or not _HEX_SHA256_RE.fullmatch(raw_payload_hash):
            raise SourceAdapterError("CANDLE_RAW_PAYLOAD_HASH_INVALID")
        open_time = _positive_epoch_ms(row.get("candle_open_time"), name="CANDLE_OPEN_TIME")
        close_time = _positive_epoch_ms(
            row.get("candle_close_time"),
            name="CANDLE_CLOSE_TIME",
        )
        event_time = _positive_epoch_ms(row.get("event_time"), name="CANDLE_EVENT_TIME")
        ingested_at = _positive_epoch_ms(row.get("ingested_at"), name="CANDLE_INGESTED_AT")
        source_available_at = _positive_epoch_ms(
            row.get("available_at"),
            name="CANDLE_SOURCE_AVAILABLE_AT",
        )
        if not (
            open_time
            < close_time
            <= event_time
            <= ingested_at
            <= source_available_at
            <= evidence.consumer_observed_at_ms
        ):
            raise SourceAdapterError("CANDLE_SOURCE_CLOCK_ORDER_INVALID")
        parsed.append(
            CandleObservation(
                venue=BINANCE_USDM_VENUE,
                symbol=canonical_symbol,
                timeframe=timeframe,
                open_time_ms=open_time,
                close_time_ms=close_time,
                event_time_ms=event_time,
                ingested_at_ms=ingested_at,
                available_at_ms=evidence.consumer_observed_at_ms,
                is_final=True,
                open=_finite(row.get("open"), name="CANDLE_OPEN"),
                high=_finite(row.get("high"), name="CANDLE_HIGH"),
                low=_finite(row.get("low"), name="CANDLE_LOW"),
                close=_finite(row.get("close"), name="CANDLE_CLOSE"),
                quote_volume=(
                    _finite(row.get("quote_volume"), name="CANDLE_QUOTE_VOLUME")
                    if row.get("quote_volume") is not None
                    else None
                ),
                taker_buy_quote_volume=(
                    _finite(
                        row.get("taker_buy_quote_vol"),
                        name="CANDLE_TAKER_BUY_QUOTE_VOLUME",
                    )
                    if row.get("taker_buy_quote_vol") is not None
                    else None
                ),
                source_key=evidence.key,
                source_sha256=evidence.raw_sha256,
            )
        )
    suffix = _latest_contiguous_candle_suffix(
        parsed,
        duration_ms=duration_ms,
        max_rows=row_limit,
    )
    if not suffix:
        raise SourceAdapterError("CANDLE_CONTIGUOUS_SUFFIX_EMPTY")
    return suffix


def adapt_binance_mark_price(
    evidence: RawRedisEvidence,
    *,
    symbol: str,
) -> MarkPriceObservation:
    canonical_symbol = _canonical_symbol(symbol, expected=symbol)
    allowed_keys = {
        f"v2:market:funding:{canonical_symbol}",
        f"v2:market:mark_price:{canonical_symbol}",
    }
    if evidence.key not in allowed_keys:
        raise SourceAdapterError("MARK_PRICE_REDIS_KEY_IDENTITY_MISMATCH")
    payload = evidence.json_value()
    if not isinstance(payload, Mapping):
        raise SourceAdapterError("MARK_PRICE_PAYLOAD_NOT_OBJECT")
    _require_no_positive_authority_claim(payload)
    if payload.get("symbol") != canonical_symbol:
        raise SourceAdapterError("MARK_PRICE_SYMBOL_MISMATCH")
    product_identity = (payload.get("venue"), payload.get("product_type"))
    product_identity_valid = product_identity == (BINANCE_USDM_VENUE, "USD-M")
    product_identity_legacy_absent = product_identity == (None, None)
    exact_wss_key = evidence.key == f"v2:market:mark_price:{canonical_symbol}"
    if not (
        product_identity_valid
        or (exact_wss_key and product_identity_legacy_absent)
    ):
        raise SourceAdapterError("MARK_PRICE_VENUE_OR_PRODUCT_TYPE_MISMATCH")
    source = str(payload.get("source") or "").strip().lower()
    transport = str(payload.get("transport") or "").strip().lower()
    if exact_wss_key:
        if (
            payload.get("schema_version") != "binance_usdm_mark_price_wss_v1"
            or source != "binance_usdm_wss_mark_price_all_symbols"
            or transport != "websocket_primary"
        ):
            raise SourceAdapterError("MARK_PRICE_SOURCE_NOT_EXACT_BINANCE_USDM_WSS")
    elif source == "binance_usdm_wss_mark_price_all_symbols":
        if (
            payload.get("schema_version") != "binance_usdm_mark_price_wss_v1"
            or transport != "websocket_primary"
        ):
            raise SourceAdapterError("MARK_PRICE_SOURCE_NOT_EXACT_BINANCE_USDM_WSS")
    elif source == "binance_public_rest_premium_index_fallback":
        if (
            transport != "rest_fallback"
            or payload.get("source_endpoint") != "/fapi/v1/premiumIndex"
        ):
            raise SourceAdapterError("MARK_PRICE_SOURCE_NOT_EXACT_BINANCE_USDM_REST")
    else:
        raise SourceAdapterError("MARK_PRICE_SOURCE_NOT_BINANCE_USDM")
    event_time = _positive_epoch_ms(
        next(
            (
                payload.get(field)
                for field in ("event_time", "time", "timestamp", "binance_time_ms", "E")
                if payload.get(field) not in (None, "")
            ),
            None,
        ),
        name="MARK_PRICE_EVENT_TIME",
    )
    source_available_value = next(
        (
            payload.get(field)
            for field in ("available_at", "received_at", "consumer_observed_at", "republished_at")
            if payload.get(field) not in (None, "")
        ),
        None,
    )
    source_available = (
        _positive_epoch_ms(source_available_value, name="MARK_PRICE_SOURCE_AVAILABLE_AT")
        if source_available_value is not None
        else evidence.consumer_observed_at_ms
    )
    if not event_time <= source_available <= evidence.consumer_observed_at_ms:
        raise SourceAdapterError("MARK_PRICE_SOURCE_CLOCK_ORDER_INVALID")
    price = _finite(
        payload.get("markPrice")
        if payload.get("markPrice") not in (None, "")
        else payload.get("mark_price"),
        name="MARK_PRICE",
    )
    if price <= 0.0:
        raise SourceAdapterError("MARK_PRICE_NOT_POSITIVE")
    return MarkPriceObservation(
        venue=BINANCE_USDM_VENUE,
        symbol=canonical_symbol,
        event_time_ms=event_time,
        ingested_at_ms=source_available,
        available_at_ms=evidence.consumer_observed_at_ms,
        price=price,
        source_key=evidence.key,
        source_sha256=evidence.raw_sha256,
    )


def _latest_contiguous_oi_suffix(
    rows: list[OpenInterestObservation],
    *,
    duration_ms: int,
    max_rows: int,
) -> tuple[OpenInterestObservation, ...]:
    ordered = sorted(rows, key=lambda row: row.feature_cutoff_ms)
    if len({row.feature_cutoff_ms for row in ordered}) != len(ordered):
        raise SourceAdapterError("DUPLICATE_OPEN_INTEREST_FEATURE_CUTOFF")
    start = len(ordered) - 1
    while start > 0:
        if ordered[start].feature_cutoff_ms - ordered[start - 1].feature_cutoff_ms != duration_ms:
            break
        start -= 1
    return tuple(ordered[start:][-max_rows:])


def adapt_coinank_plan3_open_interest(
    evidence: RawRedisEvidence,
    *,
    symbol: str,
    source_timeframe: str,
    max_rows: int = 4_096,
) -> tuple[OpenInterestObservation, ...]:
    """Adapt Plan3 venue-specific CoinAnk OI kline evidence.

    This function never accepts heatmap/map payloads.  The endpoint, Binance
    venue, exact symbol, interval, request-start finality cutoff, and response
    observation clock are all mandatory.
    """

    canonical_symbol = _canonical_symbol(symbol, expected=symbol)
    duration_ms = _timeframe_duration_ms(source_timeframe)
    row_limit = _positive_int(max_rows, name="MAX_ROWS")
    expected_key = f"latest:coinank:open_interest:{canonical_symbol}:{source_timeframe}"
    if evidence.key != expected_key:
        raise SourceAdapterError("COINANK_OI_REDIS_KEY_IDENTITY_MISMATCH")
    payload = evidence.json_value()
    if not isinstance(payload, Mapping):
        raise SourceAdapterError("COINANK_OI_PAYLOAD_NOT_OBJECT")
    _require_no_positive_authority_claim(payload)
    _canonical_symbol(payload.get("symbol"), expected=canonical_symbol)
    if payload.get("family") != "open_interest":
        raise SourceAdapterError("COINANK_OI_FAMILY_MISMATCH")
    if payload.get("endpoint") != COINANK_OPEN_INTEREST_ENDPOINT:
        raise SourceAdapterError("COINANK_OI_ENDPOINT_MISMATCH")
    interval = payload.get("interval", payload.get("timeframe"))
    if interval != source_timeframe:
        raise SourceAdapterError("COINANK_OI_TIMEFRAME_MISMATCH")
    allowed_exchanges = {
        "binance",
        "binance futures",
        "binance_usdm",
        "binance usdm",
    }
    exchange = str(payload.get("exchange") or "").strip().lower().replace("-", "_")
    if exchange not in allowed_exchanges:
        raise SourceAdapterError("COINANK_OI_VENUE_NOT_BINANCE_USDM")
    request_parameters = payload.get("request_parameters")
    if not isinstance(request_parameters, Mapping):
        raise SourceAdapterError("COINANK_OI_REQUEST_PARAMETERS_MISSING")
    _canonical_symbol(request_parameters.get("symbol"), expected=canonical_symbol)
    parameter_exchange = (
        str(request_parameters.get("exchange") or "").strip().lower().replace("-", "_")
    )
    if parameter_exchange not in allowed_exchanges or parameter_exchange != exchange:
        raise SourceAdapterError("COINANK_OI_REQUEST_VENUE_MISMATCH")
    if request_parameters.get("interval") != source_timeframe:
        raise SourceAdapterError("COINANK_OI_REQUEST_TIMEFRAME_MISMATCH")
    if request_parameters.get("productType") != "SWAP":
        raise SourceAdapterError("COINANK_OI_REQUEST_PRODUCT_TYPE_NOT_SWAP")
    request_started_at = _positive_epoch_ms(
        payload.get("request_started_at_ms"),
        name="COINANK_REQUEST_STARTED_AT",
    )
    fetched_at = _positive_epoch_ms(
        payload.get("ts_ms", payload.get("timestamp")),
        name="COINANK_FETCHED_AT",
    )
    if not (request_started_at <= fetched_at <= evidence.consumer_observed_at_ms):
        raise SourceAdapterError("COINANK_OI_ENVELOPE_CLOCK_ORDER_INVALID")
    outer = payload.get("data")
    if (
        not isinstance(outer, Mapping)
        or outer.get("success") is not True
        or str(outer.get("code")) != "1"
    ):
        raise SourceAdapterError("COINANK_OI_RESPONSE_NOT_SUCCESS")
    rows = outer.get("data")
    if not isinstance(rows, list) or not rows:
        raise SourceAdapterError("COINANK_OI_ROWS_MISSING")
    if len(rows) > MAX_SOURCE_ROWS:
        raise SourceAdapterError("COINANK_OI_SOURCE_ROWS_EXCEED_HARD_RESOURCE_MAXIMUM")
    parsed: list[OpenInterestObservation] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise SourceAdapterError("COINANK_OI_ROW_NOT_OBJECT")
        begin = _positive_epoch_ms(row.get("begin"), name="COINANK_OI_BEGIN")
        cutoff = begin + duration_ms
        if cutoff >= request_started_at:
            continue
        value = _finite(row.get("close"), name="COINANK_OI_CLOSE")
        if value < 0.0:
            raise SourceAdapterError("COINANK_OI_CLOSE_NEGATIVE")
        parsed.append(
            OpenInterestObservation(
                venue=BINANCE_USDM_VENUE,
                symbol=canonical_symbol,
                timeframe=source_timeframe,
                feature_cutoff_ms=cutoff,
                event_time_ms=cutoff,
                ingested_at_ms=fetched_at,
                available_at_ms=evidence.consumer_observed_at_ms,
                is_final=True,
                value=value,
                # CoinAnk documents /api/openInterest/kline as the trading-pair
                # position *quantity* series.  It is base-asset quantity, not
                # quote notional and not an exchange contract-count assertion.
                unit="base_asset",
                source_key=evidence.key,
                source_sha256=evidence.raw_sha256,
            )
        )
    if not parsed:
        raise SourceAdapterError("COINANK_OI_NO_FINALIZED_ROWS")
    return _latest_contiguous_oi_suffix(
        parsed,
        duration_ms=duration_ms,
        max_rows=row_limit,
    )


__all__ = [
    "BINANCE_USDM_VENUE",
    "COINANK_OPEN_INTEREST_ENDPOINT",
    "MAX_RAW_REDIS_BYTES",
    "MAX_SOURCE_ROWS",
    "RawRedisEvidence",
    "SourceAdapterError",
    "adapt_binance_finalized_candles",
    "adapt_binance_mark_price",
    "adapt_coinank_plan3_open_interest",
]
