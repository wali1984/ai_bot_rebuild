from __future__ import annotations

from v2.backend.app.services.preemptive_edge_control.portfolio_stress import (
    assess_portfolio_stress,
)


def test_portfolio_stress_preserves_explicit_zero_target_notional() -> None:
    result = assess_portfolio_stress(
        {
            "target_notional_usd": 0.0,
            "gross_notional_usd": 250.0,
            "allocated_margin_usd": 0.0,
            "margin": 50.0,
            "recommended_leverage": 0.0,
            "leverage_recommendation": 5.0,
            "stop_distance_bps": 0.0,
            "max_loss_bps": 200.0,
        },
        expected_edge_after_cost_bps=12.0,
        bucket_profit_factor=1.5,
    )

    assert result["target_notional_usd"] == 0.0
    assert result["allocated_margin_usd"] == 0.0
    assert result["recommended_leverage"] == 0.0
    assert result["max_loss_if_stop_hit"] == 0.0


def test_portfolio_stress_preserves_explicit_zero_risk_budget() -> None:
    result = assess_portfolio_stress(
        {
            "target_notional_usd": 100.0,
            "allocated_margin_usd": 20.0,
            "recommended_leverage": 2.0,
            "stop_distance_bps": 100.0,
            "risk_budget_usd": 0.0,
        },
        expected_edge_after_cost_bps=12.0,
        bucket_profit_factor=1.5,
    )

    assert result["target_notional_usd"] == 100.0
    assert result["risk_budget_usd"] == 0.0
    assert result["max_loss_if_stop_hit"] == 1.0
