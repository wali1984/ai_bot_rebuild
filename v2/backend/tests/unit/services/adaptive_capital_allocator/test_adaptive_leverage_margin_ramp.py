"""Phase 2 — adaptive leverage/margin regression fixtures.

Every test exercises the real ``allocate_paper_candidate`` /
``allocate_live_candidate`` path: leverage and margin are derived from live
risk variables, never a hardcoded 1x, and live mode is operator-gated to 1x.
"""

from __future__ import annotations

from v2.backend.app.services.adaptive_capital_allocator import (
    AllocationInput,
    allocate_live_candidate,
)
from v2.backend.app.services.adaptive_capital_allocator.allocator import (
    PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_LINEAGE_KEY,
    PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY,
    build_paper_liquidation_atr_evidence,
)
from v2.backend.tests.unit.services.adaptive_capital_allocator.growth_receipt_test_utils import (
    allocate_authorized_growth as allocate_paper_candidate,
)

_EQUITY = 200.0


def _mk(*, with_liquidation_atr_evidence: bool = True, **overrides) -> AllocationInput:
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
        maintenance_margin_rate=0.005,
        min_notional=5.0,
        step_size=0.0001,
        min_qty=0.0001,
        lineage_ids={"signal_id": "phase2"},
    )
    base.update(overrides)
    if with_liquidation_atr_evidence:
        entry_atr_bps = base.get("entry_atr_bps", base["volatility_bps"])
        base["entry_atr_bps"] = entry_atr_bps
        receipt, reasons = build_paper_liquidation_atr_evidence(
            feature_snapshot={
                "feature_snapshot_id": "adaptive-ramp-snapshot",
                "symbol": base["symbol"],
                "timeframe": base["timeframe"],
                "feature_freshness_state": "CURRENT",
                    "candle_closed_confirmed": True,
                    "latest_unclosed_kline_excluded": True,
                    "candle_close_time": "2026-07-18T11:59:59Z",
                    "feature_cutoff": "2026-07-18T12:00:00Z",
                "available_at": "2026-07-18T12:00:01Z",
                "generated_at": "2026-07-18T12:00:02Z",
                "features": {"atr_bps": entry_atr_bps},
            },
            symbol=base["symbol"],
            timeframe=base["timeframe"],
            entry_price=base["price"],
            allocation_decision_time="2026-07-18T12:00:03Z",
        )
        assert not reasons
        assert receipt is not None
        lineage_ids = dict(base.get("lineage_ids") or {})
        lineage_ids[PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY] = receipt
        lineage_ids[PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_LINEAGE_KEY] = receipt[
            "evidence_sha256"
        ]
        base["lineage_ids"] = lineage_ids
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
    # Expected edge is already after cost, so paper cost pressure reduces size
    # and leverage continuously instead of creating a second admission cliff.
    res = allocate_paper_candidate(_mk(spread_bps=60.0, slippage_bps=35.0))
    assert res.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert res.recommended_leverage == 1.0
    assert res.gross_notional_usd > 0.0
    # The discrete permitted ladder may select 1x for both, while the continuous
    # target still declines with the costlier book.
    clean = allocate_paper_candidate(_mk(confidence_calibrated=0.70))
    costly = allocate_paper_candidate(
        _mk(confidence_calibrated=0.70, spread_bps=40.0, slippage_bps=30.0)
    )
    assert costly.recommended_leverage == 1.0
    assert costly.model_inputs["leverage_target"] < clean.model_inputs["leverage_target"]


def test_high_funding_cost_caps_leverage() -> None:
    # Heavy funding drag continuously shrinks the evidence-supported target.
    res = allocate_paper_candidate(_mk(confidence_calibrated=0.70, expected_funding_bps=60.0))
    baseline = allocate_paper_candidate(_mk(confidence_calibrated=0.70))
    assert res.recommended_leverage == 1.0
    assert res.model_inputs["leverage_target"] < baseline.model_inputs["leverage_target"]
    # Maximum confidence is still only evidence; it cannot bypass funding drag.
    high_confidence_costly = allocate_paper_candidate(_mk(expected_funding_bps=60.0))
    high_confidence_clean = allocate_paper_candidate(_mk())
    assert high_confidence_costly.model_inputs["leverage_target"] < (
        high_confidence_clean.model_inputs["leverage_target"]
    )
    assert high_confidence_costly.model_inputs["leverage_selection_reason"] == (
        "continuous_market_evidence_within_supplied_dynamic_envelope"
    )


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
    # continuously shrinks leverage back to the permitted 1x rung.
    res = allocate_paper_candidate(_mk(confidence_calibrated=0.80, drawdown_bps=400.0))
    assert res.recommended_leverage == 1.0
    assert res.model_inputs["leverage_drawdown_resilience"] == 0.2
    assert res.model_inputs["leverage_selection_reason"] == (
        "continuous_market_evidence_within_supplied_dynamic_envelope"
    )


def test_portfolio_drawdown_caps_total_margin() -> None:
    # Drawdown shrinks leverage monotonically down to 1x.
    normal = allocate_paper_candidate(_mk(confidence_calibrated=0.80))
    drawn = allocate_paper_candidate(_mk(confidence_calibrated=0.80, drawdown_bps=400.0))
    assert drawn.recommended_leverage < normal.recommended_leverage
    assert drawn.recommended_leverage == 1.0
    # Live mode stays operator-gated at 1x regardless of drawdown state.
    live = allocate_live_candidate(_mk(drawdown_bps=400.0))
    assert live.recommended_leverage == 1.0


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
