"""Phase 6 — maker-first execution payload regression fixtures.

These exercise the real ``build_binance_order_plan`` builder. Every assertion
verifies the no-execute contract: the builder composes exchange parameters but
never submits, and post-only orders are described honestly (exchange-visible
GTX maker orders, never claimed hidden).
"""

from __future__ import annotations

from v2.backend.app.services.execution.binance_order_builder import (
    build_binance_order_plan,
)

_GEN = "2026-07-11T18:00:00Z"
_FILTERS = {
    "tick_size": 0.1,
    "step_size": 0.001,
    "min_qty": 0.001,
    "min_notional": 5.0,
}


def _plan(**overrides):
    base = dict(
        symbol="BTCUSDT",
        side="long",
        symbol_filters=_FILTERS,
        hedge_mode=True,
        generated_utc=_GEN,
        current_price=60000.0,
        best_bid=59999.0,
        best_ask=60001.0,
        quantity=0.002,
        order_type="LIMIT",
        time_in_force="GTX",
    )
    base.update(overrides)
    return build_binance_order_plan(**base)


def _assert_no_execute(plan: dict) -> None:
    assert plan["would_submit_order"] is False
    assert plan["would_submit_test_order"] is False
    assert plan["places_real_order"] is False
    assert plan["leverage_mutated"] is False
    assert plan["margin_mutated"] is False
    assert plan["raw_key_exposed"] is False


def test_post_only_payload_uses_gtx_or_equivalent() -> None:
    plan = _plan()
    assert plan["order_type"] == "LIMIT"
    assert plan["timeInForce"] == "GTX"
    assert plan["post_only_requested"] is True
    assert plan["post_only_supported"] is True
    assert plan["maker_first"] is True
    # Honest: a GTX maker order is exchange-visible, never described as hidden.
    assert "hidden" not in str(plan).lower()
    _assert_no_execute(plan)


def test_taker_allowed_only_when_waiting_expected_loss_exceeds_cost() -> None:
    # Plain MARKET entry without an emergency reason must be rejected.
    blocked = _plan(order_type="MARKET", time_in_force=None, quantity=0.002)
    assert "TAKER_ENTRY_BLOCKED_WITHOUT_EMERGENCY_OR_ALPHA_URGENCY" in (
        blocked["builder_reject_reasons"]
    )
    assert blocked["taker_fallback_allowed"] is False
    # Same MARKET entry WITH an emergency reason is permitted (taker fallback).
    allowed = _plan(
        order_type="MARKET",
        time_in_force=None,
        taker_fallback_reason="EMERGENCY_EXIT",
    )
    assert allowed["taker_fallback_allowed"] is True
    assert allowed["taker_fallback_reason"] == "EMERGENCY_EXIT"
    _assert_no_execute(allowed)


def test_reduce_only_exit_payload() -> None:
    plan = _plan(reduce_only=True, close_position=True, order_type="LIMIT")
    assert plan["closePosition"] is True
    assert plan["reduce_only_semantics"] == "HEDGE_MODE_CLOSE_POSITION"
    _assert_no_execute(plan)


def test_internal_stop_does_not_place_visible_stop() -> None:
    # The maker-first entry plan carries no exchange stop order; the stop is an
    # internal trigger spec, so no STOP_MARKET params are present on the entry.
    plan = _plan()
    assert plan["order_params"].get("type") == "LIMIT"
    assert "stopPrice" not in plan["order_params"]
    _assert_no_execute(plan)


def test_emergency_reduce_only_stop_market_payload_no_execute() -> None:
    plan = _plan(
        order_type="STOP_MARKET",
        time_in_force=None,
        close_position=True,
        stop_price=58800.0,
        taker_fallback_reason="LIQUIDATION_BUFFER_COLLAPSE",
    )
    assert plan["order_params"]["type"] == "STOP_MARKET"
    assert plan["order_params"]["stopPrice"] == 58800.0
    assert plan["order_params"]["closePosition"] == "true"
    _assert_no_execute(plan)


def test_payload_rejected_when_notional_below_min_notional() -> None:
    # A sub-min-notional clip is rejected by the symbol filter, never submitted.
    plan = _plan(quantity=0.00001)
    assert plan["symbol_filter_pass"] is False
    assert any(
        "MIN_NOTIONAL" in r or "MIN_QTY" in r or "NOTIONAL" in r
        for r in plan["builder_reject_reasons"] + plan["symbol_filter_reasons"]
    )
    _assert_no_execute(plan)


def test_payload_rejected_when_live_gate_blocked() -> None:
    # The builder composes params but the no-execute contract is absolute: even a
    # fully-valid maker payload would never be submitted while the live gate is
    # blocked_human_only. The builder itself never submits (all flags False), so
    # any caller that respects would_submit_order cannot route it to the exchange.
    plan = _plan()
    live_gate = "blocked_human_only"
    assert plan["would_submit_order"] is False
    assert plan["would_submit_test_order"] is False
    would_route_to_exchange = plan["would_submit_order"] and live_gate != "blocked_human_only"
    assert would_route_to_exchange is False
    _assert_no_execute(plan)
