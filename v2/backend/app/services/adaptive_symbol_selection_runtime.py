"""Read-only runtime evidence adapter for adaptive symbol selection.

The adapter reads exact, bounded Redis values.  Volume, returns, and realized
volatility are calculated only from canonical finalized 5-minute candles.
Executability uses a separately clocked current top-of-book snapshot.  It does
not write Redis, mutate an exchange, or interpret current model confidence as
validated edge.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import statistics
import time
from collections.abc import Mapping, Sequence
from typing import Any, NoReturn, Protocol

from v2.backend.app.services.v2_symbol_runtime_universe import is_valid_runtime_symbol

SCHEMA_VERSION = "v2_adaptive_symbol_selection_runtime_evidence_v1"
OHLCV_TIMEFRAME = "5m"
OHLCV_INTERVAL_MS = 5 * 60 * 1000
MAX_RUNTIME_SYMBOLS = 512
MAX_OHLCV_PAYLOAD_BYTES = 512 * 1024
MAX_ORDERBOOK_PAYLOAD_BYTES = 64 * 1024
MAX_COVERAGE_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_CANDLE_ROWS = 1000
MAX_COVERAGE_AGE_SECONDS = 30 * 60
COVERAGE_REDIS_KEY = "v2:universe:coverage_census"


class BoundedRedisReader(Protocol):
    def getrange(self, key: str, start: int, end: int) -> Any: ...


def _reject_constant(_value: str) -> NoReturn:
    raise ValueError("nonfinite_json_constant")


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _clock_seconds(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        number = _finite(value)
        if number is None or number <= 0:
            return None
        if number > 1.0e17:
            number /= 1.0e9
        elif number > 1.0e14:
            number /= 1.0e6
        elif number > 1.0e11:
            number /= 1.0e3
        try:
            dt.datetime.fromtimestamp(number, tz=dt.UTC)
        except (OverflowError, OSError, ValueError):
            return None
        return number
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    try:
        seconds = parsed.timestamp()
        dt.datetime.fromtimestamp(seconds, tz=dt.UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return seconds


def _iso(seconds: float) -> str:
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC).isoformat().replace("+00:00", "Z")


def _bounded_json(
    reader: BoundedRedisReader,
    key: str,
    *,
    max_bytes: int,
) -> tuple[Any | None, str | None]:
    try:
        raw = reader.getrange(key, 0, max_bytes)
    except Exception as exc:  # Redis adapters expose several transport errors.
        return None, f"redis_read_failed:{type(exc).__name__}"
    if raw in (None, b"", ""):
        return None, "redis_value_missing"
    if isinstance(raw, str):
        try:
            encoded = raw.encode("utf-8")
        except UnicodeError:
            return None, "redis_value_utf8_invalid"
    elif isinstance(raw, bytes | bytearray):
        encoded = bytes(raw)
    else:
        return None, "redis_value_type_invalid"
    if len(encoded) > max_bytes:
        return None, "redis_value_resource_limit"
    try:
        return json.loads(encoded, parse_constant=_reject_constant), None
    except (TypeError, ValueError, UnicodeError):
        return None, "redis_value_json_invalid"


def _strict_closed_candle_metrics(
    payload: Any,
    *,
    symbol: str,
    observed_seconds: float,
) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    if not isinstance(payload, list) or not 2 <= len(payload) <= MAX_CANDLE_ROWS:
        return {}, ["closed_candle_window_shape_invalid"]

    closes: list[float] = []
    quote_volumes: list[float] = []
    previous_open_ms: int | None = None
    last_clock_values: dict[str, float] = {}
    for index, raw in enumerate(payload):
        if not isinstance(raw, Mapping):
            blockers.append(f"closed_candle_row_{index}_not_object")
            continue
        if raw.get("symbol") != symbol or raw.get("timeframe") != OHLCV_TIMEFRAME:
            blockers.append(f"closed_candle_row_{index}_identity_invalid")
        if not (
            raw.get("closed_candle") is True
            and raw.get("candle_closed_confirmed") is True
            and raw.get("is_closed") is True
        ):
            blockers.append(f"closed_candle_row_{index}_finality_invalid")

        open_time = raw.get("candle_open_time", raw.get("open_time"))
        close_time = raw.get("candle_close_time", raw.get("close_time"))
        if type(open_time) is not int or type(close_time) is not int:
            blockers.append(f"closed_candle_row_{index}_economic_clock_invalid")
        else:
            if close_time != open_time + OHLCV_INTERVAL_MS - 1:
                blockers.append(f"closed_candle_row_{index}_duration_invalid")
            if previous_open_ms is not None and open_time != previous_open_ms + OHLCV_INTERVAL_MS:
                blockers.append(f"closed_candle_row_{index}_continuity_invalid")
            previous_open_ms = open_time

        event = _clock_seconds(raw.get("event_time"))
        ingested = _clock_seconds(raw.get("ingested_at"))
        available = _clock_seconds(raw.get("available_at"))
        economic_close = _clock_seconds(close_time)
        if None in (economic_close, event, ingested, available):
            blockers.append(f"closed_candle_row_{index}_availability_clock_invalid")
        else:
            assert economic_close is not None
            assert event is not None and ingested is not None and available is not None
            if not economic_close <= event <= ingested <= available <= observed_seconds:
                blockers.append(f"closed_candle_row_{index}_pit_order_invalid")
            if index == len(payload) - 1:
                last_clock_values = {
                    "candle_close_time": economic_close,
                    "feature_cutoff": economic_close,
                    "event_time": event,
                    "ingested_at": ingested,
                    "available_at": available,
                }

        open_price = _finite(raw.get("open"))
        high = _finite(raw.get("high"))
        low = _finite(raw.get("low"))
        close = _finite(raw.get("close"))
        base_volume = _finite(raw.get("volume"))
        quote_volume = _finite(raw.get("quote_volume"))
        if (
            open_price is None
            or high is None
            or low is None
            or close is None
            or min(open_price, high, low, close) <= 0
            or low > min(open_price, close)
            or high < max(open_price, close)
            or low > high
        ):
            blockers.append(f"closed_candle_row_{index}_ohlc_invalid")
        else:
            closes.append(close)
        if base_volume is None or base_volume < 0:
            blockers.append(f"closed_candle_row_{index}_base_volume_invalid")
        if quote_volume is None or quote_volume < 0:
            blockers.append(f"closed_candle_row_{index}_quote_volume_invalid")
        else:
            quote_volumes.append(quote_volume)

    blockers = sorted(set(blockers))
    if blockers or len(closes) != len(payload) or len(quote_volumes) != len(payload):
        return {}, blockers or ["closed_candle_window_incomplete"]
    log_returns = [math.log(right / left) for left, right in zip(closes, closes[1:], strict=False)]
    if not log_returns or any(not math.isfinite(value) for value in log_returns):
        return {}, ["closed_candle_return_window_invalid"]
    realized_volatility_bps = statistics.pstdev(log_returns) * 10_000.0
    absolute_move_bps = abs((closes[-1] / closes[0]) - 1.0) * 10_000.0
    metrics: dict[str, Any] = {
        **{field: _iso(value) for field, value in last_clock_values.items()},
        "candle_final": True,
        "closed_candle_count": len(payload),
        "closed_quote_volume_usd": sum(quote_volumes),
        "realized_volatility_bps": realized_volatility_bps,
        "absolute_move_bps": absolute_move_bps,
    }
    return metrics, []


def _strict_orderbook_metrics(
    payload: Any,
    *,
    symbol: str,
    observed_seconds: float,
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(payload, Mapping):
        return {}, ["orderbook_payload_not_object"]
    blockers: list[str] = []
    if payload.get("symbol") != symbol:
        blockers.append("orderbook_symbol_invalid")
    if payload.get("sequence_gap") is not False:
        blockers.append("orderbook_sequence_gap_or_unknown")
    bid = _finite(payload.get("best_bid", payload.get("bid")))
    ask = _finite(payload.get("best_ask", payload.get("ask")))
    bid_size = _finite(payload.get("best_bid_size", payload.get("bid_size")))
    ask_size = _finite(payload.get("best_ask_size", payload.get("ask_size")))
    if bid is None or ask is None or bid <= 0 or ask <= bid:
        blockers.append("orderbook_prices_invalid")
    if bid_size is None or ask_size is None or bid_size < 0 or ask_size < 0:
        blockers.append("orderbook_sizes_invalid")

    event = _clock_seconds(payload.get("event_time"))
    ingested = _clock_seconds(payload.get("received_at"))
    available = _clock_seconds(payload.get("available_at"))
    generated = _clock_seconds(payload.get("generated_at"))
    if None in (event, ingested, available, generated):
        blockers.append("orderbook_availability_clock_invalid")
    else:
        assert event is not None and ingested is not None
        assert available is not None and generated is not None
        if not event <= ingested <= available <= generated <= observed_seconds:
            blockers.append("orderbook_pit_order_invalid")

    blockers = sorted(set(blockers))
    if blockers:
        return {}, blockers
    assert bid is not None and ask is not None and bid_size is not None and ask_size is not None
    assert event is not None and ingested is not None and available is not None
    mid = (bid + ask) / 2.0
    return {
        "market_event_time": _iso(event),
        "market_ingested_at": _iso(ingested),
        "market_available_at": _iso(available),
        "spread_bps": ((ask - bid) / mid) * 10_000.0,
        "top_book_depth_usd": (bid * bid_size) + (ask * ask_size),
    }, []


def _coverage_evidence(
    coverage_payload: Any,
    *,
    symbol: str,
    observed_seconds: float,
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(coverage_payload, Mapping):
        return {
            "market_data_coverage_ratio": 0.0,
            "training_data_ready": False,
        }, ["coverage_census_missing_or_invalid"]
    generated = _clock_seconds(coverage_payload.get("generated_utc"))
    blockers: list[str] = []
    if generated is None or generated > observed_seconds:
        blockers.append("coverage_census_clock_invalid")
    elif observed_seconds - generated > MAX_COVERAGE_AGE_SECONDS:
        blockers.append("coverage_census_stale")
    symbols = coverage_payload.get("symbols")
    symbol_entry = symbols.get(symbol) if isinstance(symbols, Mapping) else None
    if not isinstance(symbol_entry, Mapping):
        blockers.append("coverage_symbol_entry_missing")
        return {
            "market_data_coverage_ratio": 0.0,
            "training_data_ready": False,
        }, sorted(set(blockers))
    families = symbol_entry.get("families")
    if not isinstance(families, Mapping):
        blockers.append("coverage_families_missing")
        return {
            "market_data_coverage_ratio": 0.0,
            "training_data_ready": False,
        }, sorted(set(blockers))

    ohlcv = families.get("ohlcv_closed")
    prices = families.get("prices")
    orderbook = families.get("orderbook")
    open_interest = families.get("open_interest")
    market_checks = (
        isinstance(ohlcv, Mapping) and ohlcv.get("source_windows_ready") is True,
        isinstance(prices, Mapping) and prices.get("status") == "ok",
        isinstance(orderbook, Mapping) and orderbook.get("status") == "ok",
        isinstance(open_interest, Mapping) and open_interest.get("status") == "ok",
    )
    coverage_ratio = sum(bool(value) for value in market_checks) / len(market_checks)
    ta_full = families.get("ta_full")
    feature_snapshot = families.get("feature_snapshot")
    # Readiness must be explicit.  A fresh feature object is not enough while
    # finality/publication-receipt validators are unbound.
    training_ready = (
        isinstance(ta_full, Mapping)
        and ta_full.get("trainer_consumption_ready") is True
        and isinstance(feature_snapshot, Mapping)
        and feature_snapshot.get("trainer_consumption_ready") is True
    )
    if not training_ready:
        blockers.append("coverage_trainer_consumption_not_explicitly_ready")
    return {
        "market_data_coverage_ratio": coverage_ratio,
        "training_data_ready": training_ready,
        "coverage_generated_at": _iso(generated) if generated is not None else None,
    }, sorted(set(blockers))


def _validation_evidence(edge_row: Any) -> dict[str, Any]:
    if not isinstance(edge_row, Mapping):
        return {}
    out: dict[str, Any] = {
        "validation_sample_count": edge_row.get("outcome_sample_count"),
        "after_cost_expectancy_bps": edge_row.get("after_cost_expectancy_bps"),
        "after_cost_ci_lower_bps": edge_row.get("after_cost_ci_lower_bps"),
        "predictability_source_classification": edge_row.get("classification"),
    }
    # Only explicit validation lineage is passed through.  The current edge
    # attribution artifact does not contain these fields, so confidence or a
    # point prediction can never be upgraded into proof by this adapter.
    for field in (
        "validation_out_of_sample",
        "validation_after_cost",
        "validation_leakage_free",
        "validation_cutoff",
        "validation_event_time",
        "validation_ingested_at",
        "validation_available_at",
        "validation_generated_at",
    ):
        if field in edge_row:
            out[field] = edge_row[field]
    return out


def _unique_edge_rows(edge_rows: Any) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
    """Index valid edge rows without allowing duplicate last-wins evidence."""

    indexed: dict[str, Mapping[str, Any]] = {}
    duplicates: set[str] = set()
    if not isinstance(edge_rows, list):
        return indexed, duplicates
    for row in edge_rows:
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not is_valid_runtime_symbol(symbol):
            continue
        if symbol in indexed:
            duplicates.add(symbol)
            continue
        indexed[symbol] = row
    for symbol in duplicates:
        indexed.pop(symbol, None)
    return indexed, duplicates


def build_runtime_selection_evidence(
    reader: BoundedRedisReader,
    symbols: Sequence[str],
    *,
    edge_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return bounded evidence rows and an end-of-read decision clock."""

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = str(raw or "").strip().upper()
        if is_valid_runtime_symbol(symbol) and symbol not in seen:
            seen.add(symbol)
            normalized.append(symbol)
    if len(normalized) > MAX_RUNTIME_SYMBOLS:
        raise ValueError("adaptive_symbol_runtime_symbol_limit_exceeded")

    coverage_payload, coverage_error = _bounded_json(
        reader,
        COVERAGE_REDIS_KEY,
        max_bytes=MAX_COVERAGE_PAYLOAD_BYTES,
    )
    edge_rows = (
        edge_payload.get("per_symbol")
        if isinstance(edge_payload, Mapping)
        else None
    )
    edge_by_symbol, duplicate_edge_symbols = _unique_edge_rows(edge_rows)

    rows: list[dict[str, Any]] = []
    read_errors: dict[str, int] = {}
    for symbol in normalized:
        ohlcv_key = f"v2:market:ohlcv_closed:binance:{symbol}:{OHLCV_TIMEFRAME}"
        book_key = f"v2:market:orderbook:{symbol}"
        ohlcv, ohlcv_error = _bounded_json(reader, ohlcv_key, max_bytes=MAX_OHLCV_PAYLOAD_BYTES)
        orderbook, orderbook_error = _bounded_json(
            reader, book_key, max_bytes=MAX_ORDERBOOK_PAYLOAD_BYTES
        )
        observed_seconds = time.time()
        candle_metrics, candle_blockers = (
            _strict_closed_candle_metrics(
                ohlcv,
                symbol=symbol,
                observed_seconds=observed_seconds,
            )
            if ohlcv_error is None
            else ({}, [f"ohlcv:{ohlcv_error}"])
        )
        book_metrics, book_blockers = (
            _strict_orderbook_metrics(
                orderbook,
                symbol=symbol,
                observed_seconds=observed_seconds,
            )
            if orderbook_error is None
            else ({}, [f"orderbook:{orderbook_error}"])
        )
        coverage_metrics, coverage_blockers = _coverage_evidence(
            coverage_payload,
            symbol=symbol,
            observed_seconds=observed_seconds,
        )
        blockers = sorted(
            set(
                candle_blockers
                + book_blockers
                + coverage_blockers
                + ([f"coverage:{coverage_error}"] if coverage_error else [])
            )
        )
        for blocker in blockers:
            read_errors[blocker] = read_errors.get(blocker, 0) + 1
        rows.append(
            {
                "symbol": symbol,
                "exchange_confirmed": True,
                "generated_at": _iso(observed_seconds),
                **candle_metrics,
                **book_metrics,
                **coverage_metrics,
                **_validation_evidence(edge_by_symbol.get(symbol)),
                "validation_source_blockers": (
                    ["duplicate_edge_symbol_evidence"]
                    if symbol in duplicate_edge_symbols
                    else []
                ),
                "source_blockers": blockers,
                "source_keys": {
                    "closed_candles": ohlcv_key,
                    "orderbook": book_key,
                },
            }
        )

    decision_seconds = time.time()
    return {
        "schema_version": SCHEMA_VERSION,
        "decision_time": _iso(decision_seconds),
        "evidence_rows": rows,
        "metrics": {
            "requested_symbol_count": len(symbols),
            "normalized_symbol_count": len(normalized),
            "evidence_row_count": len(rows),
            "source_blocker_counts": dict(sorted(read_errors.items())),
            "coverage_payload_read_ok": coverage_error is None,
            "edge_payload_present": isinstance(edge_payload, Mapping),
            "duplicate_edge_symbol_count": len(duplicate_edge_symbols),
            "duplicate_edge_symbols": sorted(duplicate_edge_symbols),
        },
        "source_contract": {
            "opportunity_and_volume": "canonical_finalized_5m_candles_only",
            "executability": "explicitly_clocked_current_top_of_book",
            "training_readiness": "strict_coverage_census_explicit_trainer_consumption_ready",
            "predictability": "explicit_oos_after_cost_lineage_only",
        },
        "places_real_order": False,
        "writes_redis": False,
        "selection_is_execution_authorization": False,
        "rankings_are_opportunity_and_feasibility_candidates_not_forecasts": True,
        "guaranteed_return_claim": False,
        "guaranteed_1000x_claim": False,
    }
