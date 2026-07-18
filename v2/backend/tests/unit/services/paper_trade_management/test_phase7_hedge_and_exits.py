"""Phase 7 — Hedge path fields and dynamic exit trigger tests.

Validates:
 - hedge_recommendation field populated on all evaluation paths
 - hedge_cost_bps and hedge_benefit_bps populated when hedge is proposed
 - unwind_reason populated when hedge is proposed or blocked by budget
 - fail-closed invariants preserved (operator_approval=False by default)
 - ATR-based volatility-adjusted stop fires before static stop_loss
 - liquidity-aware TP skips TP tier when ob_spread_bps exceeds threshold
 - existing exit tiers (emergency, microstructure, confidence_decay) unchanged
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.services.trade_management_paper.hedge_engine import (
    HedgeEvaluation,
    HedgePositionInputs,
    evaluate_hedge,
)
from app.services.paper_trade_management.exits import PaperExitConfig, evaluate_exit


# ── Shared position fixtures ──────────────────────────────────────────────────

def _long_position():
    from app.services.paper_trade_management.position_state import PaperNetPosition

    pos = PaperNetPosition(
        position_id="paper_pos_BTCUSDT",
        symbol="BTCUSDT",
        side="long",
        net_quantity=0.01,
        avg_entry_price=100_000.0,
        opened_est="2026-06-17T00:00:00Z",
        best_favorable_price=None,
    )
    pos.size = 0.01
    return pos


def _short_position():
    from app.services.paper_trade_management.position_state import PaperNetPosition

    pos = PaperNetPosition(
        position_id="paper_pos_BTCUSDT_short",
        symbol="BTCUSDT",
        side="short",
        net_quantity=-0.01,
        avg_entry_price=100_000.0,
        opened_est="2026-06-17T00:00:00Z",
        best_favorable_price=None,
    )
    pos.size = 0.01
    return pos


def _approved_long_drawdown() -> HedgePositionInputs:
    return HedgePositionInputs(
        symbol="BTCUSDT",
        side="long",
        notional_usd=1000.0,
        unrealized_pnl_bps=-120.0,
        age_seconds=120,
        drawdown_bps_abs=150.0,
        live_gate="blocked_human_only",
        live_symbols=(),
    )


# ── Hedge recommendation field ────────────────────────────────────────────────

def test_hedge_fail_closed_recommendation_is_no_hedge_when_not_approved() -> None:
    inp = _approved_long_drawdown()
    result = evaluate_hedge(inp, operator_paper_hedge_engine_approved=False)
    assert result.hedge_recommendation == "NO_HEDGE"


def test_hedge_recommendation_is_hedge_proposed_when_approved_and_triggered() -> None:
    inp = _approved_long_drawdown()
    # max_budget_ratio=0.8 ensures the sized ratio (~0.6) fits within budget.
    result = evaluate_hedge(inp, operator_paper_hedge_engine_approved=True, max_budget_ratio=0.8)
    assert result.hedge_recommendation == "HEDGE_PROPOSED"
    assert result.hedge_needed is True


def test_hedge_recommendation_budget_blocked() -> None:
    inp = _approved_long_drawdown()
    result = evaluate_hedge(
        inp,
        operator_paper_hedge_engine_approved=True,
        max_budget_ratio=0.01,  # very tight — will block
    )
    assert result.hedge_recommendation == "HEDGE_BLOCKED_BUDGET"


def test_hedge_cost_bps_set_when_proposed() -> None:
    inp = _approved_long_drawdown()
    result = evaluate_hedge(inp, operator_paper_hedge_engine_approved=True, max_budget_ratio=0.8)
    assert result.hedge_cost_bps == 8.0


def test_hedge_benefit_bps_positive_when_proposed() -> None:
    inp = _approved_long_drawdown()
    result = evaluate_hedge(inp, operator_paper_hedge_engine_approved=True, max_budget_ratio=0.8)
    assert result.hedge_benefit_bps > 0.0


def test_unwind_reason_set_when_hedge_proposed() -> None:
    inp = _approved_long_drawdown()
    result = evaluate_hedge(inp, operator_paper_hedge_engine_approved=True, max_budget_ratio=0.8)
    assert len(result.unwind_reason) > 0
    assert "UNWIND" in result.unwind_reason


def test_fail_closed_fields_default_on_no_approval_path() -> None:
    inp = _approved_long_drawdown()
    result = evaluate_hedge(inp, operator_paper_hedge_engine_approved=False)
    assert result.hedge_cost_bps == 0.0
    assert result.hedge_benefit_bps == 0.0
    assert result.unwind_reason == ""


def test_hedge_evaluation_never_places_real_order() -> None:
    from app.services.trade_management_paper.hedge_engine import hedge_engine_invariants_snapshot
    snap = hedge_engine_invariants_snapshot()
    assert snap["places_exchange_orders"] is False
    assert snap["writes_legacy_redis"] is False
    assert snap["approves_live"] is False


def test_advanced_fvg_invalidation_closes_position_before_static_tiers() -> None:
    pos = _long_position()
    result = evaluate_exit(
        position=pos,
        mark_price=100_200.0,
        generated_utc="2026-06-17T00:05:00Z",
        config=PaperExitConfig(static_take_profit_enabled=False, static_stop_loss_enabled=False),
        alpha_context={
            "advanced_indicator_context": {
                "fvg_invalidated": True,
                "fvg_kind": "bullish",
                "distance_to_fvg_bps": -25.0,
                "nearest_liquidity_above": 101_000.0,
            }
        },
    )

    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_1_FVG_INVALIDATION_EXIT"
    assert result["advanced_indicator_exit"] is True
    assert result["advanced_indicator_exit_context"]["places_real_order"] is False


def test_advanced_structure_invalidation_closes_against_long() -> None:
    pos = _long_position()
    result = evaluate_exit(
        position=pos,
        mark_price=100_100.0,
        generated_utc="2026-06-17T00:05:00Z",
        config=PaperExitConfig(static_take_profit_enabled=False, static_stop_loss_enabled=False),
        alpha_context={
            "advanced_indicator_context": {
                "choch_direction": "down",
                "nearest_liquidity_below": 99_200.0,
            }
        },
    )

    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_1_STRUCTURE_INVALIDATION_EXIT"
    assert result["advanced_indicator_exit_context"]["nearest_liquidity_below"] == 99_200.0


def test_advanced_vwap_cvd_invalidation_closes_long() -> None:
    pos = _long_position()
    result = evaluate_exit(
        position=pos,
        mark_price=99_800.0,
        generated_utc="2026-06-17T00:05:00Z",
        config=PaperExitConfig(static_take_profit_enabled=False, static_stop_loss_enabled=False),
        alpha_context={
            "advanced_indicator_context": {
                "distance_to_vwap_bps": -12.0,
                "cvd_slope": -0.4,
                "session_vwap": 99_920.0,
            }
        },
    )

    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_1_VWAP_CVD_INVALIDATION_EXIT"
    assert result["advanced_indicator_exit_context"]["nearest_liquidity_target"] == 99_920.0


# ── ATR-based volatility-adjusted stop ────────────────────────────────────────

def test_atr_stop_fires_before_static_stop_loss() -> None:
    pos = _long_position()
    # PnL at -55 bps: below ATR stop (atr_bps=25, multiplier=2 → stop at -50 bps,
    # above the 35 bps compressed-vol floor) but above static stop_loss (80 bps).
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None

    config = PaperExitConfig(
        stop_loss_bps=80.0,
        atr_stop_multiplier=2.0,
        min_hold_seconds=0,
    )
    # Simulate PnL by making position's mark_price 55 bps below entry
    mark = 100_000.0 * (1 - 55 / 10000.0)
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=25.0,  # 25 bps ATR → stop at 50 bps
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_1_ATR_VOLATILITY_STOP"
    assert result["atr_bps"] == 25.0
    assert result["atr_stop_floor_applied"] is False


def test_atr_stop_floor_blocks_sub_cost_stop_in_compressed_volatility() -> None:
    """2026-07-05 cluster regression: entry ATR 6-7 bps put the scaled stop at
    ~19-21 bps — inside round-trip cost plus one candle of noise. The floor
    keeps the effective stop at atr_stop_floor_bps so the position is not
    stopped at -20 bps, while a move past the floor still closes."""
    config = PaperExitConfig(
        stop_loss_bps=80.0,
        atr_stop_multiplier=2.0,
        atr_stop_multiplier_trend_mode=3.0,
        atr_stop_floor_bps=35.0,
        min_hold_seconds=0,
        mfe_breakeven_protection_enabled=False,
    )

    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None
    # -20 bps with ATR 7 bps (scaled stop 14-21 bps < floor 35): must NOT close.
    mark = 100_000.0 * (1 - 20 / 10000.0)
    held = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=7.0,
    )
    assert held["should_close"] is False

    pos2 = _long_position()
    pos2.avg_entry_price = 100_000.0
    pos2.best_favorable_price = None
    # -36 bps breaches the 35 bps floor: closes with the floor recorded.
    mark2 = 100_000.0 * (1 - 36 / 10000.0)
    closed = evaluate_exit(
        position=pos2,
        mark_price=mark2,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=7.0,
    )
    assert closed["should_close"] is True
    assert closed["close_reason"] == "TIER_1_ATR_VOLATILITY_STOP"
    assert closed["atr_stop_floor_applied"] is True
    assert closed["atr_stop_bps"] == 35.0


def test_atr_stop_does_not_fire_when_pnl_within_range() -> None:
    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None

    config = PaperExitConfig(
        stop_loss_bps=80.0,
        atr_stop_multiplier=2.0,
        min_hold_seconds=0,
    )
    # PnL at -5 bps: above ATR stop threshold (-16 bps)
    mark = 100_000.0 * (1 - 5 / 10000.0)
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=8.0,
    )
    assert result["should_close"] is False


def test_atr_stop_not_applied_when_atr_none() -> None:
    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None

    config = PaperExitConfig(stop_loss_bps=80.0, min_hold_seconds=0)
    mark = 100_000.0 * (1 - 20 / 10000.0)  # -20 bps, below ATR stop but atr_bps=None
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=None,
    )
    # Static stop is at 80 bps, we're at -20 bps so no stop yet
    assert result["should_close"] is False


# ── CG-F052: adaptive ATR-stop ceiling ───────────────────────────────────────
def _wide_atr_config(*, ceiling_bps: float) -> "PaperExitConfig":
    """Runtime-representative config: static stops OFF (as the paper loop sets
    them), a wide ATR multiplier so high-ATR symbols compute a stop far past the
    catastrophic floor, and the optional ceiling under test."""
    return PaperExitConfig(
        static_stop_loss_enabled=False,
        atr_stop_multiplier=2.0,
        atr_stop_floor_bps=35.0,
        catastrophic_floor_stop_bps=150.0,
        atr_stop_ceiling_bps=ceiling_bps,
        min_hold_seconds=0,
        mfe_breakeven_protection_enabled=False,
    )


def test_atr_ceiling_disabled_by_default_runs_to_catastrophic_floor() -> None:
    # atr_bps=500 -> effective ATR stop ~1000bps (never fires); with the ceiling
    # DISABLED (default 0) a -160bps loser runs all the way to the -150 floor.
    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None
    config = _wide_atr_config(ceiling_bps=0.0)
    mark = 100_000.0 * (1 - 160 / 10000.0)
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=500.0,
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_0_CATASTROPHIC_FLOOR_STOP"


def test_atr_ceiling_cuts_high_atr_loser_before_catastrophic_floor() -> None:
    # Same wide ATR stop, but ceiling=80 cuts the -90bps loser at the ceiling,
    # well before the -150 catastrophic floor -- the CG-F052 fix.
    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None
    config = _wide_atr_config(ceiling_bps=80.0)
    mark = 100_000.0 * (1 - 90 / 10000.0)
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=500.0,
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_1_ATR_CEILING_STOP"
    assert result["atr_stop_ceiling_bps"] == 80.0


def test_atr_ceiling_does_not_preempt_tighter_atr_stop() -> None:
    # Low-ATR symbol: atr_bps=25 -> stop ~50bps. A -60bps loser must exit via the
    # tighter TIER_1 ATR stop, NOT the 80bps ceiling (ceiling only backstops wide
    # stops; it must not override a symbol's own tighter stop).
    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None
    config = _wide_atr_config(ceiling_bps=80.0)
    mark = 100_000.0 * (1 - 60 / 10000.0)
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=25.0,
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_1_ATR_VOLATILITY_STOP"


def test_atr_ceiling_holds_position_inside_the_band() -> None:
    # Wide ATR stop, ceiling=80, loss only -70bps: neither the ATR stop, the
    # ceiling, nor the catastrophic floor is breached -> position is held.
    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None
    config = _wide_atr_config(ceiling_bps=80.0)
    mark = 100_000.0 * (1 - 70 / 10000.0)
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=500.0,
    )
    assert result["should_close"] is False


def test_atr_ceiling_cuts_losing_short_symmetrically() -> None:
    # The book runs 2.6:1 long but losing shorts must also be capped. A losing
    # short is price UP; unrealized_pnl_bps is side-aware so pnl_bps is negative
    # and the ceiling check fires symmetrically.
    from app.services.paper_trade_management.position_state import PaperNetPosition

    pos = PaperNetPosition(
        position_id="paper_pos_BTCUSDT",
        symbol="BTCUSDT",
        side="short",
        net_quantity=-0.01,
        avg_entry_price=100_000.0,
        opened_est="2026-06-17T00:00:00Z",
        best_favorable_price=None,
    )
    pos.size = 0.01
    config = _wide_atr_config(ceiling_bps=80.0)
    mark = 100_000.0 * (1 + 90 / 10000.0)  # short down 90 bps
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=500.0,
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_1_ATR_CEILING_STOP"
    assert result["atr_stop_ceiling_bps"] == 80.0


def test_atr_scaled_trailing_stop_holds_inside_dynamic_distance() -> None:
    from app.services.paper_trade_management.position_state import PaperNetPosition

    pos = PaperNetPosition(
        position_id="paper_pos_BTCUSDT",
        symbol="BTCUSDT",
        side="long",
        net_quantity=1.0,
        avg_entry_price=100.0,
        opened_est="2026-06-17T00:00:00Z",
        best_favorable_price=110.0,
        intra_trade_high_price=110.0,
        intra_trade_low_price=100.0,
        last_mark_price=110.0,
    )
    config = PaperExitConfig(
        trailing_stop_bps=60.0,
        atr_trailing_stop_multiplier=1.5,
        min_profit_before_trailing_bps=30.0,
        take_profit_bps=99999.0,
        stop_loss_bps=99999.0,
        profit_bank_bps=99999.0,
        profit_lock_bps=99999.0,
    )
    result = evaluate_exit(
        position=pos,
        mark_price=110.0 * (1.0 - 80.0 / 10000.0),
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=100.0,
    )

    assert result["should_close"] is False
    assert pos.trailing_stop_history
    assert pos.trailing_stop_price == pytest.approx(110.0 * (1.0 - 150.0 / 10000.0))


def test_atr_scaled_trailing_stop_closes_after_dynamic_distance() -> None:
    from app.services.paper_trade_management.position_state import PaperNetPosition

    pos = PaperNetPosition(
        position_id="paper_pos_BTCUSDT",
        symbol="BTCUSDT",
        side="long",
        net_quantity=1.0,
        avg_entry_price=100.0,
        opened_est="2026-06-17T00:00:00Z",
        best_favorable_price=110.0,
        intra_trade_high_price=110.0,
        intra_trade_low_price=100.0,
        last_mark_price=110.0,
    )
    config = PaperExitConfig(
        trailing_stop_bps=60.0,
        atr_trailing_stop_multiplier=1.5,
        min_profit_before_trailing_bps=30.0,
        take_profit_bps=99999.0,
        stop_loss_bps=99999.0,
        profit_bank_bps=99999.0,
        profit_lock_bps=99999.0,
    )
    result = evaluate_exit(
        position=pos,
        mark_price=110.0 * (1.0 - 180.0 / 10000.0),
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=100.0,
    )

    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_2_TRAILING_STOP"
    assert result["trailing_stop_bps_effective"] == pytest.approx(150.0)
    assert result["atr_bps"] == pytest.approx(100.0)


def test_trailing_stop_blocks_when_after_cost_profit_floor_not_met() -> None:
    from app.services.paper_trade_management.position_state import PaperNetPosition

    pos = PaperNetPosition(
        position_id="paper_pos_BTCUSDT",
        symbol="BTCUSDT",
        side="long",
        net_quantity=1.0,
        avg_entry_price=100.0,
        opened_est="2026-06-17T00:00:00Z",
        best_favorable_price=101.0,
        intra_trade_high_price=101.0,
        intra_trade_low_price=100.0,
        last_mark_price=101.0,
    )
    config = PaperExitConfig(
        trailing_stop_bps=20.0,
        min_profit_before_trailing_bps=30.0,
        trailing_stop_min_after_cost_buffer_bps=25.0,
        take_profit_bps=99999.0,
        stop_loss_bps=99999.0,
        profit_bank_bps=99999.0,
        profit_lock_bps=99999.0,
    )
    result = evaluate_exit(
        position=pos,
        mark_price=100.4,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        ob_spread_bps=5.0,
    )

    assert result["should_close"] is False
    assert result["close_reason"] is None
    assert result["blocker"] == "TRAILING_AFTER_COST_PROFIT_FLOOR_NOT_MET"
    assert result["pnl_bps"] == pytest.approx(40.0)
    assert result["drawdown_from_best_bps"] > 20.0
    assert result["trailing_profit_floor_bps"] == pytest.approx(55.0)
    assert result["trailing_after_cost_buffer_bps"] == pytest.approx(25.0)


def test_prior_armed_trailing_stop_closes_positive_gap_below_profit_floor() -> None:
    from app.services.paper_trade_management.position_state import PaperNetPosition

    pos = PaperNetPosition(
        position_id="paper_pos_BTCUSDT",
        symbol="BTCUSDT",
        side="long",
        net_quantity=1.0,
        avg_entry_price=100.0,
        opened_est="2026-06-17T00:00:00Z",
        best_favorable_price=101.0,
        intra_trade_high_price=101.0,
        intra_trade_low_price=100.0,
        last_mark_price=101.0,
        trailing_activation_price=100.55,
        trailing_activation_time="2026-06-17T00:30:00Z",
        trailing_stop_price=100.798,
        trailing_stop_history=[
            {
                "generated_utc": "2026-06-17T00:30:00Z",
                "activation_price": 100.55,
                "trailing_stop_price": 100.798,
                "reason": "ADAPTIVE_TRAIL_ARMED_AFTER_NET_PROFIT_FLOOR",
            }
        ],
    )
    config = PaperExitConfig(
        trailing_stop_bps=20.0,
        min_profit_before_trailing_bps=30.0,
        trailing_stop_min_after_cost_buffer_bps=25.0,
        take_profit_bps=99999.0,
        stop_loss_bps=99999.0,
        profit_bank_bps=99999.0,
        profit_lock_bps=99999.0,
    )
    result = evaluate_exit(
        position=pos,
        mark_price=100.4,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        ob_spread_bps=5.0,
    )

    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_2_TRAILING_STOP"
    assert result["pnl_bps"] == pytest.approx(40.0)
    assert result["trailing_profit_floor_bps"] == pytest.approx(55.0)
    assert result["trailing_profit_floor_gap_bps"] == pytest.approx(15.0)
    assert result["trailing_profit_floor_gap_exit"] is True
    assert result["paper_exit_price"] == pytest.approx(100.798)
    assert result["paper_exit_price_source"] == "PAPER_TRAILING_STOP_PRICE"
    assert result["paper_exit_pnl_bps"] == pytest.approx(79.8)
    assert result["trailing_stop_exit_floor_bps"] == pytest.approx(30.0)
    assert result["trailing_stop_exit_floor_gap_bps"] == pytest.approx(0.0)
    assert result["trailing_stop_mark_price"] == pytest.approx(100.4)
    assert result["trailing_stop_gap_bps"] == pytest.approx(((100.798 - 100.4) / 100.798) * 10000.0)
    assert (
        result["trailing_profit_floor_gap_exit_reason"]
        == "PRIOR_ARMED_TRAILING_STOP_BREACHED_WITH_POSITIVE_PNL"
    )


def test_prior_armed_trailing_stop_closes_with_stop_price_when_mark_gaps_to_loss() -> None:
    from app.services.paper_trade_management.position_state import PaperNetPosition

    pos = PaperNetPosition(
        position_id="paper_pos_BTCUSDT",
        symbol="BTCUSDT",
        side="long",
        net_quantity=1.0,
        avg_entry_price=100.0,
        opened_est="2026-06-17T00:00:00Z",
        best_favorable_price=101.0,
        intra_trade_high_price=101.0,
        intra_trade_low_price=100.0,
        last_mark_price=101.0,
        trailing_activation_price=100.55,
        trailing_activation_time="2026-06-17T00:30:00Z",
        trailing_stop_price=100.798,
        trailing_stop_history=[
            {
                "generated_utc": "2026-06-17T00:30:00Z",
                "activation_price": 100.55,
                "trailing_stop_price": 100.798,
                "reason": "ADAPTIVE_TRAIL_ARMED_AFTER_NET_PROFIT_FLOOR",
            }
        ],
    )
    config = PaperExitConfig(
        trailing_stop_bps=20.0,
        min_profit_before_trailing_bps=30.0,
        trailing_stop_min_after_cost_buffer_bps=25.0,
        take_profit_bps=99999.0,
        stop_loss_bps=99999.0,
        profit_bank_bps=99999.0,
        profit_lock_bps=99999.0,
    )
    result = evaluate_exit(
        position=pos,
        mark_price=99.8,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        ob_spread_bps=5.0,
    )

    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_2_TRAILING_STOP"
    assert result["pnl_bps"] == pytest.approx(-20.0)
    assert result["trailing_profit_floor_bps"] == pytest.approx(55.0)
    assert result["trailing_profit_floor_gap_bps"] == pytest.approx(75.0)
    assert result["trailing_profit_floor_gap_exit"] is True
    assert result["paper_exit_price"] == pytest.approx(100.798)
    assert result["paper_exit_price_source"] == "PAPER_TRAILING_STOP_PRICE"
    assert result["paper_exit_pnl_bps"] == pytest.approx(79.8)
    assert result["trailing_stop_exit_floor_bps"] == pytest.approx(30.0)
    assert result["trailing_stop_exit_floor_gap_bps"] == pytest.approx(0.0)
    assert result["trailing_stop_mark_price"] == pytest.approx(99.8)
    assert result["trailing_stop_gap_bps"] == pytest.approx(((100.798 - 99.8) / 100.798) * 10000.0)


def test_prior_armed_trailing_stop_blocks_stop_price_below_cost_floor() -> None:
    from app.services.paper_trade_management.position_state import PaperNetPosition

    pos = PaperNetPosition(
        position_id="paper_pos_BTCUSDT",
        symbol="BTCUSDT",
        side="long",
        net_quantity=1.0,
        avg_entry_price=100.0,
        opened_est="2026-06-17T00:00:00Z",
        best_favorable_price=100.7,
        intra_trade_high_price=100.7,
        intra_trade_low_price=100.0,
        last_mark_price=100.7,
        trailing_activation_price=100.42,
        trailing_activation_time="2026-06-17T00:30:00Z",
        trailing_stop_price=100.1965,
        trailing_stop_history=[
            {
                "generated_utc": "2026-06-17T00:30:00Z",
                "activation_price": 100.42,
                "trailing_stop_price": 100.1965,
                "reason": "ADAPTIVE_TRAIL_ARMED_AFTER_NET_PROFIT_FLOOR",
            }
        ],
    )
    config = PaperExitConfig(
        trailing_stop_bps=50.0,
        min_profit_before_trailing_bps=30.0,
        trailing_stop_min_after_cost_buffer_bps=12.0,
        take_profit_bps=99999.0,
        stop_loss_bps=99999.0,
        profit_bank_bps=99999.0,
        profit_lock_bps=99999.0,
    )
    result = evaluate_exit(
        position=pos,
        mark_price=99.8,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        ob_spread_bps=5.0,
    )

    # CG-F015: stop_price clamped to at-cost floor (100.42); trade now exits at floor instead of blocking
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_2_TRAILING_STOP"
    assert result["pnl_bps"] == pytest.approx(-20.0)
    assert result["paper_exit_price"] == pytest.approx(100.42)
    assert result["paper_exit_price_source"] == "PAPER_TRAILING_STOP_PRICE"
    assert result["paper_exit_pnl_bps"] == pytest.approx(42.0)
    assert result["trailing_profit_floor_bps"] == pytest.approx(42.0)
    assert result["trailing_stop_exit_floor_bps"] == pytest.approx(30.0)
    assert result["trailing_stop_exit_floor_gap_bps"] == pytest.approx(0.0)
    assert result["trailing_stop_mark_price"] == pytest.approx(99.8)


def test_prior_armed_trailing_stop_still_blocks_loss_below_profit_floor() -> None:
    from app.services.paper_trade_management.position_state import PaperNetPosition

    pos = PaperNetPosition(
        position_id="paper_pos_BTCUSDT",
        symbol="BTCUSDT",
        side="long",
        net_quantity=1.0,
        avg_entry_price=100.0,
        opened_est="2026-06-17T00:00:00Z",
        best_favorable_price=100.56,
        intra_trade_high_price=100.56,
        intra_trade_low_price=100.0,
        last_mark_price=100.56,
        trailing_activation_price=100.54,
        trailing_activation_time="2026-06-17T00:30:00Z",
        trailing_stop_price=99.35328,
        trailing_stop_history=[
            {
                "generated_utc": "2026-06-17T00:30:00Z",
                "activation_price": 100.54,
                "trailing_stop_price": 99.35328,
                "reason": "ADAPTIVE_TRAIL_ARMED_AFTER_NET_PROFIT_FLOOR",
            }
        ],
    )
    config = PaperExitConfig(
        trailing_stop_bps=120.0,
        min_profit_before_trailing_bps=30.0,
        trailing_stop_min_after_cost_buffer_bps=25.0,
        take_profit_bps=99999.0,
        stop_loss_bps=99999.0,
        profit_bank_bps=99999.0,
        profit_lock_bps=99999.0,
    )
    result = evaluate_exit(
        position=pos,
        mark_price=99.0,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        ob_spread_bps=5.0,
    )

    # CG-F015: stop_price clamped to at-cost floor (100.55); trade now exits at floor instead of blocking
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_2_TRAILING_STOP"
    assert result["pnl_bps"] == pytest.approx(-100.0)
    assert result["paper_exit_price"] == pytest.approx(100.55)
    assert result["paper_exit_pnl_bps"] == pytest.approx(55.0)
    assert result["trailing_profit_floor_bps"] == pytest.approx(55.0)
    assert result["trailing_stop_exit_floor_bps"] == pytest.approx(30.0)
    assert result["trailing_stop_exit_floor_gap_bps"] == pytest.approx(0.0)
    assert result["trailing_stop_mark_price"] == pytest.approx(99.0)


def test_trailing_stop_closes_after_after_cost_profit_floor_is_met() -> None:
    from app.services.paper_trade_management.position_state import PaperNetPosition

    pos = PaperNetPosition(
        position_id="paper_pos_BTCUSDT",
        symbol="BTCUSDT",
        side="long",
        net_quantity=1.0,
        avg_entry_price=100.0,
        opened_est="2026-06-17T00:00:00Z",
        best_favorable_price=101.0,
        intra_trade_high_price=101.0,
        intra_trade_low_price=100.0,
        last_mark_price=101.0,
    )
    config = PaperExitConfig(
        trailing_stop_bps=20.0,
        min_profit_before_trailing_bps=30.0,
        trailing_stop_min_after_cost_buffer_bps=25.0,
        take_profit_bps=99999.0,
        stop_loss_bps=99999.0,
        profit_bank_bps=99999.0,
        profit_lock_bps=99999.0,
    )
    result = evaluate_exit(
        position=pos,
        mark_price=100.7,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        ob_spread_bps=5.0,
    )

    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_2_TRAILING_STOP"
    assert result["pnl_bps"] == pytest.approx(70.0)
    assert result["trailing_profit_floor_bps"] == pytest.approx(55.0)
    assert result["trailing_after_cost_buffer_bps"] == pytest.approx(25.0)


# ── Liquidity-aware TP ────────────────────────────────────────────────────────

def test_tp_skipped_when_spread_too_wide() -> None:
    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None

    config = PaperExitConfig(
        take_profit_bps=120.0,
        profit_bank_bps=180.0,
        stop_loss_bps=80.0,
        max_ob_spread_bps_for_tp=20.0,
        min_hold_seconds=0,
    )
    # PnL at +130 bps (would normally trigger TIER_2_TAKE_PROFIT)
    mark = 100_000.0 * (1 + 130 / 10000.0)
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        ob_spread_bps=35.0,  # wide spread — skip TP
    )
    # Should NOT fire TP (spread too wide)
    assert result.get("close_reason") != "TIER_2_TAKE_PROFIT"


def test_tp_fires_when_spread_acceptable() -> None:
    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None

    config = PaperExitConfig(
        take_profit_bps=120.0,
        profit_bank_bps=180.0,
        stop_loss_bps=80.0,
        max_ob_spread_bps_for_tp=20.0,
        min_hold_seconds=0,
    )
    # PnL at +130 bps with narrow spread
    mark = 100_000.0 * (1 + 130 / 10000.0)
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        ob_spread_bps=5.0,  # tight spread — allow TP
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_2_TAKE_PROFIT"


def test_tp_fires_when_ob_spread_none() -> None:
    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None

    config = PaperExitConfig(
        take_profit_bps=120.0,
        profit_bank_bps=180.0,
        stop_loss_bps=80.0,
        max_ob_spread_bps_for_tp=20.0,
        min_hold_seconds=0,
    )
    mark = 100_000.0 * (1 + 130 / 10000.0)
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        ob_spread_bps=None,  # no spread data — default allow TP
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_2_TAKE_PROFIT"


# ── Existing exit tiers unchanged ─────────────────────────────────────────────

def test_emergency_liquidation_exit_still_fires_tier_0() -> None:
    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None
    pos.liquidation_price_estimate = 98_000.0

    config = PaperExitConfig(
        emergency_liquidation_distance_bps=250.0,
        min_hold_seconds=0,
    )
    result = evaluate_exit(
        position=pos,
        mark_price=99_500.0,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_0_EMERGENCY_LIQUIDATION_DISTANCE"
    assert result["current_liquidation_distance_bps"] == pytest.approx(
        (99_500.0 - 98_000.0) / 99_500.0 * 10000.0
    )


def test_emergency_liquidation_exit_is_side_aware_for_short() -> None:
    pos = _short_position()
    pos.liquidation_price_estimate = 101_000.0

    result = evaluate_exit(
        position=pos,
        mark_price=100_500.0,
        generated_utc="2026-06-17T01:00:00Z",
        config=PaperExitConfig(
            emergency_liquidation_distance_bps=250.0,
            min_hold_seconds=0,
        ),
    )

    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_0_EMERGENCY_LIQUIDATION_DISTANCE"
    assert result["liquidation_price_estimate"] == 101_000.0
    assert result["current_liquidation_distance_bps"] == pytest.approx(
        (101_000.0 - 100_500.0) / 100_500.0 * 10000.0
    )


@pytest.mark.parametrize(
    ("side", "liquidation_price_estimate"),
    (
        ("long", 100_100.0),
        ("short", 99_900.0),
    ),
)
def test_crossed_liquidation_estimate_fails_closed_at_zero_distance(
    side: str,
    liquidation_price_estimate: float,
) -> None:
    pos = _long_position() if side == "long" else _short_position()
    pos.liquidation_price_estimate = liquidation_price_estimate

    result = evaluate_exit(
        position=pos,
        mark_price=100_000.0,
        generated_utc="2026-06-17T01:00:00Z",
        config=PaperExitConfig(
            emergency_liquidation_distance_bps=250.0,
            min_hold_seconds=0,
        ),
    )

    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_0_EMERGENCY_LIQUIDATION_DISTANCE"
    assert result["current_liquidation_distance_bps"] == 0.0


def test_missing_liquidation_estimate_does_not_invent_emergency_distance() -> None:
    pos = _long_position()
    pos.liquidation_price_estimate = None

    result = evaluate_exit(
        position=pos,
        mark_price=100_000.0,
        generated_utc="2026-06-17T01:00:00Z",
        config=PaperExitConfig(
            emergency_liquidation_distance_bps=250.0,
            min_hold_seconds=0,
        ),
    )

    assert result["should_close"] is False
    assert result["close_reason"] is None
    assert "current_liquidation_distance_bps" not in result


def test_zero_long_liquidation_estimate_is_a_distant_valid_boundary() -> None:
    pos = _long_position()
    pos.liquidation_price_estimate = 0.0

    result = evaluate_exit(
        position=pos,
        mark_price=100_000.0,
        generated_utc="2026-06-17T01:00:00Z",
        config=PaperExitConfig(
            emergency_liquidation_distance_bps=250.0,
            min_hold_seconds=0,
        ),
    )

    assert result["should_close"] is False
    assert result["close_reason"] is None


@pytest.mark.parametrize(
    "liquidation_price_estimate",
    (-1.0, float("nan"), float("inf"), float("-inf")),
)
def test_invalid_liquidation_estimate_does_not_invent_emergency_distance(
    liquidation_price_estimate: float,
) -> None:
    pos = _long_position()
    pos.liquidation_price_estimate = liquidation_price_estimate

    result = evaluate_exit(
        position=pos,
        mark_price=100_000.0,
        generated_utc="2026-06-17T01:00:00Z",
        config=PaperExitConfig(
            emergency_liquidation_distance_bps=250.0,
            min_hold_seconds=0,
        ),
    )

    assert result["should_close"] is False
    assert result["close_reason"] is None
    assert "current_liquidation_distance_bps" not in result


def test_confidence_decay_exit_fires() -> None:
    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None

    config = PaperExitConfig(
        confidence_decay_min=0.42,
        stop_loss_bps=80.0,
        min_hold_seconds=0,
    )
    result = evaluate_exit(
        position=pos,
        mark_price=100_000.0,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        model_context={"confidence": 0.30},
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_1_CONFIDENCE_DECAY_EXIT"


def test_catastrophic_floor_stop_fires_without_atr_or_static_stops() -> None:
    """LITUSDT regression (2026-07-06): entry_atr_bps=None + static stops
    disabled left no working stop; MAE reached 610bps. The catastrophic floor
    must fire unconditionally."""
    config = PaperExitConfig(
        static_stop_loss_enabled=False,
        catastrophic_floor_stop_bps=150.0,
        atr_stop_floor_bps=0.0,  # isolate the catastrophic floor
        mfe_breakeven_protection_enabled=False,
        min_hold_seconds=0,
    )
    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None
    mark = 100_000.0 * (1 - 200 / 10000.0)
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=None,
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_0_CATASTROPHIC_FLOOR_STOP"


def test_missing_atr_falls_back_to_floor_stop_when_static_disabled() -> None:
    config = PaperExitConfig(
        static_stop_loss_enabled=False,
        atr_stop_floor_bps=35.0,
        catastrophic_floor_stop_bps=150.0,
        mfe_breakeven_protection_enabled=False,
        min_hold_seconds=0,
    )
    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None
    mark = 100_000.0 * (1 - 40 / 10000.0)
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=None,
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_1_ATR_VOLATILITY_STOP"
    assert result["atr_missing_floor_fallback"] is True
    assert result["atr_stop_bps"] == 35.0


def test_mfe_breakeven_protection_does_not_mislabel_deep_losses() -> None:
    """The breakeven tier must only fire near breakeven; a -286bps position
    must fall through to real stops instead of closing as 'protection'."""
    config = PaperExitConfig(
        static_stop_loss_enabled=False,
        atr_stop_floor_bps=0.0,
        catastrophic_floor_stop_bps=0.0,  # disable stops to observe fall-through
        mfe_breakeven_protection_enabled=True,
        mfe_breakeven_min_mfe_bps=20.0,
        mfe_breakeven_cost_buffer_bps=8.0,
        min_hold_seconds=0,
        trailing_stop_enabled=False,
    )
    pos = _long_position()
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = 100_000.0 * (1 + 35 / 10000.0)  # MFE 35bps, armed
    mark = 100_000.0 * (1 - 286 / 10000.0)
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=None,
    )
    assert result.get("close_reason") != "TIER_2_MFE_BREAKEVEN_PROTECTION"

    # Near breakeven (within 3x cost buffer) it still protects as designed.
    pos2 = _long_position()
    pos2.avg_entry_price = 100_000.0
    pos2.best_favorable_price = 100_000.0 * (1 + 35 / 10000.0)
    mark2 = 100_000.0 * (1 + 5 / 10000.0)
    result2 = evaluate_exit(
        position=pos2,
        mark_price=mark2,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=None,
    )
    assert result2["should_close"] is True
    assert result2["close_reason"] == "TIER_2_MFE_BREAKEVEN_PROTECTION"
