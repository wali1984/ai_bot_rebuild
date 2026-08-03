"""Full TA-Lib compatibility payloads for V2-owned TA keys.

The legacy runtime published a broad ``ta:{symbol}:{timeframe}`` surface with
roughly 160 TA fields. The native V2 feature loop intentionally publishes a
compact trainer-ready subset. This module restores the broad TA-Lib data plane
under V2-only keys while preserving the safety boundary:

* reads caller-provided OHLCV rows only
* writes nothing by itself
* never imports exchange clients
* never emits legacy Redis keys
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np

from v2.backend.app.services.native_trainer.model_ta_technical_dependency_contract import (
    CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS,
    inspect_strict_latest_output,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    ValidatedOHLCVClosedWindow,
)

FULL_TALIB_TA_SCHEMA_VERSION = "v2_full_talib_ta_payload_v1"
FULL_TALIB_TA_CLOSED_CANDIDATE_SCHEMA_VERSION = "v2_full_talib_ta_closed_candidate_v1"
LIVE_GATE_BLOCKED = "blocked_human_only"
DEFAULT_MIN_CANDLES = 60
FULL_TALIB_TA_REQUIRED_CONTIGUOUS_ROWS = CURRENT_TIMEFRAME_MODEL_TA_MINIMUM_ROWS

TIMEFRAME_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


@dataclass(frozen=True)
class NormalizedCandle:
    ts_ms: int | None
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class FullTalibTAResult:
    """Computed full-TA payload plus summary fields."""

    symbol: str
    timeframe: str
    indicators: dict[str, float] = field(default_factory=dict)
    computed_functions: list[str] = field(default_factory=list)
    skipped_functions: dict[str, str] = field(default_factory=dict)
    candle_count: int = 0
    last_candle_ts_ms: int | None = None
    talib_function_count: int = 0
    classification: str = "NOT_RUN"
    rejected_outputs: dict[str, str] = field(default_factory=dict)

    @property
    def indicator_count(self) -> int:
        return len(self.indicators)

    def to_payload(self, *, source_ohlcv_key: str | None = None) -> dict[str, Any]:
        return {
            "schema_version": FULL_TALIB_TA_SCHEMA_VERSION,
            "source_label": "V2_FULL_TALIB_TA_LIVE",
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "generated_utc": _utc_iso(),
            "source_ohlcv_key": source_ohlcv_key,
            "library_used": "talib",
            "talib_function_count": self.talib_function_count,
            "computed_function_count": len(self.computed_functions),
            "computed_functions": list(self.computed_functions),
            "skipped_function_count": len(self.skipped_functions),
            "skipped_functions": dict(self.skipped_functions),
            "strict_latest_output_rejection_count": len(self.rejected_outputs),
            "strict_latest_output_rejections": dict(self.rejected_outputs),
            "candle_count": self.candle_count,
            "last_candle_ts_ms": self.last_candle_ts_ms,
            "field_count": self.indicator_count,
            "indicator_count": self.indicator_count,
            "indicators": dict(sorted(self.indicators.items())),
            "families_present": _families_present(self.indicators),
            "classification": self.classification,
            # A mutable compatibility payload is not trainer evidence.  Exact
            # source validation and a successful Redis SET still do not prove
            # postcommit availability or immutable capture.
            "trainer_consumable": False,
            "consumer_eligible": False,
            "redis_read_receipt_emitted": False,
            "immutable_cas_captured": False,
            "legacy_ta_field_parity_target": "about_160_fields_from_LEGACY_SYSTEM_FULL_AUDIT",
            "legacy_redis_key_equivalent": f"ta:{self.symbol}:{self.timeframe}",
            "v2_only": True,
            "writes_legacy_redis": False,
            "exchange_action_taken": False,
            "places_real_order": False,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "no_zero_fill": True,
        }


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _epoch_ms_iso(value: int) -> str:
    return (
        datetime.fromtimestamp(value / 1000.0, tz=UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _as_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _as_int(value: Any) -> int | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return int(f)


def _first_present_mapping_value(
    row: Mapping[Any, Any],
    *keys: str,
) -> Any:
    """Select by key presence so authenticated numeric zero remains data."""

    for key in keys:
        if key in row:
            return row[key]
    return None


def normalize_ohlcv_rows(rows: Sequence[Any]) -> list[NormalizedCandle]:
    """Normalize Binance-list or dict OHLCV rows into chronological candles."""
    candles: list[NormalizedCandle] = []
    for row in rows:
        ts_ms: int | None
        o: float | None
        h: float | None
        low: float | None
        c: float | None
        v: float | None
        if isinstance(row, Mapping):
            ts_ms = _as_int(
                _first_present_mapping_value(
                    row,
                    "ts_ms",
                    "timestamp",
                    "open_time",
                    "openTime",
                    "time",
                    "t",
                )
            )
            o = _as_float(_first_present_mapping_value(row, "open", "o"))
            h = _as_float(_first_present_mapping_value(row, "high", "h"))
            low = _as_float(_first_present_mapping_value(row, "low", "l"))
            c = _as_float(_first_present_mapping_value(row, "close", "c"))
            v = _as_float(_first_present_mapping_value(row, "volume", "v"))
        elif isinstance(row, list | tuple) and len(row) >= 6:
            ts_ms = _as_int(row[0])
            o = _as_float(row[1])
            h = _as_float(row[2])
            low = _as_float(row[3])
            c = _as_float(row[4])
            v = _as_float(row[5])
        else:
            continue
        if o is None or h is None or low is None or c is None or v is None:
            continue
        candles.append(
            NormalizedCandle(
                ts_ms=ts_ms,
                open=float(o),
                high=float(h),
                low=float(low),
                close=float(c),
                volume=float(v),
            )
        )
    return sorted(candles, key=lambda candle: candle.ts_ms or 0)


def _row_close_boundary_ms(row: Any, timeframe_ms: int | None) -> int | None:
    """Best truthful close boundary for one OHLCV row; None when unprovable."""
    close_ts: int | None = None
    open_ts: int | None = None
    if isinstance(row, Mapping):
        close_ts = _as_int(
            _first_present_mapping_value(
                row,
                "close_time",
                "closeTime",
                "close_ts_ms",
            )
        )
        open_ts = _as_int(
            _first_present_mapping_value(
                row,
                "ts_ms",
                "timestamp",
                "open_time",
                "openTime",
                "time",
                "t",
            )
        )
    elif isinstance(row, list | tuple):
        if len(row) >= 7:
            close_ts = _as_int(row[6])
        if len(row) >= 1:
            open_ts = _as_int(row[0])
    if close_ts is not None:
        return close_ts
    if open_ts is not None and timeframe_ms:
        return open_ts + timeframe_ms - 1
    return None


def filter_closed_ohlcv_rows(
    rows: Sequence[Any],
    *,
    timeframe: str,
    now_ms: int | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Keep only candles whose close boundary is confirmed in the past.

    Fail-closed: a row whose closed-ness cannot be proven (no close_time and
    unknown timeframe) is dropped, never assumed closed.
    """
    if now_ms is None:
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
    timeframe_ms = TIMEFRAME_MS.get(str(timeframe))
    closed: list[Any] = []
    dropped_unclosed = 0
    dropped_unprovable = 0
    last_closed_open_ts: int | None = None
    last_closed_close_ts: int | None = None
    for row in rows:
        boundary = _row_close_boundary_ms(row, timeframe_ms)
        if boundary is None:
            dropped_unprovable += 1
            continue
        if boundary > now_ms:
            dropped_unclosed += 1
            continue
        closed.append(row)
        open_ts = None
        if isinstance(row, list | tuple) and row:
            open_ts = _as_int(row[0])
        elif isinstance(row, Mapping):
            open_ts = _as_int(
                _first_present_mapping_value(
                    row,
                    "ts_ms",
                    "timestamp",
                    "open_time",
                    "openTime",
                )
            )
        if last_closed_close_ts is None or boundary > last_closed_close_ts:
            last_closed_close_ts = boundary
            last_closed_open_ts = open_ts
    meta = {
        "closed_candle_count": len(closed),
        "dropped_unclosed_count": dropped_unclosed,
        "dropped_unprovable_count": dropped_unprovable,
        "last_closed_candle_open_ts_ms": last_closed_open_ts,
        "last_closed_candle_close_ts_ms": last_closed_close_ts,
        "now_ms": now_ms,
        "timeframe_ms": timeframe_ms,
    }
    return closed, meta


def _strict_latest_output(
    value: Any,
    *,
    source_row_count: int,
) -> tuple[float | None, str]:
    """Select only the exact final TA output for the exact source window.

    This deliberately never scans backward.  A non-finite final value, a
    scalar, a multidimensional value, or a length mismatch stays missing even
    when an older element is finite.
    """

    audit = inspect_strict_latest_output(
        value,
        source_row_count=source_row_count,
    )
    if audit.status != "PRESENT_FINITE":
        return None, audit.status
    return audit.latest_value, audit.status


def _field_name(function_name: str, output_name: str) -> str:
    if output_name == "real":
        return f"ta_{function_name}"
    return f"ta_{function_name}_{output_name}"


def _put(
    indicators: dict[str, float],
    name: str,
    value: Any,
    *,
    source_row_count: int,
    rejected_outputs: dict[str, str],
) -> bool:
    latest, status = _strict_latest_output(
        value,
        source_row_count=source_row_count,
    )
    if latest is None:
        rejected_outputs[name] = status
        return False
    indicators[name] = latest
    return True


def _compute_aliases(
    indicators: dict[str, float],
    *,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    rejected_outputs: dict[str, str],
) -> None:
    """Add legacy/trainer aliases with explicit periods used by old consumers."""
    import talib  # type: ignore

    source_row_count = len(closes)

    def put(name: str, value: Any) -> bool:
        return _put(
            indicators,
            name,
            value,
            source_row_count=source_row_count,
            rejected_outputs=rejected_outputs,
        )

    put("ta_RSI_14", talib.RSI(closes, timeperiod=14))
    put("rsi_14", talib.RSI(closes, timeperiod=14))
    macd, signal, hist = talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)
    put("ta_MACD_12_26_9_macd", macd)
    put("ta_MACD_12_26_9_signal", signal)
    put("ta_MACD_12_26_9_hist", hist)
    put("ta_MACDhist_12_26_9", hist)
    put("macd", macd)
    put("macd_signal", signal)
    put("macd_hist", hist)
    put("ta_ATR_14", talib.ATR(highs, lows, closes, timeperiod=14))
    put("atr_14", talib.ATR(highs, lows, closes, timeperiod=14))
    for period in (9, 12, 20, 21, 26, 50):
        put(f"ta_EMA_{period}", talib.EMA(closes, timeperiod=period))
        put(f"ema_{period}", talib.EMA(closes, timeperiod=period))
        put(f"ta_SMA_{period}", talib.SMA(closes, timeperiod=period))
        put(f"sma_{period}", talib.SMA(closes, timeperiod=period))
    upper, middle, lower = talib.BBANDS(
        closes,
        timeperiod=20,
        nbdevup=2,
        nbdevdn=2,
        matype=talib.MA_Type.SMA,
    )
    put("ta_BBANDS_20_upper", upper)
    put("ta_BBANDS_20_middle", middle)
    put("ta_BBANDS_20_lower", lower)
    bbw = None
    upper_last, _ = _strict_latest_output(upper, source_row_count=source_row_count)
    lower_last, _ = _strict_latest_output(lower, source_row_count=source_row_count)
    middle_last, _ = _strict_latest_output(middle, source_row_count=source_row_count)
    if upper_last is not None and lower_last is not None and middle_last and middle_last > 0:
        bbw = (upper_last - lower_last) / middle_last
    if bbw is not None:
        indicators["ta_BB_width_pct"] = float(bbw)
        indicators["bb_width_pct"] = float(bbw)
    put("ta_OBV", talib.OBV(closes, volumes))
    put("ta_AD", talib.AD(highs, lows, closes, volumes))
    put("ta_ADOSC_3_10", talib.ADOSC(highs, lows, closes, volumes))
    put("ta_TYPPRICE", talib.TYPPRICE(highs, lows, closes))
    put("ta_WCLPRICE", talib.WCLPRICE(highs, lows, closes))
    put("open", opens)
    put("high", highs)
    put("low", lows)
    put("close", closes)
    put("volume", volumes)


def _families_present(indicators: Mapping[str, float]) -> list[str]:
    families: set[str] = set()
    for name in indicators:
        raw = name[3:] if name.startswith("ta_") else name
        family = raw.split("_", 1)[0].upper()
        if family:
            families.add(family)
    return sorted(families)


def build_full_talib_ta_payload(
    *,
    symbol: str,
    timeframe: str,
    candles: Sequence[Any],
    source_ohlcv_key: str | None = None,
    min_candles: int = DEFAULT_MIN_CANDLES,
) -> FullTalibTAResult:
    normalized = normalize_ohlcv_rows(candles)
    return _build_full_talib_ta_from_normalized(
        symbol=symbol,
        timeframe=timeframe,
        normalized=normalized,
        min_candles=min_candles,
    )


def _build_full_talib_ta_from_normalized(
    *,
    symbol: str,
    timeframe: str,
    normalized: Sequence[NormalizedCandle],
    min_candles: int,
) -> FullTalibTAResult:
    """Compute TA from the exact normalized sequence supplied by the caller."""

    result = FullTalibTAResult(
        symbol=symbol.upper(),
        timeframe=timeframe,
        candle_count=len(normalized),
        last_candle_ts_ms=normalized[-1].ts_ms if normalized else None,
    )
    try:
        import talib  # type: ignore
        from talib import abstract  # type: ignore
    except Exception as exc:  # noqa: BLE001
        result.classification = "BLOCKED_TALIB_IMPORT_FAILED"
        result.skipped_functions["talib_import"] = str(exc)
        return result

    functions = list(talib.get_functions())
    result.talib_function_count = len(functions)
    if len(normalized) < min_candles:
        result.classification = "BLOCKED_INSUFFICIENT_OHLCV_HISTORY"
        result.skipped_functions["all"] = f"need_at_least_{min_candles}_candles"
        return result

    opens = np.asarray([c.open for c in normalized], dtype="float64")
    highs = np.asarray([c.high for c in normalized], dtype="float64")
    lows = np.asarray([c.low for c in normalized], dtype="float64")
    closes = np.asarray([c.close for c in normalized], dtype="float64")
    volumes = np.asarray([c.volume for c in normalized], dtype="float64")
    periods = np.full(len(normalized), 14.0, dtype="float64")
    inputs = {
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "periods": periods,
    }

    indicators: dict[str, float] = {}
    for function_name in functions:
        try:
            function = abstract.Function(function_name)
            output = function(inputs)
        except Exception as exc:  # noqa: BLE001
            result.skipped_functions[function_name] = str(exc)
            continue
        output_names = list(getattr(function, "output_names", []) or ["real"])
        values: Iterable[Any]
        if len(output_names) == 1:
            values = (output,)
        elif isinstance(output, tuple | list):
            values = output
        else:
            values = (output,)
        added = 0
        for output_name, value in zip(output_names, values, strict=False):
            field_name = _field_name(function_name, str(output_name))
            if _put(
                indicators,
                field_name,
                value,
                source_row_count=len(normalized),
                rejected_outputs=result.rejected_outputs,
            ):
                added += 1
        if added:
            result.computed_functions.append(function_name)
        else:
            result.skipped_functions[function_name] = "no_finite_latest_output"

    try:
        _compute_aliases(
            indicators,
            opens=opens,
            highs=highs,
            lows=lows,
            closes=closes,
            volumes=volumes,
            rejected_outputs=result.rejected_outputs,
        )
    except Exception as exc:  # noqa: BLE001
        result.skipped_functions["legacy_aliases"] = str(exc)

    result.indicators = dict(sorted(indicators.items()))
    if result.indicator_count >= 150:
        result.classification = "V2_FULL_TALIB_TA_OK"
    elif result.indicator_count >= 100:
        result.classification = "V2_FULL_TALIB_TA_PARTIAL_OK"
    else:
        result.classification = "BLOCKED_INSUFFICIENT_TA_OUTPUT"
    return result


def build_full_talib_ta_closed_candidate(
    *,
    validated_window: ValidatedOHLCVClosedWindow,
) -> dict[str, Any]:
    """Build a nonconsumable TA candidate from one exact validated source read.

    The calculation always uses the exact final 89-row contiguous suffix.
    ``record_available_at`` is the point at which this in-memory derived record
    exists and is therefore the conservative maximum of the authenticated
    source availability and producer generation clocks.  It is deliberately
    distinct from ``publication_observed_at``: constructing a record does not
    claim a later Redis readback, immutable capture, or trainer admission.
    """

    if type(validated_window) is not ValidatedOHLCVClosedWindow:
        raise ValueError("full_talib_closed_candidate_exact_validated_window_required")
    if (
        validated_window.required_contiguous_lookback != FULL_TALIB_TA_REQUIRED_CONTIGUOUS_ROWS
        or validated_window.required_contiguous_window_satisfied is not True
        or validated_window.contiguous_suffix_count < FULL_TALIB_TA_REQUIRED_CONTIGUOUS_ROWS
    ):
        raise ValueError("full_talib_closed_candidate_89_row_suffix_unverified")

    selected = validated_window.rows[-FULL_TALIB_TA_REQUIRED_CONTIGUOUS_ROWS:]
    calculation_rows = [
        {
            "open_time": row.candle_open_time,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "volume": row.volume,
        }
        for row in selected
    ]
    normalized_calculation_rows = normalize_ohlcv_rows(calculation_rows)
    expected_normalized_rows = tuple(
        NormalizedCandle(
            ts_ms=row.candle_open_time,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in selected
    )
    if tuple(normalized_calculation_rows) != expected_normalized_rows:
        raise ValueError("full_talib_closed_candidate_normalized_source_identity_mismatch")

    result = _build_full_talib_ta_from_normalized(
        symbol=validated_window.symbol,
        timeframe=validated_window.timeframe,
        normalized=normalized_calculation_rows,
        min_candles=FULL_TALIB_TA_REQUIRED_CONTIGUOUS_ROWS,
    )

    generated = datetime.now(UTC)
    source_available_ms = validated_window.max_available_at
    if source_available_ms > int(generated.timestamp() * 1000):
        raise ValueError("full_talib_closed_candidate_source_available_after_generation")
    generated_at = generated.isoformat(timespec="microseconds").replace("+00:00", "Z")
    record_available_at = generated_at
    source_event_ms = validated_window.latest_economic_close_time
    candle_ids = [row.candle_id for row in selected]
    candle_ids_sha256 = hashlib.sha256(
        json.dumps(candle_ids, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    payload = result.to_payload(source_ohlcv_key=validated_window.source_key)
    payload.update(
        {
            "schema_version": FULL_TALIB_TA_CLOSED_CANDIDATE_SCHEMA_VERSION,
            "source_label": "V2_FULL_TALIB_TA_EXACT_CLOSED_CANDIDATE",
            "source_schema_version": validated_window.schema_version,
            "source_ohlcv_key": validated_window.source_key,
            "source_exact_payload_sha256": validated_window.exact_payload_sha256,
            "source_exact_payload_byte_count": validated_window.exact_payload_byte_count,
            "source_row_count": validated_window.row_count,
            "source_contiguous_suffix_count": validated_window.contiguous_suffix_count,
            "calculation_row_count": len(selected),
            "calculation_normalized_row_count": len(normalized_calculation_rows),
            "calculation_required_contiguous_rows": (FULL_TALIB_TA_REQUIRED_CONTIGUOUS_ROWS),
            "calculation_normalized_exact_source_identity": True,
            "calculation_normalized_first_ts_ms": normalized_calculation_rows[0].ts_ms,
            "calculation_normalized_last_ts_ms": normalized_calculation_rows[-1].ts_ms,
            "calculation_window_first_candle_id": selected[0].candle_id,
            "calculation_window_latest_candle_id": selected[-1].candle_id,
            "calculation_window_candle_ids_sha256": candle_ids_sha256,
            "latest_candle_id": selected[-1].candle_id,
            "latest_candle_raw_payload_hash": selected[-1].raw_payload_hash,
            "latest_candle_source_sequence_id": selected[-1].source_sequence_id,
            "latest_closed_candle_open_ts_ms": selected[-1].candle_open_time,
            "latest_closed_candle_close_ts_ms": source_event_ms,
            # Preserve the established consumer aliases, but bind every name
            # to the same authenticated final candle.  Consumers can therefore
            # reject omission or contradiction rather than guessing which
            # finality field a producer meant.
            "last_closed_candle_open_ts_ms": selected[-1].candle_open_time,
            "last_closed_candle_close_ts_ms": source_event_ms,
            "latest_closed_kline_close_time_ms": source_event_ms,
            "latest_candle_producer_event_time_ms": selected[-1].event_time,
            "latest_candle_ingested_at_ms": selected[-1].ingested_at,
            "latest_candle_available_at_ms": selected[-1].available_at,
            "source_economic_event_time_ms": source_event_ms,
            "source_producer_event_time_ms": (validated_window.latest_producer_event_time),
            "source_ingested_at_ms": validated_window.max_ingested_at,
            "source_available_at_ms": source_available_ms,
            "source_economic_event_time": _epoch_ms_iso(source_event_ms),
            "source_event_time": _epoch_ms_iso(source_event_ms),
            "source_producer_event_time": _epoch_ms_iso(
                validated_window.latest_producer_event_time
            ),
            "source_ingested_at": _epoch_ms_iso(validated_window.max_ingested_at),
            "source_available_at": _epoch_ms_iso(source_available_ms),
            "feature_cutoff": _epoch_ms_iso(source_event_ms),
            "generated_at": generated_at,
            "generated_utc": generated_at,
            "producer_generated_at": generated_at,
            "record_available_at": record_available_at,
            "available_at": record_available_at,
            "record_available_at_semantics": (
                "MAX_SOURCE_AVAILABLE_AT_PRODUCER_GENERATED_AT"
            ),
            "publication_observed_at": None,
            "closed_candles_only": True,
            "candle_closed_confirmed": True,
            "exact_source_schema_validated": True,
            "producer_finality_contract_validated": True,
            "redis_read_receipt_emitted": False,
            "immutable_cas_captured": False,
            "publication_committed": False,
            "consumer_eligible": False,
            "trainer_consumable": False,
            "trainer_admission_granted": False,
            "live_execution_authorized": False,
            "classification": (
                "V2_FULL_TALIB_TA_CLOSED_CANDIDATE_NONCONSUMABLE"
                if result.indicator_count
                else f"{result.classification}_CLOSED_CANDIDATE_NONCONSUMABLE"
            ),
            "computation_classification": result.classification,
        }
    )
    return payload
