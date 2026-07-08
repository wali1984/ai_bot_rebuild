from __future__ import annotations

from datetime import datetime, timedelta, timezone

from v2.backend.app.services.market_structure import (
    compute_cvd_features,
    compute_fvg,
    compute_liquidity_zones,
    compute_trade_tape_features,
    compute_volume_profile,
    compute_vwap_features,
)
from v2.backend.app.services.market_structure.structure_breaks import compute_structure


BASE = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)


def _candle(i: int, *, open_: float, high: float, low: float, close: float, volume: float = 100.0) -> dict:
    ts = BASE + timedelta(minutes=i)
    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "taker_buy_base_vol": volume * 0.55,
        "event_time": ts.isoformat(),
        "available_at": ts.isoformat(),
        "candle_closed_confirmed": True,
    }


def test_bullish_fvg_detection_partial_fill_and_timestamp_lineage() -> None:
    candles = [
        _candle(0, open_=95, high=100, low=90, close=97),
        _candle(1, open_=97, high=103, low=96, close=101),
        _candle(2, open_=106, high=112, low=105, close=110),
        _candle(3, open_=109, high=111, low=103, close=108),
    ]

    payload = compute_fvg(
        symbol="BTCUSDT",
        timeframe="1m",
        candles=candles,
        price=108.0,
        decision_time=BASE + timedelta(minutes=3),
    )

    assert payload["bullish_fvg_present"] is True
    assert payload["fvg_retest_confirmed"] is True
    assert payload["fvg_fill_percent"] == 40.0
    assert payload["available_at"] == candles[-1]["available_at"]
    assert payload["decision_time"] == (BASE + timedelta(minutes=3)).isoformat()
    assert payload["fvg_alone_can_approve_trade"] is False
    assert payload["trainer_consumes"] is True


def test_bearish_fvg_detection_and_full_invalidation() -> None:
    candles = [
        _candle(0, open_=105, high=110, low=100, close=104),
        _candle(1, open_=104, high=106, low=98, close=100),
        _candle(2, open_=94, high=95, low=90, close=92),
        _candle(3, open_=93, high=101, low=91, close=99),
    ]

    payload = compute_fvg(
        symbol="ETHUSDT",
        timeframe="1m",
        candles=candles,
        price=99.0,
        decision_time=BASE + timedelta(minutes=3),
    )

    assert payload["active_fvg_count"] == 0
    assert payload["fvg_kind"] == "bearish"
    assert payload["fvg_invalidated"] is True
    assert payload["fvg_fill_percent"] == 100.0


def test_fvg_excludes_future_rows_from_decision() -> None:
    future = _candle(4, open_=108, high=109, low=99, close=100)
    future["available_at"] = (BASE + timedelta(minutes=10)).isoformat()
    payload = compute_fvg(
        symbol="SOLUSDT",
        timeframe="1m",
        candles=[
            _candle(0, open_=95, high=100, low=90, close=97),
            _candle(1, open_=97, high=103, low=96, close=101),
            _candle(2, open_=106, high=112, low=105, close=110),
            future,
        ],
        price=110.0,
        decision_time=BASE + timedelta(minutes=3),
    )

    assert payload["bullish_fvg_present"] is True
    assert payload["fvg_invalidated"] is False
    assert payload["timestamp_lineage"]["excluded_future_rows"] == 1


def test_liquidity_vwap_volume_cvd_and_tape_features_are_timestamp_safe() -> None:
    candles = [
        _candle(i, open_=100 + i, high=102 + i, low=99 + i, close=101 + i, volume=100 + i * 10)
        for i in range(30)
    ]
    decision_time = BASE + timedelta(minutes=29)

    liquidity = compute_liquidity_zones(
        symbol="BTCUSDT",
        timeframe="1m",
        candles=candles,
        price=120.0,
        orderbook_features={"ask_wall_price": 123.0, "bid_wall_price": 117.0},
        liquidation_levels={"nearest_liquidation_level_above": 124.0},
        trade_tape={"trade_imbalance": 0.8, "sweep_prints": 2},
        decision_time=decision_time,
    )
    vwap = compute_vwap_features(
        symbol="BTCUSDT",
        timeframe="1m",
        candles=candles,
        price=120.0,
        decision_time=decision_time,
    )
    profile = compute_volume_profile(
        symbol="BTCUSDT",
        timeframe="1m",
        candles=candles,
        price=120.0,
        decision_time=decision_time,
    )
    cvd = compute_cvd_features(
        symbol="BTCUSDT",
        timeframe="1m",
        candles=candles,
        price=120.0,
        decision_time=decision_time,
    )
    tape = compute_trade_tape_features(
        symbol="BTCUSDT",
        timeframe="1m",
        trades=[
            {
                "price": 120.0,
                "quantity": 2.0,
                "side": "buy",
                "event_time": decision_time.isoformat(),
                "available_at": decision_time.isoformat(),
            },
            {
                "price": 119.5,
                "quantity": 1.0,
                "side": "sell",
                "event_time": decision_time.isoformat(),
                "available_at": decision_time.isoformat(),
            },
        ],
        decision_time=decision_time,
    )

    assert liquidity["nearest_liquidity_above"] is not None
    assert liquidity["sweep_risk_short_side"] is not None
    assert vwap["session_vwap"] is not None
    assert profile["volume_profile_poc"] is not None
    assert cvd["cvd"] is not None
    assert tape["trade_imbalance"] > 0
    assert all(
        payload["timestamp_lineage"]["excluded_future_rows"] == 0
        for payload in (liquidity, vwap, profile, cvd, tape)
    )


def test_structure_breaks_publish_decision_consumption_fields() -> None:
    candles = [
        _candle(i, open_=100 + i * 0.2, high=101 + i * 0.5, low=99 + i * 0.1, close=100 + i * 0.4)
        for i in range(20)
    ]
    payload = compute_structure(
        symbol="BTCUSDT",
        timeframe="1m",
        candles=candles,
        price=108.0,
        decision_time=BASE + timedelta(minutes=19),
    )

    assert "bos_direction_code" in payload
    assert "premium_discount_zone_code" in payload
    assert payload["paper_consumes"] is True
    assert payload["live_dry_run_consumes"] is True
