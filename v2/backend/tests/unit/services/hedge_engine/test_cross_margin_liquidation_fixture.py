"""Phase 4 — cross-margin portfolio-level liquidation regression fixtures.

Exercises the real ``simulate_cross_margin_stress`` engine. Liquidation is
portfolio-level (never fake per-position), every result carries a portfolio
liquidation buffer, and no exchange margin mode is mutated.
"""

from __future__ import annotations

from v2.backend.app.services.hedge_engine import simulate_cross_margin_stress

_EQUITY = 200.0


def _stress(**overrides):
    base = dict(
        equity_usd=_EQUITY,
        available_margin_usd=_EQUITY,
        target_notional_usd=100.0,
        allocated_margin_usd=34.0,
        recommended_leverage=3.0,
        max_loss_usd=30.0,
        requested_margin_mode="cross",
        profit_factor=1.5,
        expectancy_usd=2.0,
    )
    base.update(overrides)
    return simulate_cross_margin_stress(**base)


def test_cross_margin_liquidation_buffer_decreases_with_new_position() -> None:
    small = _stress(target_notional_usd=50.0, allocated_margin_usd=17.0, max_loss_usd=10.0)
    big = _stress(target_notional_usd=180.0, allocated_margin_usd=60.0, max_loss_usd=120.0)
    assert (
        big["portfolio_liquidation_buffer_usd"]
        < small["portfolio_liquidation_buffer_usd"]
    )
    # Portfolio-level buffer is always present (never per-position-only).
    assert "portfolio_liquidation_buffer_usd" in small
    assert small["exchange_margin_mode_mutation_allowed"] is False


def test_cross_margin_liquidation_blocks_if_buffer_too_low() -> None:
    fragile = _stress(
        available_margin_usd=25.0,
        target_notional_usd=180.0,
        allocated_margin_usd=60.0,
        max_loss_usd=190.0,
    )
    assert fragile["cross_margin_safe"] is False
    assert fragile["margin_call_risk"] == "HIGH"
    assert fragile["recommended_margin_mode"].startswith("isolated")


def test_hedge_improves_liquidation_buffer_when_correlation_valid() -> None:
    unhedged = _stress()
    hedged = _stress(
        hedge_plan={
            "hedge_required": True,
            "hedge_increases_liquidation_risk": False,
            "hedge_expected_risk_reduction_usd": 15.0,
        }
    )
    assert (
        hedged["portfolio_liquidation_buffer_usd"]
        > unhedged["portfolio_liquidation_buffer_usd"]
    )
    # A hedge that WORSENS liquidation risk contributes no risk reduction.
    bad = _stress(
        hedge_plan={
            "hedge_required": True,
            "hedge_increases_liquidation_risk": True,
            "hedge_expected_risk_reduction_usd": 15.0,
        }
    )
    assert bad["cross_margin_hedge_risk_reduction_usd"] == 0.0


def test_position_without_liquidation_buffer_is_rejected() -> None:
    # A zero-notional (no real position) request cannot be cross-margin-safe.
    empty = _stress(target_notional_usd=0.0, allocated_margin_usd=0.0, max_loss_usd=0.0)
    assert empty["cross_margin_safe"] is False
    assert empty["places_real_order"] is False
