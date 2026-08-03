"""Tests for paper-only major-move detection."""
from __future__ import annotations

from v2.backend.app.services.market_move_detection import (
    CandleInput,
    DetectionContext,
    detect_breakout_squeeze,
)


def _candle(
    *,
    index: int,
    close: float,
    volume: float = 1000.0,
    high_offset: float = 0.25,
    low_offset: float = 0.25,
    closed: bool = True,
    available_offset_ms: int = 1000,
) -> CandleInput:
    open_time = 1_800_000_000_000 + index * 60_000
    close_time = open_time + 59_000
    return CandleInput(
        symbol="BTCUSDT",
        timeframe="1m",
        open_time_ms=open_time,
        close_time_ms=close_time,
        available_at_ms=close_time + available_offset_ms,
        open=close - 0.1,
        high=close + high_offset,
        low=close - low_offset,
        close=close,
        volume=volume,
        closed=closed,
    )


def test_breakout_squeeze_allows_paper_candidate_from_closed_candles() -> None:
    candles = [
        _candle(index=0, close=100.0, volume=900.0),
        _candle(index=1, close=100.1, volume=950.0),
        _candle(index=2, close=100.0, volume=920.0),
        _candle(index=3, close=101.4, volume=1900.0, high_offset=1.1, low_offset=0.3),
    ]
    decision_time = candles[-1].available_at_ms

    signal = detect_breakout_squeeze(
        symbol="BTCUSDT",
        timeframe="1m",
        candles=candles,
        context=DetectionContext(
            decision_time_ms=decision_time,
            spread_bps=2.0,
            slippage_bps=2.0,
            orderbook_imbalance=0.18,
            liquidation_pressure=0.45,
            oi_change_pct=0.01,
            public_intel_score=0.60,
            correlated_regime_confirmed=True,
        ),
    )

    assert signal.paper_only is True
    assert signal.live_allowed is False
    assert signal.direction == "long"
    assert signal.expected_move_after_cost_bps > 0
    assert signal.evidence_score >= 0.62
    assert signal.reject_reasons == ()
    assert "closed_candle_directional_impulse" in signal.reasons
    assert "btc_eth_sol_correlated_regime" in signal.reasons


def test_breakout_squeeze_blocks_available_at_after_decision_time() -> None:
    candles = [
        _candle(index=0, close=100.0),
        _candle(index=1, close=100.1),
        _candle(index=2, close=100.0),
        _candle(index=3, close=101.4, volume=1900.0, high_offset=1.1, low_offset=0.3),
    ]
    decision_time = candles[-1].available_at_ms - 5_000

    signal = detect_breakout_squeeze(
        symbol="BTCUSDT",
        timeframe="1m",
        candles=candles,
        context=DetectionContext(decision_time_ms=decision_time, correlated_regime_confirmed=True),
    )

    assert signal.direction == "blocked"
    assert signal.paper_only is True
    assert signal.live_allowed is False
    assert "AVAILABLE_AT_AFTER_DECISION_TIME" in signal.reject_reasons


def test_btc_eth_sol_major_move_replay_creates_paper_candidate_when_evidence_present() -> None:
    rows = [
        _candle(index=0, close=100.0, volume=900.0),
        _candle(index=1, close=100.1, volume=950.0),
        _candle(index=2, close=100.0, volume=920.0),
        _candle(index=3, close=101.7, volume=2100.0, high_offset=1.2, low_offset=0.3),
    ]
    decision_time = rows[-1].available_at_ms

    signals = [
        detect_breakout_squeeze(
            symbol=symbol,
            timeframe="1m",
            candles=[candle.__class__(**{**candle.__dict__, "symbol": symbol}) for candle in rows],
            context=DetectionContext(
                decision_time_ms=decision_time,
                spread_bps=2.0,
                slippage_bps=2.0,
                orderbook_imbalance=0.18,
                liquidation_pressure=0.45,
                oi_change_pct=0.01,
                public_intel_score=0.60,
                correlated_regime_confirmed=True,
            ),
        )
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    ]

    assert {signal.symbol for signal in signals if not signal.reject_reasons} == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    assert all(signal.paper_only is True and signal.live_allowed is False for signal in signals)


def test_correlated_regime_detection_for_eth_sol() -> None:
    candles = [
        _candle(index=0, close=100.0, volume=900.0),
        _candle(index=1, close=100.1, volume=950.0),
        _candle(index=2, close=100.0, volume=920.0),
        _candle(index=3, close=101.5, volume=1900.0, high_offset=1.1, low_offset=0.3),
    ]
    decision_time = candles[-1].available_at_ms

    for symbol in ("ETHUSDT", "SOLUSDT"):
        signal = detect_breakout_squeeze(
            symbol=symbol,
            timeframe="1m",
            candles=[candle.__class__(**{**candle.__dict__, "symbol": symbol}) for candle in candles],
            context=DetectionContext(decision_time_ms=decision_time, correlated_regime_confirmed=True),
        )

        assert signal.regime == "correlated_breakout_squeeze"
        assert "btc_eth_sol_correlated_regime" in signal.reasons
