from __future__ import annotations

from v2.backend.app.services.preemptive_edge_control.loss_probability import (
    evaluate_loss_probability,
)


def test_loss_probability_blocks_negative_expectancy() -> None:
    result = evaluate_loss_probability(
        {
            "pre_trade_expected_net_pnl_usd": -0.25,
            "bucket_pf_window": 1.2,
            "microstructure_trust_score": 0.8,
        }
    )

    assert result["pre_trade_loss_probability"] >= 0.80
    assert "BLOCK_NEGATIVE_EXPECTANCY" in result["loss_probability_reasons"]
    assert result["block"] is True


def test_loss_probability_penalizes_high_confidence_loss_cluster() -> None:
    result = evaluate_loss_probability(
        {
            "pre_trade_expected_net_pnl_usd": 1.0,
            "confidence_calibrated": 0.91,
            "recent_high_confidence_loss_rate": 0.60,
            "microstructure_trust_score": 0.8,
        }
    )

    assert result["pre_trade_loss_probability"] >= 0.80
    assert "BLOCK_HIGH_CONFIDENCE_LOSS_CLUSTER" in result["loss_probability_reasons"]


def test_loss_probability_penalizes_atr_stop_cluster() -> None:
    result = evaluate_loss_probability(
        {
            "pre_trade_expected_net_pnl_usd": 1.0,
            "recent_ATR_stop_risk": 0.80,
            "microstructure_trust_score": 0.8,
        }
    )

    assert result["pre_trade_loss_probability"] >= 0.80
    assert "BLOCK_ATR_STOP_CLUSTER" in result["loss_probability_reasons"]


def test_loss_probability_blocks_missing_cost() -> None:
    result = evaluate_loss_probability(
        {
            "confidence_calibrated": 0.62,
            "microstructure_trust_score": 0.8,
        }
    )

    assert result["pre_trade_loss_probability"] >= 0.80
    assert "BLOCK_MISSING_COST" in result["loss_probability_reasons"]


def test_loss_probability_allows_positive_clean_probation() -> None:
    result = evaluate_loss_probability(
        {
            "pre_trade_expected_net_pnl_usd": 0.75,
            "bucket_pf_window": 1.25,
            "bucket_expectancy_usd_window": 0.20,
            "recent_high_confidence_loss_rate": 0.0,
            "recent_ATR_stop_risk": 0.0,
            "microstructure_trust_score": 0.78,
        }
    )

    assert result["pre_trade_loss_probability"] < 0.80
    assert result["block"] is False
