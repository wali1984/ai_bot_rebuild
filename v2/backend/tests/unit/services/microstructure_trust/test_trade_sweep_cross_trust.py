from __future__ import annotations

from v2.backend.app.services.microstructure_trust.cross_venue_confirmation import evaluate_cross_venue_confirmation
from v2.backend.app.services.microstructure_trust.feed_quality import evaluate_feed_quality
from v2.backend.app.services.microstructure_trust.liquidation_sweep_detector import detect_liquidation_sweep
from v2.backend.app.services.microstructure_trust.orderbook_adversarial_features import compute_orderbook_adversarial_features
from v2.backend.app.services.microstructure_trust.trade_tape_confirmation import evaluate_trade_tape_confirmation
from v2.backend.app.services.microstructure_trust.trust_score import score_microstructure_trust


def test_trade_tape_distrusts_bullish_book_when_sells_dominate() -> None:
    tape = evaluate_trade_tape_confirmation(
        symbol="BTCUSDT",
        book_imbalance=0.7,
        trades=[
            {"price": 100.0, "quantity": 1.0, "side": "sell"},
            {"price": 99.8, "quantity": 2.0, "side": "sell"},
        ],
    )

    assert tape["trade_imbalance"] < 0
    assert tape["book_trade_divergence_score"] == 1.0
    assert tape["trade_tape_confirmation_score"] < 0.5


def test_sweep_cross_venue_and_trust_score_fail_closed_under_bad_feed() -> None:
    feed = evaluate_feed_quality(
        exchange="binance",
        symbol="BTCUSDT",
        sequence_gap_count=1,
        unrepaired_sequence_gap=True,
    )
    adversarial = compute_orderbook_adversarial_features(exchange="binance", symbol="BTCUSDT", snapshots=[])
    tape = evaluate_trade_tape_confirmation(symbol="BTCUSDT", trades=[])
    cross = evaluate_cross_venue_confirmation(
        symbol="BTCUSDT",
        binance={"best_bid": 100.0, "best_ask": 100.1, "depth_imbalance": 0.8},
        kucoin={"best_bid": 99.0, "best_ask": 99.1, "depth_imbalance": -0.8},
        trade_tape_confirmation_score=tape["trade_tape_confirmation_score"],
    )
    sweep = detect_liquidation_sweep(
        symbol="BTCUSDT",
        timeframe="1m",
        liquidation_context={"cascade_risk": 0.8, "distance_to_long_liq_bps": 50.0},
        long_short_ratio=2.5,
        funding_rate=0.001,
        open_interest_change_pct=0.05,
        depth_collapse_bps=5000.0,
        trade_tape_acceleration=60.0,
        trade_imbalance=0.0,
    )
    trust = score_microstructure_trust(
        symbol="BTCUSDT",
        timeframe="1m",
        feed_quality=feed,
        adversarial_features=adversarial,
        trade_tape=tape,
        cross_venue=cross,
        sweep_risk=sweep,
    )

    assert cross["imbalance_conflict"] is True
    assert sweep["sweep_risk"] >= 0.55
    assert trust["microstructure_action"] == "NO_TRADE"
    assert trust["eligible_for_a_grade"] is False
