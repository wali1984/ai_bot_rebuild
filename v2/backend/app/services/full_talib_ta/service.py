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

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


FULL_TALIB_TA_SCHEMA_VERSION = "v2_full_talib_ta_payload_v1"
LIVE_GATE_BLOCKED = "blocked_human_only"
DEFAULT_MIN_CANDLES = 60

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
            "candle_count": self.candle_count,
            "last_candle_ts_ms": self.last_candle_ts_ms,
            "field_count": self.indicator_count,
            "indicator_count": self.indicator_count,
            "indicators": dict(sorted(self.indicators.items())),
            "families_present": _families_present(self.indicators),
            "classification": self.classification,
            "trainer_consumable": self.indicator_count >= 10,
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
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def normalize_ohlcv_rows(rows: Sequence[Any]) -> list[NormalizedCandle]:
    """Normalize Binance-list or dict OHLCV rows into chronological candles."""
    candles: list[NormalizedCandle] = []
    for row in rows:
        ts_ms: int | None
        o: float | None
        h: float | None
        l: float | None
        c: float | None
        v: float | None
        if isinstance(row, Mapping):
            ts_ms = _as_int(
                row.get("ts_ms")
                or row.get("timestamp")
                or row.get("open_time")
                or row.get("openTime")
                or row.get("time")
                or row.get("t")
            )
            o = _as_float(row.get("open") or row.get("o"))
            h = _as_float(row.get("high") or row.get("h"))
            l = _as_float(row.get("low") or row.get("l"))
            c = _as_float(row.get("close") or row.get("c"))
            v = _as_float(row.get("volume") or row.get("v"))
        elif isinstance(row, (list, tuple)) and len(row) >= 6:
            ts_ms = _as_int(row[0])
            o = _as_float(row[1])
            h = _as_float(row[2])
            l = _as_float(row[3])
            c = _as_float(row[4])
            v = _as_float(row[5])
        else:
            continue
        if None in (o, h, l, c, v):
            continue
        candles.append(
            NormalizedCandle(
                ts_ms=ts_ms,
                open=float(o),
                high=float(h),
                low=float(l),
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
            row.get("close_time")
            or row.get("closeTime")
            or row.get("close_ts_ms")
        )
        open_ts = _as_int(
            row.get("ts_ms")
            or row.get("timestamp")
            or row.get("open_time")
            or row.get("openTime")
            or row.get("time")
            or row.get("t")
        )
    elif isinstance(row, (list, tuple)):
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
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
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
        if isinstance(row, (list, tuple)) and row:
            open_ts = _as_int(row[0])
        elif isinstance(row, Mapping):
            open_ts = _as_int(
                row.get("ts_ms")
                or row.get("timestamp")
                or row.get("open_time")
                or row.get("openTime")
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


def _last_finite(value: Any) -> float | None:
    try:
        array = np.asarray(value, dtype="float64")
    except (TypeError, ValueError):
        return None
    if array.ndim == 0:
        f = float(array)
        return f if math.isfinite(f) else None
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return None
    f = float(finite[-1])
    return f if math.isfinite(f) else None


def _field_name(function_name: str, output_name: str) -> str:
    if output_name == "real":
        return f"ta_{function_name}"
    return f"ta_{function_name}_{output_name}"


def _put(indicators: dict[str, float], name: str, value: Any) -> None:
    f = _last_finite(value)
    if f is not None:
        indicators[name] = f


def _compute_aliases(
    indicators: dict[str, float],
    *,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
) -> None:
    """Add legacy/trainer aliases with explicit periods used by old consumers."""
    import talib  # type: ignore

    _put(indicators, "ta_RSI_14", talib.RSI(closes, timeperiod=14))
    _put(indicators, "rsi_14", talib.RSI(closes, timeperiod=14))
    macd, signal, hist = talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)
    _put(indicators, "ta_MACD_12_26_9_macd", macd)
    _put(indicators, "ta_MACD_12_26_9_signal", signal)
    _put(indicators, "ta_MACD_12_26_9_hist", hist)
    _put(indicators, "ta_MACDhist_12_26_9", hist)
    _put(indicators, "macd", macd)
    _put(indicators, "macd_signal", signal)
    _put(indicators, "macd_hist", hist)
    _put(indicators, "ta_ATR_14", talib.ATR(highs, lows, closes, timeperiod=14))
    _put(indicators, "atr_14", talib.ATR(highs, lows, closes, timeperiod=14))
    for period in (9, 12, 20, 21, 26, 50):
        _put(indicators, f"ta_EMA_{period}", talib.EMA(closes, timeperiod=period))
        _put(indicators, f"ema_{period}", talib.EMA(closes, timeperiod=period))
        _put(indicators, f"ta_SMA_{period}", talib.SMA(closes, timeperiod=period))
        _put(indicators, f"sma_{period}", talib.SMA(closes, timeperiod=period))
    upper, middle, lower = talib.BBANDS(
        closes,
        timeperiod=20,
        nbdevup=2,
        nbdevdn=2,
        matype=0,
    )
    _put(indicators, "ta_BBANDS_20_upper", upper)
    _put(indicators, "ta_BBANDS_20_middle", middle)
    _put(indicators, "ta_BBANDS_20_lower", lower)
    bbw = None
    upper_last = _last_finite(upper)
    lower_last = _last_finite(lower)
    middle_last = _last_finite(middle)
    if upper_last is not None and lower_last is not None and middle_last and middle_last > 0:
        bbw = (upper_last - lower_last) / middle_last
    if bbw is not None:
        indicators["ta_BB_width_pct"] = float(bbw)
        indicators["bb_width_pct"] = float(bbw)
    _put(indicators, "ta_OBV", talib.OBV(closes, volumes))
    _put(indicators, "ta_AD", talib.AD(highs, lows, closes, volumes))
    _put(indicators, "ta_ADOSC_3_10", talib.ADOSC(highs, lows, closes, volumes))
    _put(indicators, "ta_TYPPRICE", talib.TYPPRICE(highs, lows, closes))
    _put(indicators, "ta_WCLPRICE", talib.WCLPRICE(highs, lows, closes))
    if len(opens) and opens[-1] > 0:
        indicators["open"] = float(opens[-1])
    if len(highs):
        indicators["high"] = float(highs[-1])
    if len(lows):
        indicators["low"] = float(lows[-1])
    if len(closes):
        indicators["close"] = float(closes[-1])
    if len(volumes):
        indicators["volume"] = float(volumes[-1])


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
        if isinstance(output, (tuple, list)):
            values = output
        else:
            values = (output,)
        added = 0
        for output_name, value in zip(output_names, values):
            before = len(indicators)
            _put(indicators, _field_name(function_name, str(output_name)), value)
            if len(indicators) > before:
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
