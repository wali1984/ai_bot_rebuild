from __future__ import annotations

from v2.backend.app.services.adaptive_capital_allocator import (
    ADAPTIVE_CAPITAL_POLICY_VERSION,
    AllocationInput,
    RiskEnvelope,
    allocate_live_candidate,
    allocate_paper_candidate,
)


def _row(**overrides) -> AllocationInput:
    values = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "action": "long",
        "price": 100.0,
        "equity": 10000.0,
        "available_margin": 5000.0,
        "wallet_balance": 10000.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": 80.0,
        "market_state_integrity_score": 95.0,
        "volatility_bps": 50.0,
        "liquidity_score": 1.0,
        "spread_bps": 2.0,
        "slippage_bps": 2.0,
        "drawdown_bps": 0.0,
        "symbol_exposure_usdt": 0.0,
        "total_exposure_usdt": 0.0,
        "correlation_exposure_pct": 0.0,
        "regime_score": 1.0,
        "lineage_ids": {"prediction_id": "pred"},
    }
    values.update(overrides)
    return AllocationInput(**values)


def test_high_confidence_and_edge_sizes_larger_than_weak_edge() -> None:
    strong = allocate_paper_candidate(_row(confidence_calibrated=0.85, expected_move_after_cost_bps=90.0))
    weak = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.56,
            expected_move_after_cost_bps=10.0,
            spread_bps=1.0,
            slippage_bps=1.0,
            stop_distance_bps=300.0,
        )
    )

    assert strong.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert weak.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert strong.target_notional_usdt > weak.target_notional_usdt


def test_low_confidence_blocks() -> None:
    result = allocate_paper_candidate(_row(confidence_calibrated=0.49))

    assert result.decision == "BLOCK_LOW_CONFIDENCE"
    assert result.target_notional_usdt == 0.0
    assert result.model_inputs["selected_leverage"] == 1.0
    assert result.model_inputs["leverage_target"] == 1.0
    assert result.model_inputs["leverage_live_mutation_allowed"] is False
    assert result.model_inputs["leverage_selection_reason"] == (
        "blocked_allocation_uses_1x_leverage:confidence_below_adaptive_minimum"
    )
    assert result.model_inputs["selected_margin_mode"] == "isolated_paper_simulated"
    assert result.model_inputs["hedge_budget_selection_reason"] == "hedge_budget_not_required_for_current_risk"


def test_high_volatility_reduces_size() -> None:
    calm = allocate_paper_candidate(_row(volatility_bps=35.0))
    volatile = allocate_paper_candidate(_row(volatility_bps=300.0))

    assert calm.target_notional_usdt > volatile.target_notional_usdt


def test_wide_spread_blocks_when_cost_exceeds_edge() -> None:
    result = allocate_paper_candidate(_row(expected_move_after_cost_bps=8.0, spread_bps=7.0, slippage_bps=2.0))

    assert result.decision == "BLOCK_SPREAD_SLIPPAGE"


def test_paper_short_uses_negative_signed_move_as_positive_economic_edge() -> None:
    result = allocate_paper_candidate(
        _row(
            action="short",
            confidence_calibrated=0.8,
            expected_move_after_cost_bps=-80.0,
            spread_bps=2.0,
            slippage_bps=2.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.expected_move_after_cost_bps == -80.0
    assert result.expected_net_pnl_usd > 0.0
    assert result.model_inputs["signed_expected_move_after_cost_bps"] == -80.0
    assert result.model_inputs["allocator_economic_edge_after_cost_bps"] == 80.0
    assert result.model_inputs["allocator_edge_sign_convention"] == (
        "paper_short_negative_signed_move_is_positive_economic_edge"
    )


def test_paper_short_blocks_positive_signed_move_as_no_edge() -> None:
    result = allocate_paper_candidate(
        _row(
            action="short",
            expected_move_after_cost_bps=80.0,
            spread_bps=2.0,
            slippage_bps=2.0,
        )
    )

    assert result.decision == "BLOCK_NO_EDGE"
    assert result.model_inputs["signed_expected_move_after_cost_bps"] == 80.0
    assert result.model_inputs["allocator_economic_edge_after_cost_bps"] == 0.0


def test_live_allocator_keeps_existing_positive_edge_semantics_for_shorts() -> None:
    result = allocate_live_candidate(_row(action="short", expected_move_after_cost_bps=-80.0))

    assert result.decision == "BLOCK_NO_EDGE"
    assert result.model_inputs["signed_expected_move_after_cost_bps"] == -80.0
    assert result.model_inputs["allocator_economic_edge_after_cost_bps"] == 0.0
    assert result.model_inputs["allocator_edge_sign_convention"] == (
        "live_existing_positive_edge_semantics"
    )


def test_low_liquidity_blocks() -> None:
    result = allocate_paper_candidate(_row(liquidity_score=0.01))

    assert result.decision == "BLOCK_INSUFFICIENT_LIQUIDITY"


def test_drawdown_guard_blocks() -> None:
    result = allocate_paper_candidate(_row(drawdown_bps=600.0))

    assert result.decision == "BLOCK_DRAWDOWN_GUARD"


def test_existing_exposure_reduces_or_blocks_size() -> None:
    no_exposure = allocate_paper_candidate(_row())
    heavy_exposure = allocate_paper_candidate(_row(total_exposure_usdt=5500.0))

    assert heavy_exposure.target_notional_usdt < no_exposure.target_notional_usdt


def test_exchange_min_notional_is_respected() -> None:
    result = allocate_paper_candidate(_row(min_notional=50.0, confidence_calibrated=0.56, expected_move_after_cost_bps=10.0))

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.target_notional_usdt >= 50.0


def test_insufficient_margin_blocks_live_submit() -> None:
    result = allocate_live_candidate(_row(available_margin=0.0))

    assert result.decision == "BLOCK_INSUFFICIENT_MARGIN"


def test_no_fixed_200_usdt_runtime_allocation() -> None:
    result = allocate_paper_candidate(_row())

    assert result.target_notional_usdt != 200.0
    assert result.final_size_reason == "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget"


def test_low_risk_candidate_does_not_reserve_hedge_budget() -> None:
    result = allocate_paper_candidate(_row())

    assert result.hedge_budget_usd == 0.0
    assert result.model_inputs["selected_hedge_budget_pct_of_risk"] == 0.0
    assert result.model_inputs["hedge_budget_selection_reason"] == "hedge_budget_not_required_for_current_risk"


def test_allocator_selects_hedge_budget_from_correlation_and_drawdown_risk() -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.86,
            expected_move_after_cost_bps=95.0,
            correlation_exposure_pct=0.16,
            drawdown_bps=250.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.hedge_budget_usd > 0.0
    assert result.hedge_budget_usd <= round(result.risk_budget_usd * 0.35, 8)
    assert result.model_inputs["selected_hedge_budget_pct_of_risk"] > 0.0
    assert result.model_inputs["hedge_correlation_pressure"] > 0.0
    assert result.model_inputs["hedge_drawdown_pressure"] > 0.0
    assert result.model_inputs["hedge_budget_selection_reason"] == "correlation_drawdown_volatility_cost_pressure"


def test_operator_hedge_budget_floor_is_preserved() -> None:
    result = allocate_paper_candidate(_row(hedge_budget_pct_of_risk=0.2))

    assert result.hedge_budget_usd == round(result.risk_budget_usd * 0.2, 8)
    assert result.model_inputs["selected_hedge_budget_pct_of_risk"] == 0.2
    assert result.model_inputs["hedge_budget_selection_reason"] == "operator_hedge_budget_floor"


def test_paper_and_live_use_same_allocator_contract() -> None:
    row = _row()
    paper = allocate_paper_candidate(row)
    live = allocate_live_candidate(row)

    assert paper.to_payload().keys() == live.to_payload().keys()


def test_all_allowed_allocations_emit_explicit_margin_leverage_and_cost_fields() -> None:
    result = allocate_paper_candidate(_row(confidence_calibrated=0.86, expected_move_after_cost_bps=95.0))
    payload = result.to_payload()

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    for field in (
        "risk_budget_usd",
        "gross_notional_usd",
        "allocated_margin_usd",
        "recommended_leverage",
        "effective_leverage",
        "recommended_margin_mode",
        "stop_distance_bps",
        "liquidation_price_estimate",
        "liquidation_buffer_bps",
        "target_notional_usd",
        "max_loss_if_stop_hit",
        "risk_reward",
        "risk_of_ruin_contribution",
        "portfolio_exposure_after_trade",
        "correlation_exposure_after_trade",
        "expected_fees_usd",
        "expected_slippage_usd",
        "expected_funding_usd",
        "expected_gross_pnl_usd",
        "expected_net_pnl_usd",
        "expected_shortfall_usd",
        "hedge_budget_usd",
        "hedge_action",
        "hedge_reason",
        "cross_margin_stress_used_usd",
        "cross_margin_available_buffer_usd",
        "portfolio_liquidation_buffer_usd",
        "margin_call_risk",
        "capital_allocation_reason",
    ):
        assert field in payload
        assert payload[field] is not None
    assert payload["gross_notional_usd"] == payload["target_notional_usdt"]
    assert payload["target_notional_usd"] == payload["target_notional_usdt"]
    assert payload["adaptive_capital_policy_version"] == ADAPTIVE_CAPITAL_POLICY_VERSION
    assert payload["allocated_margin_usd"] <= payload["gross_notional_usd"]
    assert payload["recommended_margin_mode"] == "isolated_paper_simulated"
    assert payload["capital_allocation_reason"] == result.final_size_reason
    assert payload["max_loss_if_stop_hit"] > 0.0
    assert payload["max_loss_usd"] == payload["max_loss_if_stop_hit"]
    assert payload["stop_loss_usd"] is not None
    assert payload["take_profit_usd"] is not None
    assert payload["liquidation_distance_usd"] is not None
    assert payload["risk_reward"] > 0.0
    assert payload["expected_gross_pnl_usd"] >= payload["expected_net_pnl_usd"]
    assert 0.0 <= payload["risk_of_ruin_contribution"] <= 1.0
    assert payload["portfolio_exposure_after_trade"] >= payload["gross_notional_usd"]
    assert 0.0 <= payload["correlation_exposure_after_trade"] <= 1.0
    assert payload["hedge_action"] in {
        "NO_HEDGE",
        "REDUCE_POSITION",
        "CLOSE_POSITION",
        "PROTECTIVE_HEDGE",
        "PAIR_HEDGE",
        "BETA_HEDGE",
        "MARKET_REGIME_HEDGE",
        "CROSS_MARGIN_RISK_OFF",
    }
    assert payload["cross_margin_safe"] in {True, False}
    assert payload["model_inputs"]["hedge_engine"]["places_real_order"] is False
    assert payload["model_inputs"]["cross_margin_stress"]["exchange_margin_mode_mutation_allowed"] is False


def test_allowed_allocation_payload_exposes_selected_capital_attribution_contract() -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.90,
            expected_move_after_cost_bps=180.0,
            volatility_bps=20.0,
            stop_distance_bps=80.0,
            correlation_exposure_pct=0.08,
            drawdown_bps=120.0,
        )
    )
    payload = result.to_payload()
    model_inputs = payload["model_inputs"]

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert payload["expected_move_after_cost_bps"] == 180.0
    assert payload["gross_notional_usd"] == payload["target_notional_usdt"]
    assert payload["allocated_margin_usd"] == result.allocated_margin_usd
    assert payload["recommended_leverage"] == result.recommended_leverage
    assert payload["recommended_margin_mode"] == result.recommended_margin_mode
    assert payload["hedge_budget_usd"] == result.hedge_budget_usd
    assert model_inputs["selected_allocated_margin_usd"] == payload["allocated_margin_usd"]
    assert model_inputs["selected_leverage"] == payload["recommended_leverage"]
    assert model_inputs["selected_margin_mode"] == payload["recommended_margin_mode"]
    assert model_inputs["selected_hedge_budget_pct_of_risk"] > 0.0
    assert model_inputs["hedge_budget_selection_reason"] == "correlation_drawdown_volatility_cost_pressure"
    assert model_inputs["leverage_selection_reason"]
    assert model_inputs["margin_mode_selection_reason"]
    assert model_inputs["leverage_edge_cost_ratio"] > 0.0
    assert model_inputs["margin_mode_edge_cost_ratio"] > 0.0
    assert model_inputs["hedge_correlation_pressure"] > 0.0
    assert model_inputs["hedge_drawdown_pressure"] > 0.0
    assert model_inputs["leverage_live_mutation_allowed"] is False
    assert model_inputs["margin_mode_live_mutation_allowed"] is False


def test_paper_margin_mode_selects_cross_simulation_for_high_edge_low_pressure() -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=180.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            correlation_exposure_pct=0.0,
            drawdown_bps=0.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_leverage == 3.0
    assert result.recommended_margin_mode == "cross_paper_simulated"
    assert result.cross_margin_safe is True
    assert result.model_inputs["selected_margin_mode"] == "cross_paper_simulated"
    assert result.model_inputs["margin_mode_live_mutation_allowed"] is False
    assert result.model_inputs["margin_mode_selection_reason"] == (
        "paper_cross_margin_simulated_for_high_edge_low_portfolio_pressure"
    )


def test_paper_margin_mode_stays_isolated_under_correlation_pressure() -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=180.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            correlation_exposure_pct=0.12,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_margin_mode == "isolated_paper_simulated"
    assert result.cross_margin_safe is False
    assert result.model_inputs["selected_margin_mode"] == "isolated_paper_simulated"
    assert result.model_inputs["margin_mode_selection_reason"] == "isolated_limits_tail_contagion_for_current_risk"


def test_allocator_emits_protective_hedge_when_net_delta_benefit_is_positive() -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=180.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            correlation_exposure_pct=0.13,
            spread_bps=0.5,
            slippage_bps=0.5,
            fee_bps=0.5,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.hedge_action in {"PROTECTIVE_HEDGE", "REDUCE_POSITION"}
    if result.hedge_action == "PROTECTIVE_HEDGE":
        assert result.hedge_required is True
        assert result.hedge_notional_usd > 0.0
        assert result.hedge_net_benefit_usd > 0.0
        assert result.hedge_exit_plan["status"] == "HEDGE_EXIT_PLAN_ACTIVE"
    assert result.model_inputs["hedge_engine"]["paper_only"] is True


def test_leverage_is_lowest_safe_value_that_supports_margin_budget() -> None:
    tight_margin = allocate_paper_candidate(
        _row(
            available_margin=330.0,
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=120.0,
            stop_distance_bps=80.0,
        )
    )
    ample_margin = allocate_paper_candidate(
        _row(
            available_margin=5000.0,
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=120.0,
            stop_distance_bps=80.0,
        )
    )

    assert tight_margin.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert ample_margin.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert tight_margin.recommended_leverage > ample_margin.recommended_leverage
    assert tight_margin.allocated_margin_usd <= 330.0 * (1.0 - RiskEnvelope().min_available_margin_buffer_pct)


def test_paper_leverage_uses_phase8_target_for_high_confidence_low_volatility_edge() -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=95.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_leverage == 3.0
    assert result.effective_leverage == 3.0
    assert result.allocated_margin_usd < result.gross_notional_usd
    assert result.model_inputs["raw_leverage_target"] == 3.0
    assert result.model_inputs["leverage_target"] == 3.0
    assert result.model_inputs["selected_leverage"] == 3.0
    assert result.model_inputs["leverage_live_mutation_allowed"] is False
    assert result.model_inputs["phase8_leverage_recommendation"]["paper_only"] is True
    assert result.model_inputs["phase8_leverage_recommendation"]["mutates_exchange"] is False


def test_phase6_simulation_fields_scale_with_risk_and_do_not_mutate_live() -> None:
    low_risk = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=95.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            total_exposure_usdt=100.0,
            correlation_exposure_pct=0.01,
        )
    )
    higher_pressure = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=95.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            total_exposure_usdt=100.0,
            correlation_exposure_pct=0.12,
            drawdown_bps=200.0,
        )
    )

    low_payload = low_risk.to_payload()
    pressure_payload = higher_pressure.to_payload()

    assert low_risk.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert higher_pressure.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert low_payload["max_loss_if_stop_hit"] > low_payload["expected_fees_usd"]
    assert low_payload["risk_reward"] == round(
        low_payload["expected_net_pnl_usd"] / low_payload["max_loss_if_stop_hit"],
        8,
    )
    assert low_payload["portfolio_exposure_after_trade"] == (
        low_payload["gross_notional_usd"] + 100.0
    )
    assert pressure_payload["risk_of_ruin_contribution"] > low_payload["risk_of_ruin_contribution"]
    assert pressure_payload["correlation_exposure_after_trade"] > low_payload["correlation_exposure_after_trade"]
    assert pressure_payload["model_inputs"]["leverage_live_mutation_allowed"] is False
    assert pressure_payload["model_inputs"]["margin_mode_live_mutation_allowed"] is False


def test_paper_leverage_stays_at_one_when_after_cost_edge_is_too_small() -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=28.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            spread_bps=1.0,
            slippage_bps=1.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_leverage == 1.0
    assert result.model_inputs["raw_leverage_target"] == 3.0
    assert result.model_inputs["leverage_target"] == 1.0
    assert result.model_inputs["leverage_selection_reason"] == "after_cost_edge_too_small_for_dynamic_leverage"


def test_high_spread_and_funding_pressure_caps_dynamic_leverage() -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.90,
            expected_move_after_cost_bps=120.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            spread_bps=25.0,
            slippage_bps=10.0,
            expected_funding_bps=60.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_leverage == 1.0
    assert result.model_inputs["leverage_target"] == 1.0
    assert result.model_inputs["leverage_cost_drag_bps"] == 99.0
    assert result.model_inputs["leverage_selection_reason"] == "after_cost_edge_too_small_for_dynamic_leverage"


def test_paper_leverage_risk_pressure_caps_high_confidence_target() -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=95.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            correlation_exposure_pct=0.16,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_leverage == 1.0
    assert result.model_inputs["raw_leverage_target"] == 3.0
    assert result.model_inputs["leverage_target"] == 1.0
    assert result.model_inputs["leverage_selection_reason"] == "correlation_pressure_caps_leverage_at_1x"


def test_live_leverage_selection_remains_lowest_safe_without_operator_approval() -> None:
    result = allocate_live_candidate(
        _row(
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=95.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_leverage == 1.0
    assert result.model_inputs["leverage_target"] == 1.0
    assert result.model_inputs["leverage_selection_reason"] == (
        "live_mode_requires_operator_approval_for_dynamic_leverage_change"
    )
    assert result.model_inputs["leverage_live_mutation_allowed"] is False
    assert result.recommended_margin_mode == "isolated"
    assert result.model_inputs["selected_margin_mode"] == "isolated"
    assert result.model_inputs["margin_mode_live_mutation_allowed"] is False
    assert result.model_inputs["margin_mode_selection_reason"] == (
        "live_mode_requires_operator_approval_for_margin_mode_change"
    )


def test_no_safe_liquidation_buffer_blocks_even_when_edge_is_positive() -> None:
    result = allocate_paper_candidate(
        _row(
            available_margin=100.0,
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=120.0,
            stop_distance_bps=6000.0,
        )
    )

    assert result.decision == "BLOCK_LIQUIDATION_RISK"
    assert result.target_notional_usdt == 0.0


def test_risk_envelope_can_veto_allocator_output() -> None:
    result = allocate_paper_candidate(
        _row(risk_veto=True, risk_veto_reason="operator_drawdown_budget_locked"),
        RiskEnvelope(),
    )

    assert result.decision == "BLOCK_EXPOSURE_BUDGET"
    assert result.risk_veto_reason_if_blocked == "operator_drawdown_budget_locked"
