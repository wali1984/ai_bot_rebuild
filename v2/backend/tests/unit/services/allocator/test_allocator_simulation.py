from __future__ import annotations

from v2.backend.app.services.allocator import build_allocator_simulation, simulate_hedge_plan


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
