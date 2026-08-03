"""Signal-layer adaptive after-cost recompute tests.

The all-timeframe publisher recomputes expected_move_after_cost_bps from the
symbol-adaptive cost model. Widening (clearing trainer flat-cost blocks)
requires FRESH orderbook evidence and the trainer's own min-edge threshold;
narrowing applies whenever adaptive evidence kills a flat-model edge.
Paper-only; live gate stays BLOCKED.
"""
from __future__ import annotations

from datetime import datetime, timezone

from v2.backend.app.services.all_timeframe_prediction_signal_price_target_publisher import (
    ADAPTIVE_COST_NARROW_BLOCK_REASON,
    adaptive_after_cost_recompute,
)
from v2.backend.app.services.paper_trade_management.adaptive_cost_model import (
    CostEstimate,
    FRESHNESS_FALLBACK_CONSERVATIVE,
    FRESHNESS_FRESH_ORDERBOOK,
)

NOW_ISO = datetime(2026, 7, 17, 6, 0, 0, tzinfo=timezone.utc).isoformat()


def _estimate(*, cost_bps: float, fresh: bool = True) -> CostEstimate:
    return CostEstimate(
        symbol="BTCUSDT",
        round_trip_cost_bps=cost_bps,
        taker_fee_bps_per_side=5.0,
        fee_source="test",
        spread_bps=0.016 if fresh else None,
        spread_source="orderbook_features_binance_live_spread_bps" if fresh else "missing",
        spread_age_seconds=2.0 if fresh else None,
        impact_per_side_bps=0.002,
        impact_source="test",
        depth_used_usd=1_000_000.0 if fresh else None,
        notional_usd_assumed=250.0,
        freshness_status=(
            FRESHNESS_FRESH_ORDERBOOK if fresh else FRESHNESS_FALLBACK_CONSERVATIVE
        ),
        conservative_floor_applied=not fresh,
        flat_baseline_round_trip_bps=12.0,
        orderbook_key="v2:orderbook:features:binance:BTCUSDT",
        computed_utc=NOW_ISO,
    )


def test_no_estimate_keeps_trainer_value_as_fallback() -> None:
    out = adaptive_after_cost_recompute(
        action="long",
        expected_move_bps=9.96,
        trainer_after_cost_bps=-2.04,
        trainer_paper_fill_allowed=False,
        trainer_block_reasons=["expected_move_after_cost_below_threshold"],
        cost_estimate=None,
    )
    assert out["applied"] is False
    assert out["expected_move_after_cost_bps_effective"] == -2.04
    assert out["round_trip_cost_source"] == "trainer_flat_fallback"
    # Flat cost is derivable from the trainer's own numbers: 9.96 - (-2.04) = 12.
    assert out["trainer_flat_round_trip_cost_bps"] == 12.0
    assert out["cost_regate_pass"] is False


def test_fresh_evidence_recomputes_major_after_cost_and_widen_regate() -> None:
    # Operator case: SOLUSDT-style 9.96bps move, flat model said -2.04.
    # Live cost 5.5bps => after-cost +4.46 >= 4.0 min edge -> honest unblock.
    out = adaptive_after_cost_recompute(
        action="long",
        expected_move_bps=9.96,
        trainer_after_cost_bps=-2.04,
        trainer_paper_fill_allowed=False,
        trainer_block_reasons=["expected_move_after_cost_below_threshold"],
        cost_estimate=_estimate(cost_bps=5.5),
        min_edge_after_cost_bps=4.0,
    )
    assert out["applied"] is True
    assert abs(out["expected_move_after_cost_bps_adaptive"] - 4.46) < 1e-9
    assert out["expected_move_after_cost_bps_effective"] == out[
        "expected_move_after_cost_bps_adaptive"
    ]
    assert out["round_trip_cost_source"] == "adaptive_cost_model_live_orderbook"
    assert out["cost_regate_pass"] is True
    assert out["cost_regate_reasons_cleared"] == [
        "expected_move_after_cost_below_threshold"
    ]


def test_recompute_can_stay_negative_honestly_without_widening() -> None:
    # Cost improves (12 -> 10.02) but the edge is still below min edge: the
    # point is per-symbol honesty, not forcing trades.
    out = adaptive_after_cost_recompute(
        action="long",
        expected_move_bps=9.96,
        trainer_after_cost_bps=-2.04,
        trainer_paper_fill_allowed=False,
        trainer_block_reasons=["expected_move_after_cost_below_threshold"],
        cost_estimate=_estimate(cost_bps=10.02),
        min_edge_after_cost_bps=4.0,
    )
    assert out["applied"] is True
    assert abs(out["expected_move_after_cost_bps_adaptive"] - (-0.06)) < 1e-9
    assert out["cost_regate_pass"] is False
    assert out["adaptive_edge_narrow_blocked"] is False


def test_widening_requires_fresh_evidence_never_fallback() -> None:
    out = adaptive_after_cost_recompute(
        action="long",
        expected_move_bps=20.0,
        trainer_after_cost_bps=8.0,
        trainer_paper_fill_allowed=False,
        trainer_block_reasons=["expected_move_after_cost_below_threshold"],
        cost_estimate=_estimate(cost_bps=12.0, fresh=False),
        min_edge_after_cost_bps=4.0,
    )
    assert out["applied"] is True
    assert out["cost_regate_pass"] is False
    assert out["round_trip_cost_source"] == "adaptive_cost_model_conservative_fallback"


def test_widening_requires_all_reasons_cost_derived() -> None:
    out = adaptive_after_cost_recompute(
        action="long",
        expected_move_bps=20.0,
        trainer_after_cost_bps=8.0,
        trainer_paper_fill_allowed=False,
        trainer_block_reasons=[
            "expected_move_after_cost_below_threshold",
            "confidence_below_threshold",
        ],
        cost_estimate=_estimate(cost_bps=5.0),
        min_edge_after_cost_bps=4.0,
    )
    # Confidence block is not cost-derived: never cleared by the cost model.
    assert out["cost_regate_pass"] is False


def test_narrowing_blocks_tail_symbol_whose_real_cost_is_higher() -> None:
    # Trainer allowed under flat 12; live wide-spread cost 22 kills the edge.
    out = adaptive_after_cost_recompute(
        action="long",
        expected_move_bps=17.0,
        trainer_after_cost_bps=5.0,
        trainer_paper_fill_allowed=True,
        trainer_block_reasons=[],
        cost_estimate=_estimate(cost_bps=22.0),
        min_edge_after_cost_bps=4.0,
    )
    assert out["applied"] is True
    assert abs(out["expected_move_after_cost_bps_adaptive"] - (-5.0)) < 1e-9
    assert out["adaptive_edge_narrow_blocked"] is True
    assert ADAPTIVE_COST_NARROW_BLOCK_REASON == (
        "expected_move_after_cost_below_threshold_adaptive"
    )


def test_short_side_sign_convention() -> None:
    # short favorable = negative after-cost: move + cost.
    out = adaptive_after_cost_recompute(
        action="short",
        expected_move_bps=-13.19,
        trainer_after_cost_bps=-1.19,
        trainer_paper_fill_allowed=False,
        trainer_block_reasons=["expected_move_after_cost_below_threshold"],
        cost_estimate=_estimate(cost_bps=5.0),
        min_edge_after_cost_bps=4.0,
    )
    assert out["applied"] is True
    assert abs(out["expected_move_after_cost_bps_adaptive"] - (-8.19)) < 1e-9
    # abs(-8.19) >= 4.0 and aligned for short -> widen passes.
    assert out["cost_regate_pass"] is True


def test_hold_action_never_recomputed() -> None:
    out = adaptive_after_cost_recompute(
        action="hold",
        expected_move_bps=-9.58,
        trainer_after_cost_bps=0.0,
        trainer_paper_fill_allowed=False,
        trainer_block_reasons=["action_not_directional"],
        cost_estimate=_estimate(cost_bps=5.0),
        min_edge_after_cost_bps=4.0,
    )
    assert out["applied"] is False
    assert out["expected_move_after_cost_bps_effective"] == 0.0
    assert out["cost_regate_pass"] is False
