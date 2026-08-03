from __future__ import annotations

import math

import pytest

from v2.backend.app.services.trade_management_paper.service import (
    PaperPositionSnapshot,
    TradeManagementPaperService,
    churn_veto,
    compute_dynamic_stop_plan,
    compute_dynamic_take_profit_ladder,
    compute_stealth_stop_schedule,
    evaluate_fee_ratio_gate,
    evaluate_hedge_dca,
)


def _snap(side: str = "long", age: int = 0, atr_pct: float | None = 0.01) -> PaperPositionSnapshot:
    return PaperPositionSnapshot(
        symbol="BTCUSDT",
        side=side,
        entry_price=100.0,
        current_price=100.0,
        atr_pct=atr_pct,
        age_seconds=age,
    )


def test_stealth_stop_long_is_below_entry() -> None:
    s = compute_stealth_stop_schedule(_snap(side="long"))
    assert s.initial_stop_price < 100.0
    assert s.trailing_buffer_bps > 0


def test_stealth_stop_short_is_above_entry() -> None:
    s = compute_stealth_stop_schedule(_snap(side="short"))
    assert s.initial_stop_price > 100.0


def test_stealth_stop_buffer_decays_with_age() -> None:
    young = compute_stealth_stop_schedule(_snap(side="long", age=0), time_decay_seconds=1800)
    old = compute_stealth_stop_schedule(_snap(side="long", age=1800), time_decay_seconds=1800)
    assert old.trailing_buffer_bps <= young.trailing_buffer_bps


def test_dynamic_stop_falls_back_when_atr_missing() -> None:
    plan = compute_dynamic_stop_plan(_snap(atr_pct=None), atr_multiplier=2.0)
    assert plan.stop_price < 100.0
    assert plan.stop_price > 90.0  # fallback default 1% * 2.0 = 2% drop


def test_dynamic_stop_uses_atr_when_present() -> None:
    plan = compute_dynamic_stop_plan(_snap(atr_pct=0.02), atr_multiplier=2.5)
    # expected stop_distance = 0.02 * 2.5 = 0.05 → price * (1-0.05) = 95
    assert math.isclose(plan.stop_price, 95.0, rel_tol=1e-6)


def test_take_profit_ladder_rungs_sum_to_one() -> None:
    ladder = compute_dynamic_take_profit_ladder(_snap())
    total = sum(frac for _, frac in ladder.rungs)
    assert math.isclose(total, 1.0, rel_tol=1e-6)


def test_take_profit_ladder_long_rungs_above_entry() -> None:
    ladder = compute_dynamic_take_profit_ladder(_snap(side="long"))
    assert all(price > 100.0 for price, _ in ladder.rungs)


def test_take_profit_ladder_short_rungs_below_entry() -> None:
    ladder = compute_dynamic_take_profit_ladder(_snap(side="short"))
    assert all(price < 100.0 for price, _ in ladder.rungs)


def test_churn_veto_blocks_too_soon() -> None:
    r = churn_veto(seconds_since_last_close=10, minimum_hold_seconds=300)
    assert r.blocked is True
    assert "BLOCKED_BY_MINIMUM_HOLD" in r.reason


def test_churn_veto_allows_after_minimum_hold() -> None:
    r = churn_veto(seconds_since_last_close=600, minimum_hold_seconds=300)
    assert r.blocked is False
    assert r.reason == "ALLOWED"


def test_fee_ratio_gate_blocks_when_expected_move_missing() -> None:
    r = evaluate_fee_ratio_gate(fee_bps=8.0, expected_move_after_cost_bps=None)
    assert r.blocked is True
    assert "MISSING_EXPECTED_MOVE" in r.reason


def test_fee_ratio_gate_blocks_when_ratio_too_high() -> None:
    r = evaluate_fee_ratio_gate(fee_bps=8.0, expected_move_after_cost_bps=10.0, max_ratio=0.5)
    assert r.blocked is True
    assert r.ratio is not None and r.ratio > 0.5


def test_fee_ratio_gate_allows_when_ratio_low() -> None:
    r = evaluate_fee_ratio_gate(fee_bps=2.0, expected_move_after_cost_bps=20.0, max_ratio=0.5)
    assert r.blocked is False
    assert r.reason == "ALLOWED"


def test_hedge_dca_evaluator_is_fail_closed() -> None:
    r = evaluate_hedge_dca(request={"symbol": "BTCUSDT", "side": "long"})
    assert r.allowed is False
    assert r.classification == "FAIL_CLOSED_STUB"


def test_service_plan_for_position_returns_full_structure() -> None:
    svc = TradeManagementPaperService()
    plan = svc.plan_for_position(_snap())
    assert "stealth_stop" in plan and "dynamic_stop" in plan and "take_profit_ladder" in plan


def test_service_evaluate_pre_trade_blocks_when_either_gate_blocks() -> None:
    svc = TradeManagementPaperService()
    result = svc.evaluate_pre_trade(
        seconds_since_last_close=10,
        fee_bps=2.0,
        expected_move_after_cost_bps=20.0,
    )
    assert result["allowed"] is False  # churn blocks
    result2 = svc.evaluate_pre_trade(
        seconds_since_last_close=600,
        fee_bps=15.0,
        expected_move_after_cost_bps=10.0,
    )
    assert result2["allowed"] is False  # fee ratio blocks


def test_service_evaluate_pre_trade_allows_when_both_clear() -> None:
    svc = TradeManagementPaperService()
    result = svc.evaluate_pre_trade(
        seconds_since_last_close=600,
        fee_bps=2.0,
        expected_move_after_cost_bps=20.0,
    )
    assert result["allowed"] is True


def test_status_payload_holds_safety_invariants() -> None:
    svc = TradeManagementPaperService()
    s = svc.current_paper_only_status()
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["approves_live"] is False
    assert s["approves_canary"] is False
    assert s["approves_legacy_shutdown"] is False
    assert s["approves_redis_trim"] is False
    assert s["scope"] == "PAPER_ONLY"
    assert s["migration_classification"] == "PARTIALLY_MIGRATED"
    assert isinstance(s["components_ported"], list) and len(s["components_ported"]) >= 6
    assert isinstance(s["components_missing"], list) and len(s["components_missing"]) >= 5


def test_status_payload_cites_legacy_sha256() -> None:
    svc = TradeManagementPaperService()
    s = svc.current_paper_only_status()
    cits = s["legacy_sha256_citations"]
    assert "trading/stealth_stops.py" in cits
    assert len(cits["trading/stealth_stops.py"]["sha256"]) == 64
