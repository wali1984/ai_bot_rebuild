from __future__ import annotations

from v2.backend.app.services.hedge_engine import (
    compute_portfolio_exposure,
    evaluate_hedge_intent,
    simulate_cross_margin_stress,
)


def test_portfolio_exposure_computes_delta_and_beta() -> None:
    exposure = compute_portfolio_exposure(
        [
            {"symbol": "BTCUSDT", "side": "long", "notional_usd": 100.0},
            {"symbol": "ETHUSDT", "side": "short", "notional_usd": 40.0},
        ],
        candidate={"symbol": "SOLUSDT", "side": "long", "target_notional_usd": 25.0},
        equity_usd=1000.0,
    )

    assert exposure["net_delta_usd"] == 85.0
    assert exposure["gross_exposure_usd"] == 165.0
    assert exposure["long_exposure_usd"] == 125.0
    assert exposure["short_exposure_usd"] == 40.0
    assert exposure["btc_beta_exposure_usd"] != 0.0
    assert exposure["eth_beta_exposure_usd"] != 0.0
    assert exposure["correlation_exposure_usd"] > 0.0


def test_hedge_cost_above_benefit_reduces_instead_of_hedging() -> None:
    plan = evaluate_hedge_intent(
        candidate={"symbol": "BTCUSDT", "side": "long", "target_notional_usd": 1000.0},
        equity_usd=2000.0,
        risk_budget_usd=10.0,
        hedge_budget_usd=2.0,
        max_loss_usd=1.0,
        expected_net_pnl_usd=2.0,
        spread_bps=500.0,
        slippage_bps=500.0,
        fee_bps=50.0,
        funding_bps=0.0,
        correlation_exposure_pct=0.4,
        liquidation_buffer_usd=100.0,
    )

    assert plan["hedge_action"] == "REDUCE_POSITION"
    assert plan["hedge_required"] is False
    assert plan["hedge_notional_usd"] == 0.0
    assert "HEDGE_COST_EXCEEDS_EXPECTED_RISK_REDUCTION" in plan["hedge_reason"]


def test_hedge_never_averages_down_same_direction() -> None:
    plan = evaluate_hedge_intent(
        candidate={"symbol": "BTCUSDT", "side": "short", "target_notional_usd": 1000.0},
        positions=[{"symbol": "ETHUSDT", "side": "long", "notional_usd": 3000.0}],
        equity_usd=2000.0,
        risk_budget_usd=10.0,
        hedge_budget_usd=2.0,
        max_loss_usd=50.0,
        expected_net_pnl_usd=5.0,
        spread_bps=1.0,
        slippage_bps=1.0,
        fee_bps=1.0,
        funding_bps=0.0,
        correlation_exposure_pct=0.4,
        liquidation_buffer_usd=100.0,
    )

    assert plan["hedge_action"] == "REDUCE_POSITION"
    assert plan["hedge_averaging_down_rejected"] is True
    assert plan["hedge_notional_usd"] == 0.0


def test_cross_margin_simulation_prefers_isolated_when_stress_unsafe() -> None:
    stress = simulate_cross_margin_stress(
        equity_usd=1000.0,
        available_margin_usd=25.0,
        target_notional_usd=900.0,
        allocated_margin_usd=300.0,
        recommended_leverage=3.0,
        max_loss_usd=80.0,
        requested_margin_mode="cross_paper_simulated",
        expectancy_usd=10.0,
    )

    assert stress["recommended_margin_mode"] == "isolated_paper_simulated"
    assert stress["cross_margin_safe"] is False
    assert stress["exchange_margin_mode_mutation_allowed"] is False
    assert stress["places_real_order"] is False
