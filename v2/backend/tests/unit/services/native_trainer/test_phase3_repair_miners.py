from __future__ import annotations

from v2.backend.app.services.native_trainer.high_confidence_loss_miner import (
    mine_high_confidence_losses,
)
from v2.backend.app.services.native_trainer.major_move_false_negative_miner import (
    mine_major_move_false_negatives,
)
from v2.backend.app.services.native_trainer.regime_miscalibration_miner import (
    mine_regime_miscalibration,
)


def _row(
    prediction_id: str,
    *,
    symbol: str = "BTCUSDT",
    side: str = "long",
    classification: str = "correct_trade",
    realized: float = 20.0,
    confidence: float = 0.80,
    strategy: str = "breakout",
    regime: str = "TREND",
    timeframe: str = "1m",
    exit_reason: str = "take_profit",
) -> dict[str, object]:
    return {
        "prediction_id": prediction_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "selected_action": side,
        "counterfactual_side": side,
        "strategy_id": strategy,
        "market_regime": regime,
        "confidence_calibrated": confidence,
        "expected_move_after_cost_bps": 24.0,
        "realized_after_cost_return_bps": realized,
        "classification": classification,
        "exit_reason": exit_reason,
        "feature_cutoff": "2026-06-11T12:04:00Z",
        "available_at": "2026-06-11T12:04:59Z",
        "decision_time": "2026-06-11T12:05:00Z",
        "candle_closed_confirmed": True,
        "paper_fill_gate_block_reasons": [],
        "risk_reason": "allow",
        "orchestrator_reason": "allow",
    }


def test_high_confidence_loss_miner_recommends_same_bucket_quarantine() -> None:
    rows = [
        _row("loss_1", classification="false_positive", realized=-18.0, exit_reason="TIER_1_ATR_VOLATILITY_STOP"),
        _row("loss_2", classification="false_positive", realized=-11.0, exit_reason="TIER_1_ATR_VOLATILITY_STOP"),
        _row("win_1", classification="correct_trade", realized=22.0),
    ]

    status = mine_high_confidence_losses(rows, min_confidence=0.55, quarantine_min_count=2)

    assert status["high_confidence_wrong_count"] == 2
    assert status["atr_stop_high_confidence_loss_count"] == 2
    assert status["quarantined_buckets"] == [
        {
            "bucket_key": "BTCUSDT|1m|breakout|TREND|long",
            "high_confidence_loss_count": 2,
            "quarantine_recommended": True,
            "quarantine_reason": "HIGH_CONFIDENCE_LOSS_CLUSTER",
        }
    ]
    assert status["pit_trust_violation_counts"] == {}
    assert status["no_live_mutation"] is True
    assert status["runtime_thresholds_changed"] is False


def test_high_confidence_loss_miner_flags_future_leak_rows() -> None:
    row = _row("future_leak", classification="false_positive", realized=-7.0)
    row["available_at"] = "2026-06-11T12:05:01Z"

    status = mine_high_confidence_losses([row])

    assert status["pit_trust_violation_counts"]["AVAILABLE_AT_AFTER_DECISION_TIME"] == 1


def test_major_move_false_negative_miner_classifies_btc_eth_sol_paths() -> None:
    rows = [
        _row("btc_fn", symbol="BTCUSDT", classification="false_negative", realized=32.0, side="long"),
        _row("eth_fn", symbol="ETHUSDT", classification="false_negative", realized=21.0, side="short"),
        _row("sol_small", symbol="SOLUSDT", classification="false_negative", realized=4.0, side="long"),
        _row("xrp_fn", symbol="XRPUSDT", classification="false_negative", realized=40.0, side="long"),
    ]

    status = mine_major_move_false_negatives(rows, min_after_cost_bps=15.0)

    assert status["major_move_false_negative_count"] == 2
    assert status["by_symbol"] == {"BTCUSDT": 1, "ETHUSDT": 1}
    assert status["mandatory_major_classified"] == {
        "BTCUSDT": True,
        "ETHUSDT": True,
        "SOLUSDT": False,
    }
    assert status["long_and_short_have_viable_path"] is True
    assert status["no_live_mutation"] is True


def test_regime_miscalibration_miner_flags_negative_buckets_without_runtime_change() -> None:
    rows = [
        _row("trend_loss_1", realized=-10.0, side="long", regime="TREND"),
        _row("trend_loss_2", realized=-6.0, side="long", regime="TREND"),
        _row("range_win_1", realized=18.0, side="short", regime="RANGE", strategy="range_scalp"),
        _row("range_win_2", realized=10.0, side="short", regime="RANGE", strategy="range_scalp"),
    ]

    status = mine_regime_miscalibration(rows, min_bucket_samples=2)

    negative_buckets = {row["bucket"] for row in status["negative_buckets"]}
    assert "TREND" in negative_buckets
    assert "long" in negative_buckets
    assert status["long_viable"] is False
    assert status["short_viable"] is True
    assert status["no_live_mutation"] is True
    assert status["runtime_thresholds_changed"] is False
