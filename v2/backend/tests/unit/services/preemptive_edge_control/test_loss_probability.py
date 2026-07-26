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


def test_loss_probability_preserves_zero_expected_edge_as_non_positive() -> None:
    result = evaluate_loss_probability(
        {
            "expected_move_after_cost_bps": 0.0,
            "expected_edge_after_cost_bps": 12.0,
            "bucket_pf_window": 1.2,
            "microstructure_trust_score": 0.8,
        }
    )

    assert result["pre_trade_loss_probability"] >= 0.80
    assert "BLOCK_NEGATIVE_EXPECTANCY" in result["loss_probability_reasons"]
    assert result["block"] is True


def test_loss_probability_preserves_zero_bucket_pf_as_blocking_evidence() -> None:
    result = evaluate_loss_probability(
        {
            "pre_trade_expected_net_pnl_usd": 1.0,
            "bucket_pf_window": 0.0,
            "bucket_profit_factor": 1.5,
            "microstructure_trust_score": 0.8,
        }
    )

    assert result["pre_trade_loss_probability"] >= 0.80
    assert "BLOCK_PF_BELOW_1" in result["loss_probability_reasons"]
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


def test_loss_probability_prefers_directional_short_return() -> None:
    result = evaluate_loss_probability(
        {
            "expected_move_after_cost_bps": -12.5,
            "expected_move_after_cost_bps_directional": 12.5,
            "microstructure_trust_score": 0.8,
        }
    )

    assert "BLOCK_NEGATIVE_EXPECTANCY" not in result["loss_probability_reasons"]


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


def test_loss_probability_accepts_market_state_integrity_score_alias() -> None:
    result = evaluate_loss_probability(
        {
            "pre_trade_expected_net_pnl_usd": 0.75,
            "bucket_pf_window": 1.25,
            "market_state_integrity_score": 91.0,
        }
    )

    assert "BLOCK_MICROSTRUCTURE_UNSAFE" not in result["loss_probability_reasons"]
    assert result["block"] is False


def test_loss_probability_blocks_low_market_state_integrity_score_alias() -> None:
    result = evaluate_loss_probability(
        {
            "pre_trade_expected_net_pnl_usd": 0.75,
            "bucket_pf_window": 1.25,
            "market_state_integrity_score": 30.0,
        }
    )

    assert "BLOCK_MICROSTRUCTURE_UNSAFE" in result["loss_probability_reasons"]
    assert result["block"] is True
