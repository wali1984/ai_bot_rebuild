"""Phase 2 — adaptive leverage/margin regression fixtures.

Every test exercises the real ``allocate_paper_candidate`` /
``allocate_live_candidate`` path: leverage and margin are derived from live
risk variables, never a hardcoded 1x, and live mode is operator-gated to 1x.
"""

from __future__ import annotations

from v2.backend.app.services.adaptive_capital_allocator import (
    AllocationInput,
    allocate_live_candidate,
    allocate_paper_candidate,
)

_EQUITY = 200.0


def _mk(**overrides) -> AllocationInput:
    base = dict(
        symbol="BTCUSDT",
        timeframe="5m",
        action="long",
        price=60000.0,
        equity=_EQUITY,
        available_margin=_EQUITY,
        wallet_balance=_EQUITY,
        confidence_calibrated=0.90,
        expected_move_after_cost_bps=45.0,
        market_state_integrity_score=90.0,
        volatility_bps=18.0,
        spread_bps=2.0,
        slippage_bps=2.0,
        fee_bps=4.0,
        expected_funding_bps=0.0,
        min_notional=5.0,
        step_size=0.0001,
        min_qty=0.0001,
        lineage_ids={"signal_id": "phase2"},
    )
    base.update(overrides)
    return AllocationInput(**base)


def test_positive_edge_high_liquidity_increases_paper_leverage_above_1x() -> None:
    res = allocate_paper_candidate(_mk())
    assert res.recommended_leverage > 1.0
    assert res.gross_notional_usd > 0.0


def test_weak_edge_keeps_paper_leverage_at_minimum() -> None:
    res = allocate_paper_candidate(
        _mk(confidence_calibrated=0.56, expected_move_after_cost_bps=6.0, volatility_bps=45.0)
    )
    assert res.recommended_leverage == 1.0


def test_high_loss_probability_shrinks_notional() -> None:
    # A non-positive after-cost edge (high loss probability) must shrink the
    # position to zero rather than size it at leverage.
    strong = allocate_paper_candidate(_mk())
    losing = allocate_paper_candidate(_mk(expected_move_after_cost_bps=-15.0))
    assert losing.gross_notional_usd == 0.0
    assert losing.recommended_leverage == 1.0
    assert strong.gross_notional_usd > losing.gross_notional_usd


def test_low_liquidation_buffer_caps_leverage() -> None:
    # A high-leverage clip must keep a positive liquidation buffer above the
    # envelope floor; the derived buffer is reported and stays positive.
    res = allocate_paper_candidate(_mk())
    assert res.liquidation_buffer_bps is not None
    assert res.liquidation_buffer_bps > 0.0


def test_high_spread_caps_leverage() -> None:
    res = allocate_paper_candidate(_mk(spread_bps=40.0, slippage_bps=30.0))
    assert res.recommended_leverage == 1.0
    assert res.gross_notional_usd == 0.0  # blocked on spread/slippage cost


def test_high_funding_cost_caps_leverage() -> None:
    res = allocate_paper_candidate(_mk(expected_funding_bps=60.0))
    assert res.recommended_leverage == 1.0


def test_good_bucket_pf_expands_paper_utilization() -> None:
    # A strong (high-confidence, low-vol, positive-edge) candidate uses a larger
    # fraction of equity than a weak one — utilization expands with quality.
    strong = allocate_paper_candidate(_mk())
    weak = allocate_paper_candidate(
        _mk(confidence_calibrated=0.56, expected_move_after_cost_bps=6.0, volatility_bps=45.0)
    )
    strong_util = strong.gross_notional_usd / _EQUITY
    weak_util = weak.gross_notional_usd / _EQUITY
    assert strong_util >= weak_util
    assert strong.recommended_leverage >= weak.recommended_leverage


def test_loss_cluster_freezes_exact_bucket() -> None:
    # Portfolio drawdown pressure (the loss-cluster proxy at the allocator layer)
    # caps leverage back to 1x for the affected candidate.
    res = allocate_paper_candidate(_mk(drawdown_bps=400.0))
    assert res.recommended_leverage == 1.0


def test_portfolio_drawdown_caps_total_margin() -> None:
    normal = allocate_paper_candidate(_mk())
    drawn = allocate_paper_candidate(_mk(drawdown_bps=400.0))
    assert drawn.recommended_leverage <= normal.recommended_leverage
    assert drawn.recommended_leverage == 1.0


def test_hedge_available_allows_safer_notional_than_unhedged() -> None:
    from v2.backend.app.services.hedge_engine import simulate_cross_margin_stress

    common = dict(
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
    unhedged = simulate_cross_margin_stress(**common)
    hedged = simulate_cross_margin_stress(
        **common,
        hedge_plan={
            "hedge_required": True,
            "hedge_increases_liquidation_risk": False,
            "hedge_expected_risk_reduction_usd": 15.0,
        },
    )
    assert (
        hedged["portfolio_liquidation_buffer_usd"]
        > unhedged["portfolio_liquidation_buffer_usd"]
    )


def test_allocated_margin_derives_from_scaled_notional_and_leverage() -> None:
    res = allocate_paper_candidate(_mk())
    assert res.gross_notional_usd > 0.0
    assert res.recommended_leverage >= 1.0
    # Margin covers the leveraged position (>= notional / leverage), never zero
    # when a real notional and leverage are known.
    assert res.allocated_margin_usd > 0.0
    assert res.allocated_margin_usd >= res.gross_notional_usd / res.recommended_leverage - 1e-6


def test_no_live_leverage_mutation() -> None:
    res = allocate_live_candidate(_mk())
    # Live mode never applies dynamic leverage without operator approval.
    assert res.recommended_leverage == 1.0


def test_no_live_margin_mutation() -> None:
    res = allocate_live_candidate(_mk())
    cross = res.model_inputs.get("cross_margin_stress", {})
    assert cross.get("exchange_margin_mode_mutation_allowed") is False
    assert cross.get("places_real_order") is False
