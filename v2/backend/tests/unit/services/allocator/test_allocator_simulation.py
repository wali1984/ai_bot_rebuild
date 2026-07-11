from __future__ import annotations

from v2.backend.app.services.adaptive_capital_allocator import AllocationInput, RiskEnvelope, allocate_paper_candidate
from v2.backend.app.services.allocator import build_allocator_simulation, simulate_hedge_plan
from v2.backend.app.services.hedge_engine import simulate_cross_margin_stress
from v2.backend.app.services.hedge_engine.hedge_cost_benefit import evaluate_hedge_cost_benefit


def _prediction(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "prediction_id": "pred-alloc",
        "signal_id": "sig-alloc",
        "selected_action": "long",
        "price": 50_000.0,
        "expected_edge_after_cost_bps": 150.0,
        "confidence_calibrated": 0.92,
        "market_state_integrity_score": 92.0,
        "volatility_bps": 45.0,
        "spread_bps": 1.0,
        "slippage_bps": 1.0,
        "fee_bps": 2.0,
        "entry_feature_snapshot": {
            "features": {
                "microstructure_trust_score": 0.92,
                "liquidity_score": 0.9,
            },
        },
    }
    payload.update(overrides)
    return payload


def test_allocator_simulation_passes_with_adaptive_usd_packet() -> None:
    packet = build_allocator_simulation(
        {
            "candidate_id": "cand-pass",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "side": "long",
            "expected_net_pnl_usd": 10.0,
            "pre_trade_loss_probability": 0.20,
        },
        prediction=_prediction(),
        account_state={
            "signed_account_read_ok": True,
            "available_margin_usd": 1_000.0,
            "wallet_balance": 1_000.0,
        },
        symbol_filters={"min_qty": "0.0001", "step_size": "0.0001", "min_notional": "5"},
        generated_utc="2026-07-08T21:00:00Z",
    )

    assert packet["allocator_decision_id"].startswith("allocsim_")
    assert packet["allocator_decision"] == "PASS"
    assert packet["recommended_leverage_source"] == "adaptive_simulation"
    assert packet["recommended_margin_mode_source"] == "adaptive_simulation"
    assert packet["recommended_leverage"] > 0.0
    assert packet["recommended_margin_mode"] in {"isolated", "cross_simulated"}
    assert packet["gross_notional_usd"] > 0.0
    assert packet["max_loss_usd"] > 0.0
    assert packet["liquidation_buffer_usd"] > 0.0
    assert packet["routes_to_live"] is False
    assert packet["places_real_order"] is False
    assert packet["uses_static_leverage"] is False
    assert packet["uses_static_margin"] is False
    assert packet["martingale_detected"] is False


def test_allowed_existing_allocator_decision_missing_size_recalculates_paper_size() -> None:
    packet = build_allocator_simulation(
        {
            "candidate_id": "cand-allow-missing-size",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "side": "long",
            "allocator_decision": "ALLOW_WITH_SIZE",
            "allocator_decision_id": "existing-allocator-without-size",
            "recommended_leverage": 3.0,
            "expected_net_pnl_usd": 10.0,
            "expected_max_loss_usd": 1.5,
            "expected_liquidation_buffer_usd": 20.0,
            "pre_trade_loss_probability": 0.20,
        },
        prediction=_prediction(),
        account_state={
            "signed_account_read_ok": True,
            "available_margin_usd": 1_000.0,
            "wallet_balance": 1_000.0,
        },
        symbol_filters={"min_qty": "0.0001", "step_size": "0.0001", "min_notional": "5"},
        generated_utc="2026-07-11T10:00:00Z",
        recalculate_incomplete_existing_allocation=True,
    )

    assert packet["allocator_decision"] == "PASS"
    assert packet["gross_notional_usd"] > 0.0
    assert packet["target_notional_usd"] == packet["gross_notional_usd"]
    assert packet["target_notional_usdt"] == packet["gross_notional_usd"]
    assert packet["recommended_notional_usd"] == packet["gross_notional_usd"]
    assert packet["allocated_margin_usd"] > 0.0
    assert packet["risk_budget_usd"] > 0.0
    assert "ALLOCATOR_TARGET_NOTIONAL_USD_NON_POSITIVE" not in packet["allocator_block_reasons"]


def test_high_loss_probability_shrinks_paper_notional_without_rejecting() -> None:
    base = {
        "candidate_id": "cand-loss-probability-size",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "expected_net_pnl_usd": 10.0,
    }
    low_loss = build_allocator_simulation(
        {**base, "pre_trade_loss_probability": 0.20},
        prediction=_prediction(),
        account_state={
            "signed_account_read_ok": True,
            "available_margin_usd": 1_000.0,
            "wallet_balance": 1_000.0,
        },
        symbol_filters={"min_qty": "0.0001", "step_size": "0.0001", "min_notional": "5"},
        generated_utc="2026-07-11T10:00:00Z",
    )
    elevated_loss = build_allocator_simulation(
        {**base, "pre_trade_loss_probability": 0.70},
        prediction=_prediction(),
        account_state={
            "signed_account_read_ok": True,
            "available_margin_usd": 1_000.0,
            "wallet_balance": 1_000.0,
        },
        symbol_filters={"min_qty": "0.0001", "step_size": "0.0001", "min_notional": "5"},
        generated_utc="2026-07-11T10:00:00Z",
    )

    assert low_loss["allocator_decision"] == "PASS"
    assert elevated_loss["allocator_decision"] == "PASS"
    assert elevated_loss["gross_notional_usd"] < low_loss["gross_notional_usd"]
    assert elevated_loss["loss_probability_size_factor"] < 1.0
    assert elevated_loss["loss_probability_size_reasons"] == [
        "PRE_TRADE_LOSS_PROBABILITY_ELEVATED_CONSERVATIVE_SIZING"
    ]


def test_allocated_margin_derives_from_final_notional_and_leverage() -> None:
    packet = build_allocator_simulation(
        {
            "candidate_id": "cand-margin-derived",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "side": "long",
            "expected_net_pnl_usd": 10.0,
            "pre_trade_loss_probability": 0.70,
            "altdata_reduce_size_score": 0.60,
        },
        prediction=_prediction(expected_edge_after_cost_bps=180.0, volatility_bps=15.0),
        account_state={
            "signed_account_read_ok": True,
            "available_margin_usd": 1_000.0,
            "wallet_balance": 1_000.0,
        },
        symbol_filters={"min_qty": "0.0001", "step_size": "0.0001", "min_notional": "5"},
        generated_utc="2026-07-11T10:00:00Z",
    )

    assert packet["allocator_decision"] == "PASS"
    assert packet["recommended_leverage"] > 1.0
    assert packet["allocated_margin_usd"] == round(
        packet["gross_notional_usd"] / packet["recommended_leverage"],
        8,
    )


def test_allocator_simulation_preserves_positive_short_economic_edge() -> None:
    packet = build_allocator_simulation(
        {
            "candidate_id": "cand-short-positive-economic-edge",
            "symbol": "ENSUSDT",
            "timeframe": "1h",
            "side": "short",
            "current_price": 4.1265,
            "current_price_can_size_trade": True,
            "expected_move_after_cost_bps": 118.47218553813786,
            "expected_net_pnl_usd": 0.594192,
            "expected_max_loss_usd": 2.068686,
            "pre_trade_loss_probability": 0.40,
            "microstructure_trust_score": 0.70891477,
            "confidence_calibrated": 0.60,
        },
        account_state={
            "signed_account_read_ok": True,
            "available_margin_usd": 1_000.0,
            "wallet_balance": 1_000.0,
        },
        symbol_filters={"min_qty": "0.1", "step_size": "0.1", "min_notional": "5"},
        generated_utc="2026-07-09T00:00:00Z",
    )

    assert packet["allocator_decision"] == "PASS"
    assert packet["gross_notional_usd"] > 0.0
    assert packet["expected_net_pnl_usd"] > 0.0
    assert "ALLOCATOR_BLOCK_NO_EDGE" not in packet["allocator_block_reasons"]
    assert packet["market_state_integrity_score"] == 70.891477
    assert packet["market_state_integrity_minimum_score"] == 70.0
    assert packet["model_inputs"]["allocator_economic_edge_after_cost_bps"] > 0.0


def test_allocate_paper_candidate_still_accepts_negative_signed_short_move() -> None:
    result = allocate_paper_candidate(
        AllocationInput(
            symbol="BTCUSDT",
            timeframe="1m",
            action="short",
            price=50_000.0,
            equity=10_000.0,
            available_margin=9_000.0,
            wallet_balance=10_000.0,
            confidence_calibrated=0.80,
            expected_move_after_cost_bps=-42.0,
            market_state_integrity_score=92.0,
            volatility_bps=45.0,
            liquidity_score=0.90,
            spread_bps=1.0,
            slippage_bps=1.0,
            fee_bps=2.0,
            min_qty=0.0001,
            step_size=0.0001,
            min_notional=5.0,
        ),
        RiskEnvelope(),
    )

    payload = result.to_payload()
    assert payload["allocator_decision"] == "ALLOW_WITH_SIZE"
    assert payload["expected_net_pnl_usd"] > 0.0
    assert payload["model_inputs"]["signed_expected_move_after_cost_bps"] == -42.0
    assert payload["model_inputs"]["allocator_economic_edge_after_cost_bps"] == 42.0


def test_allocator_simulation_rejects_non_positive_expected_net() -> None:
    packet = build_allocator_simulation(
        {
            "candidate_id": "cand-reject",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "side": "long",
            "expected_net_pnl_usd": 0.0,
            "pre_trade_loss_probability": 0.20,
        },
        prediction=_prediction(),
        generated_utc="2026-07-08T21:00:00Z",
    )

    assert packet["allocator_decision"] == "REJECT"
    assert "ALLOCATOR_EXPECTED_NET_PNL_USD_NON_POSITIVE" in packet["allocator_block_reasons"]
    assert packet["recommended_margin_mode"] == "none"
    assert packet["recommended_leverage"] == 0.0
    assert packet["hedge_plan"]["hedge_state"] == "NO_HEDGE_PRIMARY_REJECTED"
    assert packet["places_real_order"] is False


def test_allocator_simulation_uses_selected_side_net_usd_over_zero_top_level() -> None:
    packet = build_allocator_simulation(
        {
            "candidate_id": "cand-selected-short-net",
            "symbol": "ARPAUSDT",
            "timeframe": "15m",
            "side": "short",
            "current_price": 0.0087,
            "current_price_can_size_trade": True,
            "expected_net_pnl_usd": 0.0,
            "short_expected_net_pnl_usd": 0.42,
            "expected_short_net_edge_bps": 42.0,
            "expected_max_loss_usd": 0.20,
            "expected_liquidation_buffer_usd": 3.0,
            "pre_trade_loss_probability": 0.20,
        },
        prediction=_prediction(selected_action="short", price=0.0087),
        account_state={
            "signed_account_read_ok": True,
            "available_margin_usd": 1_000.0,
            "wallet_balance": 1_000.0,
        },
        symbol_filters={"min_qty": "1", "step_size": "1", "min_notional": "5"},
        generated_utc="2026-07-09T00:00:00Z",
    )

    assert packet["expected_net_pnl_usd"] > 0.0
    assert "ALLOCATOR_EXPECTED_NET_PNL_USD_NON_POSITIVE" not in packet["allocator_block_reasons"]
    assert packet["places_real_order"] is False


def test_allocator_simulation_zero_notional_cannot_report_positive_expected_net() -> None:
    packet = build_allocator_simulation(
        {
            "candidate_id": "cand-zero-notional",
            "symbol": "APEUSDT",
            "timeframe": "15m",
            "side": "long",
            "allocator_decision": "REJECT",
            "gross_notional_usd": 0.0,
            "expected_net_pnl_usd": 3.0,
            "expected_max_loss_usd": 2.0,
            "liquidation_buffer_usd": 0.0,
        },
        prediction=_prediction(symbol="APEUSDT", price=0.16, expected_net_pnl_usd=3.0),
        generated_utc="2026-07-08T21:00:00Z",
    )

    assert packet["allocator_decision"] == "REJECT"
    assert packet["expected_net_pnl_usd"] == 0.0
    assert "ALLOCATOR_TARGET_NOTIONAL_USD_NON_POSITIVE" in packet["allocator_block_reasons"]
    assert "ALLOCATOR_EXPECTED_NET_PNL_USD_INVALID_WITH_ZERO_NOTIONAL" in packet["allocator_block_reasons"]
    assert packet["places_real_order"] is False


def test_existing_allocator_pass_rejects_missing_usd_risk_fields() -> None:
    packet = build_allocator_simulation(
        {
            "candidate_id": "cand-existing-missing-risk",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "side": "long",
            "allocator_decision": "ALLOW_WITH_SIZE",
            "recommended_leverage": 5.0,
            "recommended_margin_mode": "cross_paper_simulated",
            "gross_notional_usd": 500.0,
        },
        prediction=_prediction(),
        generated_utc="2026-07-08T21:00:00Z",
    )

    assert packet["allocator_decision"] == "REJECT"
    assert packet["recommended_leverage"] == 0.0
    assert packet["recommended_margin_mode"] == "none"
    assert "ALLOCATOR_MAX_LOSS_USD_MISSING" in packet["allocator_block_reasons"]
    assert "ALLOCATOR_LIQUIDATION_BUFFER_USD_MISSING" in packet["allocator_block_reasons"]
    assert "ALLOCATOR_EXPECTED_NET_PNL_USD_MISSING" in packet["allocator_block_reasons"]
    assert packet["routes_to_live"] is False
    assert packet["places_real_order"] is False


def test_hedge_plan_cannot_rescue_rejected_primary_candidate() -> None:
    plan = simulate_hedge_plan(
        candidate={"symbol": "BTCUSDT", "side": "long", "target_notional_usd": 500.0},
        expected_net_pnl_usd=-1.0,
        max_loss_usd=10.0,
        liquidation_buffer_usd=100.0,
        primary_candidate_passed=False,
    )

    assert plan["hedge_required"] is False
    assert plan["hedge_action"] == "NO_HEDGE"
    assert plan["scenarios"]["cash_no_trade"]["hedge_reason"] == "cash_no_trade_hedge_when_primary_not_passed"
    assert plan["routes_to_live"] is False
    assert plan["places_real_order"] is False


def test_hedge_first_positive_hedge_ev_selects_protective_hedge() -> None:
    plan = simulate_hedge_plan(
        candidate={"symbol": "BTCUSDT", "side": "long", "target_notional_usd": 500.0},
        equity_usd=1_000.0,
        risk_budget_usd=100.0,
        hedge_budget_usd=20.0,
        max_loss_usd=50.0,
        expected_net_pnl_usd=10.0,
        spread_bps=0.5,
        slippage_bps=0.5,
        fee_bps=0.5,
        correlation_exposure_pct=0.13,
        liquidation_buffer_usd=100.0,
        primary_candidate_passed=True,
        hedge_mode_supported=True,
    )

    assert plan["hedge_action"] == "PROTECTIVE_HEDGE"
    assert plan["hedge_required"] is True
    assert plan["hedge_side"] == "short"
    assert plan["hedge_notional_usd"] > 0.0
    assert plan["hedge_max_loss_reduction_usd"] > plan["hedge_expected_cost_usd"]
    assert plan["places_real_order"] is False


def test_hedge_first_high_cost_reduces_instead_of_hedging() -> None:
    plan = simulate_hedge_plan(
        candidate={"symbol": "BTCUSDT", "side": "long", "target_notional_usd": 500.0},
        equity_usd=1_000.0,
        risk_budget_usd=100.0,
        hedge_budget_usd=20.0,
        max_loss_usd=50.0,
        expected_net_pnl_usd=10.0,
        spread_bps=500.0,
        slippage_bps=500.0,
        fee_bps=500.0,
        correlation_exposure_pct=0.13,
        liquidation_buffer_usd=100.0,
        primary_candidate_passed=True,
        hedge_mode_supported=True,
    )

    assert plan["hedge_action"] == "REDUCE_POSITION"
    assert plan["hedge_required"] is False
    assert plan["hedge_notional_usd"] == 0.0
    assert "HEDGE_COST_EXCEEDS_EXPECTED_RISK_REDUCTION" in plan["hedge_reason"]


def test_hedge_first_same_direction_averaging_down_is_rejected() -> None:
    result = evaluate_hedge_cost_benefit(
        {"hedge_notional_usd": 100.0},
        exposure={"gross_exposure_usd": 500.0, "net_delta_usd": 250.0},
        max_loss_usd=50.0,
        spread_bps=0.5,
        slippage_bps=0.5,
        fee_bps=0.5,
        funding_bps=0.0,
        liquidation_buffer_usd=100.0,
        same_direction_as_candidate=True,
    )

    assert result["hedge_allowed"] is False
    assert "HEDGE_LOOKS_LIKE_AVERAGING_DOWN" in result["hedge_reject_reasons"]


def test_hedge_first_exit_dominates_when_no_edge() -> None:
    plan = simulate_hedge_plan(
        candidate={"symbol": "BTCUSDT", "side": "long", "target_notional_usd": 500.0},
        equity_usd=1_000.0,
        risk_budget_usd=100.0,
        hedge_budget_usd=20.0,
        max_loss_usd=50.0,
        expected_net_pnl_usd=-1.0,
        spread_bps=0.5,
        slippage_bps=0.5,
        fee_bps=0.5,
        correlation_exposure_pct=0.13,
        liquidation_buffer_usd=100.0,
        primary_candidate_passed=True,
        hedge_mode_supported=True,
    )

    assert plan["hedge_action"] == "REDUCE_POSITION"
    assert plan["hedge_required"] is False
    assert plan["hedge_reason"] == "no_positive_edge_reduce_before_hedge"
    assert plan["hedge_notional_usd"] == 0.0


def test_cross_margin_buffer_decreases_with_new_position() -> None:
    small = simulate_cross_margin_stress(
        equity_usd=1_000.0,
        available_margin_usd=900.0,
        target_notional_usd=100.0,
        allocated_margin_usd=50.0,
        recommended_leverage=2.0,
        max_loss_usd=5.0,
        requested_margin_mode="cross_paper_simulated",
    )
    large = simulate_cross_margin_stress(
        equity_usd=1_000.0,
        available_margin_usd=900.0,
        target_notional_usd=400.0,
        allocated_margin_usd=200.0,
        recommended_leverage=2.0,
        max_loss_usd=20.0,
        requested_margin_mode="cross_paper_simulated",
    )

    assert large["portfolio_liquidation_buffer_usd"] < small["portfolio_liquidation_buffer_usd"]
    assert large["cross_margin_available_buffer_usd"] < small["cross_margin_available_buffer_usd"]


def test_cross_margin_blocks_if_buffer_too_low() -> None:
    stress = simulate_cross_margin_stress(
        equity_usd=100.0,
        available_margin_usd=8.0,
        target_notional_usd=500.0,
        allocated_margin_usd=250.0,
        recommended_leverage=2.0,
        max_loss_usd=9.0,
        requested_margin_mode="cross_paper_simulated",
    )

    assert stress["cross_margin_safe"] is False
    assert stress["recommended_margin_mode"] == "isolated_paper_simulated"
    assert stress["margin_call_risk"] == "HIGH"


def test_cross_margin_hedge_improves_buffer_when_correlation_valid() -> None:
    unhedged = simulate_cross_margin_stress(
        equity_usd=1_000.0,
        available_margin_usd=900.0,
        target_notional_usd=500.0,
        allocated_margin_usd=250.0,
        recommended_leverage=2.0,
        max_loss_usd=60.0,
        requested_margin_mode="cross_paper_simulated",
    )
    hedged = simulate_cross_margin_stress(
        equity_usd=1_000.0,
        available_margin_usd=900.0,
        target_notional_usd=500.0,
        allocated_margin_usd=250.0,
        recommended_leverage=2.0,
        max_loss_usd=60.0,
        hedge_plan={
            "hedge_required": True,
            "hedge_expected_risk_reduction_usd": 40.0,
            "hedge_margin_usd": 5.0,
            "hedge_cost_usd": 1.0,
            "hedge_increases_liquidation_risk": False,
        },
        requested_margin_mode="cross_paper_simulated",
    )

    assert hedged["cross_margin_hedge_risk_reduction_usd"] == 40.0
    assert hedged["portfolio_liquidation_buffer_usd"] > unhedged["portfolio_liquidation_buffer_usd"]
