from __future__ import annotations

from typing import Any

from app.services.market_state_integrity.canonical_candles import (
    REQUIRED_DECISION_TIMEFRAMES,
    append_closed_candle,
    build_multi_timeframe_decision_snapshot,
    canonical_from_binance_rest,
    canonical_from_binance_wss,
    closed_candle_key,
    current_candle_key,
    storage_records_for_candle,
)

BASE_MS = 1_700_000_000_000
DECISION_MS = BASE_MS + 14_400_000 + 1_000
TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def wss_message(*, timeframe: str = "1m", closed: bool, open_time: int = BASE_MS) -> dict[str, Any]:
    close_time = open_time + TF_MS[timeframe]
    return {
        "E": close_time + 250,
        "k": {
            "s": "BTCUSDT",
            "i": timeframe,
            "t": open_time,
            "T": close_time,
            "o": "100.0",
            "h": "101.0",
            "l": "99.0",
            "c": "100.5",
            "v": "12.0",
            "q": "1206.0",
            "n": 10,
            "V": "6.0",
            "Q": "603.0",
            "B": "0",
            "x": closed,
        },
    }


def rest_row(*, timeframe: str, open_time: int) -> list[Any]:
    close_time = open_time + TF_MS[timeframe]
    return [open_time, "100", "101", "99", "100.5", "12", close_time, "1206", 10, "6", "603", "0"]


def closed_payload(timeframe: str, *, available_offset_ms: int = 0, closed: bool = True) -> dict[str, Any]:
    open_time = DECISION_MS - 1_000 - TF_MS[timeframe]
    candle = canonical_from_binance_rest(
        rest_row(timeframe=timeframe, open_time=open_time),
        symbol="BTCUSDT",
        timeframe=timeframe,
        ingested_at=DECISION_MS - 500 + available_offset_ms,
    ).to_dict()
    candle["is_closed"] = closed
    candle["closed_candle"] = closed
    candle["candle_closed_confirmed"] = closed
    candle["feature_eligible"] = closed
    return candle


def candles_by_timeframe(**overrides: Any) -> dict[str, list[dict[str, Any]]]:
    out = {timeframe: [closed_payload(timeframe)] for timeframe in REQUIRED_DECISION_TIMEFRAMES}
    for timeframe, value in overrides.items():
        out[timeframe] = value
    return out


def test_wss_open_candle_goes_only_to_current_key_never_closed_key() -> None:
    candle = canonical_from_binance_wss(wss_message(closed=False), symbol="BTCUSDT", timeframe="1m", ingested_at=BASE_MS + 1_000)

    records = storage_records_for_candle(candle)

    assert records == [(current_candle_key("binance", "BTCUSDT", "1m"), candle.to_dict())]
    assert records[0][0] != closed_candle_key("binance", "BTCUSDT", "1m")
    assert candle.is_closed is False
    assert candle.feature_eligible is False


def test_wss_closed_candle_goes_to_closed_key_with_finality_metadata() -> None:
    candle = canonical_from_binance_wss(wss_message(closed=True), symbol="BTCUSDT", timeframe="1m", ingested_at=BASE_MS + 61_000)

    records = storage_records_for_candle(candle)
    payload = records[0][1]

    assert records[0][0] == closed_candle_key("binance", "BTCUSDT", "1m")
    assert payload["is_closed"] is True
    assert payload["closed_candle"] is True
    assert payload["candle_closed_confirmed"] is True
    assert payload["available_at"] >= payload["event_time"]
    assert payload["raw_payload_hash"]
    assert payload["quote_volume"] == 1206.0
    assert payload["num_trades"] == 10
    assert payload["taker_buy_base_vol"] == 6.0
    assert payload["taker_buy_quote_vol"] == 603.0
    assert payload["ohlcv"]["quote_volume"] == 1206.0
    assert payload["ohlcv"]["num_trades"] == 10


def test_rest_current_candle_is_not_feature_eligible() -> None:
    candle = canonical_from_binance_rest(
        rest_row(timeframe="1m", open_time=BASE_MS),
        symbol="BTCUSDT",
        timeframe="1m",
        ingested_at=BASE_MS + 10_000,
    )

    assert candle.is_closed is False
    assert candle.feature_eligible is False
    assert storage_records_for_candle(candle)[0][0] == current_candle_key("binance", "BTCUSDT", "1m")


def test_rest_candle_preserves_binance_trade_and_taker_fields() -> None:
    candle = canonical_from_binance_rest(
        rest_row(timeframe="1m", open_time=BASE_MS),
        symbol="BTCUSDT",
        timeframe="1m",
        ingested_at=BASE_MS + 61_000,
    )

    payload = candle.to_dict()

    assert payload["quote_volume"] == 1206.0
    assert payload["num_trades"] == 10
    assert payload["taker_buy_base_vol"] == 6.0
    assert payload["taker_buy_quote_vol"] == 603.0
    assert payload["ohlcv"]["quote_volume"] == 1206.0
    assert payload["ohlcv"]["num_trades"] == 10


def test_append_closed_candle_deduplicates_by_open_time() -> None:
    first = closed_payload("1m")
    replacement = dict(first, close=101.0)

    rows = append_closed_candle([first], replacement)

    assert len(rows) == 1
    assert rows[0]["close"] == 101.0


def test_mtf_snapshot_selects_only_closed_candles_and_shared_cutoff() -> None:
    snapshot = build_multi_timeframe_decision_snapshot(
        symbol="BTCUSDT",
        decision_time=DECISION_MS,
        candles_by_timeframe=candles_by_timeframe(),
    )

    assert snapshot["valid"] is True
    assert snapshot["mtf_snapshot_id"].startswith("mtf_")
    assert set(snapshot["selected_candles"]) == set(REQUIRED_DECISION_TIMEFRAMES)
    assert snapshot["feature_cutoff"] == min(snapshot["all_tf_candle_timestamps"])


def test_mtf_snapshot_blocks_unfinished_higher_timeframe() -> None:
    snapshot = build_multi_timeframe_decision_snapshot(
        symbol="BTCUSDT",
        decision_time=DECISION_MS,
        candles_by_timeframe=candles_by_timeframe(**{"15m": [closed_payload("15m", closed=False)]}),
    )

    assert snapshot["valid"] is False
    assert "MISSING_CLOSED_CANDLE_15m" in snapshot["reject_reasons"]


def test_mtf_snapshot_blocks_available_at_after_decision() -> None:
    snapshot = build_multi_timeframe_decision_snapshot(
        symbol="BTCUSDT",
        decision_time=DECISION_MS,
        candles_by_timeframe=candles_by_timeframe(**{"1m": [closed_payload("1m", available_offset_ms=10_000)]}),
    )

    assert snapshot["valid"] is False
    assert "AVAILABLE_AT_AFTER_DECISION_1m" in snapshot["reject_reasons"]
