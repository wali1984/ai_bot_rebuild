from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
}

REQUIRED_DECISION_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")


@dataclass(frozen=True)
class CanonicalCandle:
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
    source_sequence_id: str | None
    raw_payload_hash: str
    ohlcv: dict[str, float | int]
    is_backfilled: bool
    feature_eligible: bool

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Every producer of CanonicalCandle is backed by Binance USD-M
        # (fstream WebSocket or /fapi REST). Persist that product identity
        # so downstream PIT adapters never infer it from a generic label.
        data["venue"] = "binance_usdm"
        data["product_type"] = "USD-M"
        data["candle_id"] = canonical_candle_id(data)
        data["open_time"] = self.candle_open_time
        data["close_time"] = self.candle_close_time
        data["ts"] = self.candle_open_time
        data["closed_candle"] = self.is_closed
        data["candle_closed_confirmed"] = self.is_closed
        data.update(self.ohlcv)
        return data


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def canonical_candle_id(candle: Mapping[str, Any]) -> str:
    return stable_hash(
        {
            "exchange": candle.get("exchange"),
            "symbol": candle.get("symbol"),
            "timeframe": candle.get("timeframe"),
            "candle_open_time": candle.get("candle_open_time"),
            "candle_close_time": candle.get("candle_close_time"),
            "raw_payload_hash": candle.get("raw_payload_hash"),
        }
    )[:24]


def current_candle_key(exchange: str, symbol: str, timeframe: str) -> str:
    return f"v2:market:kline_current:{exchange}:{symbol}:{timeframe}"


def closed_candle_key(exchange: str, symbol: str, timeframe: str) -> str:
    return f"v2:market:ohlcv_closed:{exchange}:{symbol}:{timeframe}"


def legacy_closed_compat_key(exchange: str, symbol: str, timeframe: str) -> str:
    return f"v2:market:ohlcv:{exchange}:{symbol}:{timeframe}"


def parse_ms(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = int(value)
        return numeric * 1000 if abs(numeric) < 10_000_000_000 else numeric
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            numeric = int(float(text))
            return numeric * 1000 if abs(numeric) < 10_000_000_000 else numeric
        except ValueError:
            try:
                return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
            except ValueError:
                return None
    return None


def _float(value: Any) -> float:
    return float(value)


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _with_optional_ohlcv(base: dict[str, float | int], **values: Any) -> dict[str, float | int]:
    out = dict(base)
    for key, value in values.items():
        if value is not None:
            out[key] = value
    return out


def canonical_from_binance_wss(message: Mapping[str, Any], *, symbol: str, timeframe: str, ingested_at: int | None = None) -> CanonicalCandle:
    kline = message.get("k") if isinstance(message.get("k"), Mapping) else message
    event_time = parse_ms(message.get("E")) or parse_ms(kline.get("E")) or now_ms()
    open_time = parse_ms(kline.get("t"))
    close_time = parse_ms(kline.get("T"))
    if open_time is None or close_time is None:
        raise ValueError("binance_wss_kline_missing_open_or_close_time")
    received = int(ingested_at or now_ms())
    # Binance ``T`` is the inclusive final millisecond of the interval.  Even
    # when the producer sets ``x=true``, the candle is not locally observable
    # as final until the clock has advanced past ``T``.  Treating equality as
    # final creates a one-millisecond look-ahead window at exact boundaries.
    closed = bool(kline.get("x")) and close_time < received
    available_at = max(close_time + 1, event_time, received) if closed else received
    return CanonicalCandle(
        symbol=str(symbol).upper(),
        exchange="binance",
        timeframe=str(timeframe),
        candle_open_time=open_time,
        candle_close_time=close_time,
        event_time=event_time,
        ingested_at=received,
        available_at=available_at,
        is_closed=closed,
        source="binance_wss",
        source_sequence_id=str(message.get("E") or close_time),
        raw_payload_hash=stable_hash(message),
        ohlcv=_with_optional_ohlcv(
            {
                "open": _float(kline.get("o")),
                "high": _float(kline.get("h")),
                "low": _float(kline.get("l")),
                "close": _float(kline.get("c")),
                "volume": _float(kline.get("v")),
            },
            quote_volume=_optional_float(kline.get("q")),
            num_trades=_optional_int(kline.get("n")),
            taker_buy_base_vol=_optional_float(kline.get("V")),
            taker_buy_quote_vol=_optional_float(kline.get("Q")),
        ),
        is_backfilled=False,
        feature_eligible=closed,
    )


def canonical_from_binance_rest(row: list[Any] | tuple[Any, ...], *, symbol: str, timeframe: str, ingested_at: int | None = None) -> CanonicalCandle:
    if len(row) < 7:
        raise ValueError("binance_rest_kline_row_too_short")
    open_time = parse_ms(row[0])
    close_time = parse_ms(row[6])
    if open_time is None or close_time is None:
        raise ValueError("binance_rest_kline_missing_open_or_close_time")
    received = int(ingested_at or now_ms())
    # ``close_time`` is inclusive.  Finality is therefore end-exclusive:
    # ``close_time + 1 <= received`` (equivalently ``close_time < received``).
    closed = close_time < received
    return CanonicalCandle(
        symbol=str(symbol).upper(),
        exchange="binance",
        timeframe=str(timeframe),
        candle_open_time=open_time,
        candle_close_time=close_time,
        event_time=close_time,
        ingested_at=received,
        available_at=max(close_time + 1, received) if closed else received,
        is_closed=closed,
        source="binance_rest",
        source_sequence_id=str(close_time),
        raw_payload_hash=stable_hash(list(row)),
        ohlcv=_with_optional_ohlcv(
            {
                "open": _float(row[1]),
                "high": _float(row[2]),
                "low": _float(row[3]),
                "close": _float(row[4]),
                "volume": _float(row[5]),
            },
            quote_volume=_optional_float(row[7] if len(row) > 7 else None),
            num_trades=_optional_int(row[8] if len(row) > 8 else None),
            taker_buy_base_vol=_optional_float(row[9] if len(row) > 9 else None),
            taker_buy_quote_vol=_optional_float(row[10] if len(row) > 10 else None),
        ),
        is_backfilled=True,
        feature_eligible=closed,
    )


def storage_records_for_candle(candle: CanonicalCandle) -> list[tuple[str, dict[str, Any]]]:
    payload = candle.to_dict()
    if candle.is_closed:
        return [(closed_candle_key(candle.exchange, candle.symbol, candle.timeframe), payload)]
    return [(current_candle_key(candle.exchange, candle.symbol, candle.timeframe), payload)]


def append_closed_candle(existing: Any, candle: Mapping[str, Any], *, limit: int = 1500) -> list[dict[str, Any]]:
    rows = list(existing) if isinstance(existing, list) else []
    candle_id = candle.get("candle_id") or canonical_candle_id(candle)
    candle_open_time = parse_ms(candle.get("candle_open_time") or candle.get("open_time"))
    rows = [
        dict(row)
        for row in rows
        if isinstance(row, Mapping)
        and row.get("candle_id") != candle_id
        and parse_ms(row.get("candle_open_time") or row.get("open_time")) != candle_open_time
    ]
    rows.append(dict(candle))
    rows.sort(key=lambda row: int(parse_ms(row.get("candle_open_time") or row.get("open_time") or 0) or 0))
    return rows[-limit:]


def aggregate_closed_candles(
    candles: Any,
    *,
    symbol: str,
    source_timeframe: str,
    target_timeframe: str,
    now_ms_value: int | None = None,
) -> list[dict[str, Any]]:
    """Build higher-timeframe closed candles from complete lower-timeframe slots."""

    source_seconds = TIMEFRAME_SECONDS.get(str(source_timeframe))
    target_seconds = TIMEFRAME_SECONDS.get(str(target_timeframe))
    if (
        source_seconds is None
        or target_seconds is None
        or source_seconds <= 0
        or target_seconds <= source_seconds
        or target_seconds % source_seconds != 0
    ):
        return []
    if not isinstance(candles, list):
        return []

    current_ms = int(now_ms_value if now_ms_value is not None else now_ms())
    source_ms = source_seconds * 1000
    target_ms = target_seconds * 1000
    by_open: dict[int, dict[str, Any]] = {}
    for raw in candles:
        if not isinstance(raw, Mapping):
            continue
        if not (raw.get("is_closed") is True or raw.get("closed_candle") is True or raw.get("candle_closed_confirmed") is True):
            continue
        open_ms = parse_ms(raw.get("candle_open_time") or raw.get("open_time"))
        close_ms = parse_ms(raw.get("candle_close_time") or raw.get("close_time"))
        if open_ms is None or close_ms is None or close_ms >= current_ms:
            continue
        by_open[open_ms] = dict(raw)

    aggregates: list[dict[str, Any]] = []
    target_opens = sorted({(open_ms // target_ms) * target_ms for open_ms in by_open})
    for target_open in target_opens:
        target_close = target_open + target_ms - 1
        if target_close >= current_ms:
            continue
        expected_opens = list(range(target_open, target_open + target_ms, source_ms))
        source_rows = [by_open.get(open_ms) for open_ms in expected_opens]
        if any(row is None for row in source_rows):
            continue
        complete_rows = [row for row in source_rows if row is not None]
        first = complete_rows[0]
        last = complete_rows[-1]
        try:
            open_price = _float(first.get("open") if first.get("open") is not None else _ohlcv_value(first, "open"))
            close_price = _float(last.get("close") if last.get("close") is not None else _ohlcv_value(last, "close"))
            high_price = max(_float(row.get("high") if row.get("high") is not None else _ohlcv_value(row, "high")) for row in complete_rows)
            low_price = min(_float(row.get("low") if row.get("low") is not None else _ohlcv_value(row, "low")) for row in complete_rows)
            volume = sum(_float(row.get("volume") if row.get("volume") is not None else _ohlcv_value(row, "volume")) for row in complete_rows)
        except (TypeError, ValueError):
            continue

        optional_sums: dict[str, float | int] = {}
        for field in ("quote_volume", "taker_buy_base_vol", "taker_buy_quote_vol"):
            values = [_optional_float(row.get(field) if row.get(field) is not None else _ohlcv_value(row, field)) for row in complete_rows]
            if all(value is not None for value in values):
                optional_sums[field] = float(sum(value for value in values if value is not None))
        trade_values = [_optional_int(row.get("num_trades") if row.get("num_trades") is not None else _ohlcv_value(row, "num_trades")) for row in complete_rows]
        if all(value is not None for value in trade_values):
            optional_sums["num_trades"] = int(sum(value for value in trade_values if value is not None))

        event_time = max(
            parse_ms(row.get("event_time")) or parse_ms(row.get("candle_close_time") or row.get("close_time")) or target_close
            for row in complete_rows
        )
        available_at = max(
            parse_ms(row.get("available_at")) or parse_ms(row.get("candle_close_time") or row.get("close_time")) or target_close
            for row in complete_rows
        )
        source_hash_material = {
            "source_timeframe": source_timeframe,
            "target_timeframe": target_timeframe,
            "target_open": target_open,
            "target_close": target_close,
            "source_candle_ids": [
                row.get("candle_id") or canonical_candle_id(row)
                for row in complete_rows
            ],
            "source_hashes": [
                row.get("raw_payload_hash")
                for row in complete_rows
                if row.get("raw_payload_hash")
            ],
        }
        candle = CanonicalCandle(
            symbol=str(symbol).upper(),
            exchange="binance",
            timeframe=str(target_timeframe),
            candle_open_time=target_open,
            candle_close_time=target_close,
            event_time=event_time,
            ingested_at=max(available_at, event_time),
            available_at=available_at,
            is_closed=True,
            source=f"v2_closed_candle_resampler:{source_timeframe}",
            source_sequence_id=stable_hash(source_hash_material)[:24],
            raw_payload_hash=stable_hash(source_hash_material),
            ohlcv=_with_optional_ohlcv(
                {
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "close": close_price,
                    "volume": volume,
                },
                **optional_sums,
            ),
            is_backfilled=False,
            feature_eligible=True,
        )
        payload = candle.to_dict()
        payload["resampled_from_timeframe"] = str(source_timeframe)
        payload["resampled_source_candle_count"] = len(complete_rows)
        aggregates.append(payload)
    return aggregates


def _ohlcv_value(row: Mapping[str, Any], field: str) -> Any:
    ohlcv = row.get("ohlcv") if isinstance(row.get("ohlcv"), Mapping) else {}
    return ohlcv.get(field)


def latest_closed_candle_at_or_before(candles: Any, decision_time: Any) -> dict[str, Any] | None:
    decision_ms = parse_ms(decision_time)
    if decision_ms is None or not isinstance(candles, list):
        return None
    selected: dict[str, Any] | None = None
    for raw in candles:
        if not isinstance(raw, Mapping):
            continue
        close_time = parse_ms(raw.get("candle_close_time") or raw.get("close_time"))
        is_closed = raw.get("is_closed") is True or raw.get("closed_candle") is True or raw.get("candle_closed_confirmed") is True
        if close_time is None or not is_closed:
            continue
        if close_time < decision_ms:
            selected = dict(raw)
    return selected


def _latest_available_closed_candle_at_or_before(
    candles: Any,
    decision_time: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    decision_ms = parse_ms(decision_time)
    if decision_ms is None:
        return None, "DECISION_TIME_MISSING"
    if not isinstance(candles, list):
        return None, "MISSING_CLOSED_CANDLE"
    selected: dict[str, Any] | None = None
    saw_closed_candidate = False
    saw_future_available = False
    saw_missing_available = False
    for raw in candles:
        if not isinstance(raw, Mapping):
            continue
        close_time = parse_ms(raw.get("candle_close_time") or raw.get("close_time"))
        is_closed = raw.get("is_closed") is True or raw.get("closed_candle") is True or raw.get("candle_closed_confirmed") is True
        if close_time is None or not is_closed or close_time >= decision_ms:
            continue
        saw_closed_candidate = True
        available_at = parse_ms(raw.get("available_at"))
        if available_at is None:
            saw_missing_available = True
            continue
        if available_at <= decision_ms:
            selected = dict(raw)
        else:
            saw_future_available = True
    if selected is not None:
        return selected, None
    if saw_future_available:
        return None, "AVAILABLE_AT_AFTER_DECISION"
    if saw_missing_available:
        return None, "AVAILABLE_AT_MISSING"
    if saw_closed_candidate:
        return None, "AVAILABLE_AT_MISSING"
    return None, "MISSING_CLOSED_CANDLE"


def build_multi_timeframe_decision_snapshot(
    *,
    symbol: str,
    decision_time: Any,
    candles_by_timeframe: Mapping[str, Any],
    required_timeframes: Iterable[str] = REQUIRED_DECISION_TIMEFRAMES,
) -> dict[str, Any]:
    parsed_decision_ms = parse_ms(decision_time)
    decision_ms = parsed_decision_ms or now_ms()
    selected: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    reject_reasons: list[str] = []
    if parsed_decision_ms is None:
        reject_reasons.append("DECISION_TIME_MISSING")
    for timeframe in required_timeframes:
        candle, unavailable_reason = _latest_available_closed_candle_at_or_before(
            candles_by_timeframe.get(timeframe),
            decision_ms,
        )
        if candle is None:
            missing.append(timeframe)
            if unavailable_reason == "AVAILABLE_AT_AFTER_DECISION":
                reject_reasons.append(f"AVAILABLE_AT_AFTER_DECISION_{timeframe}")
            elif unavailable_reason == "AVAILABLE_AT_MISSING":
                reject_reasons.append(f"AVAILABLE_AT_MISSING_{timeframe}")
            else:
                reject_reasons.append(f"MISSING_CLOSED_CANDLE_{timeframe}")
            continue
        available_at = parse_ms(candle.get("available_at"))
        close_time = parse_ms(candle.get("candle_close_time") or candle.get("close_time"))
        if available_at is None:
            reject_reasons.append(f"AVAILABLE_AT_MISSING_{timeframe}")
        elif available_at > decision_ms:
            reject_reasons.append(f"AVAILABLE_AT_AFTER_DECISION_{timeframe}")
        if close_time is None:
            reject_reasons.append(f"CANDLE_CLOSE_TIME_MISSING_{timeframe}")
        elif close_time >= decision_ms:
            reject_reasons.append(f"FUTURE_CANDLE_{timeframe}")
        selected[timeframe] = candle
    close_times = [parse_ms(row.get("candle_close_time") or row.get("close_time")) for row in selected.values()]
    feature_cutoff = min([value for value in close_times if value is not None], default=None)
    snapshot_body = {
        "symbol": str(symbol).upper(),
        "decision_time": decision_ms,
        "feature_cutoff": feature_cutoff,
        "selected_candles": {
            timeframe: {
                "candle_id": row.get("candle_id") or canonical_candle_id(row),
                "candle_open_time": row.get("candle_open_time") or row.get("open_time"),
                "candle_close_time": row.get("candle_close_time") or row.get("close_time"),
                "available_at": row.get("available_at"),
                "is_closed": row.get("is_closed") is True or row.get("closed_candle") is True,
                "event_time": row.get("event_time"),
                "source": row.get("source"),
                "raw_payload_hash": row.get("raw_payload_hash"),
            }
            for timeframe, row in selected.items()
        },
        "missing_timeframes": missing,
        "gap_flags": sorted(set(reject_reasons)),
    }
    snapshot_id = stable_hash(snapshot_body)[:24]
    return {
        "decision_id": f"decision_{snapshot_id}",
        "mtf_snapshot_id": f"mtf_{snapshot_id}",
        **snapshot_body,
        "valid": not reject_reasons,
        "reject_reasons": sorted(set(reject_reasons)),
        "all_tf_candle_timestamps": [
            row.get("candle_close_time") or row.get("close_time") for row in selected.values()
        ],
        "all_source_event_times": [row.get("event_time") for row in selected.values() if row.get("event_time") is not None],
        "source_hashes": [row.get("raw_payload_hash") for row in selected.values() if row.get("raw_payload_hash")],
    }
