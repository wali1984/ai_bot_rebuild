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
    pos.liquidation_distance_bps = None
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


# ── ATR-based volatility-adjusted stop ────────────────────────────────────────

def test_atr_stop_fires_before_static_stop_loss() -> None:
    pos = _long_position()
    # PnL at -20 bps: below ATR stop (atr_bps=8, multiplier=2 → stop at -16 bps)
    # but above static stop_loss (80 bps)
    pos.avg_entry_price = 100_000.0
    pos.best_favorable_price = None

    config = PaperExitConfig(
        stop_loss_bps=80.0,
        atr_stop_multiplier=2.0,
        min_hold_seconds=0,
    )
    # Simulate PnL by making position's mark_price 20 bps below entry
    mark = 100_000.0 * (1 - 20 / 10000.0)
    result = evaluate_exit(
        position=pos,
        mark_price=mark,
        generated_utc="2026-06-17T01:00:00Z",
        config=config,
        atr_bps=8.0,  # 8 bps ATR → stop at 16 bps
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_1_ATR_VOLATILITY_STOP"
    assert result["atr_bps"] == 8.0


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
    pos.liquidation_distance_bps = 100.0  # close to liquidation

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
