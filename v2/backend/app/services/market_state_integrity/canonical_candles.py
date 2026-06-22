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
    closed = bool(kline.get("x"))
    received = int(ingested_at or now_ms())
    available_at = max(close_time, event_time, received) if closed else received
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
    closed = close_time <= received
    return CanonicalCandle(
        symbol=str(symbol).upper(),
        exchange="binance",
        timeframe=str(timeframe),
        candle_open_time=open_time,
        candle_close_time=close_time,
        event_time=close_time,
        ingested_at=received,
        available_at=max(close_time, received) if closed else received,
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
        if close_time <= decision_ms:
            selected = dict(raw)
    return selected


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
        candle = latest_closed_candle_at_or_before(candles_by_timeframe.get(timeframe), decision_ms)
        if candle is None:
            missing.append(timeframe)
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
        elif close_time > decision_ms:
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
