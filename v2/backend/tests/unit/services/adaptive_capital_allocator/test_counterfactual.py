from __future__ import annotations

from v2.backend.app.services.adaptive_capital_allocator.counterfactual import (
    CounterfactualRiskEnvelope,
    run_counterfactual_sweep,
    run_rare_event_capital_stress,
    run_runtime_allocation_rare_event_stress,
)


def _candidate(**overrides):
    row = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "confidence_calibrated": 0.86,
        "expected_move_after_cost_bps": 90.0,
        "allocator_decision": "ALLOW_WITH_SIZE",
        "gross_notional_usd": 500.0,
        "orderbook_depth_usd": 2000.0,
        "realized_pnl_usd": 8.0,
        "actual_observed_spread_entry_bps": 2.0,
        "expected_slippage_bps": 2.0,
        "fee_bps": 4.0,
        "expected_funding_bps": 0.0,
        "maintenance_margin_rate": 0.005,
        "entry_atr_bps": 30.0,
        "mfe_bps": 120.0,
        "mae_bps": 25.0,
        "decision_time": "2026-06-19T12:00:00Z",
        "available_at": "2026-06-19T11:59:00Z",
        "generated_at": "2026-06-19T11:58:00Z",
        "feature_cutoff": "2026-06-19T11:55:00Z",
        "entry_feature_candle_closed_confirmed": True,
    }
    row.update(overrides)
    return row


def test_counterfactual_sweep_selects_best_event_time_valid_configuration() -> None:
    sweep = run_counterfactual_sweep([_candidate()])

    assert sweep["status"] == "PASSED"
    assert sweep["source_coverage_required_for_pass"] is False
    assert sweep["source_coverage"]["source_coverage_status"] == "NO_GO_COUNTERFACTUAL_SOURCE_COVERAGE_INCOMPLETE"
    assert sweep["source_coverage"]["required_timeframes"] == ["1m", "5m", "15m", "1h", "4h"]
    assert sweep["event_time_valid_candidate_count"] == 1
    assert sweep["sweep_result_count"] > 0
    assert sweep["a_grade_readiness"]["source_kind_counts"] == {"__unspecified__": 1}
    readiness = sweep["a_grade_readiness"]["source_kind_readiness"]["__unspecified__"]
    assert readiness["a_grade_before_temporal_count"] == 1
    assert readiness["event_time_valid_candidate_count"] == 1
    assert readiness["best_configuration_count"] == 1
    assert readiness["confidence_gap_to_threshold"] == 0.0
    # 2026-07-16 deliberate grid expansion (paper 1000x research target):
    # 6 notional multipliers x 5 leverage values x 2 margin modes x
    # 5 stop multipliers x 4 take-profit plans x 2 hedge flags = 2400.
    assert sweep["config_space_audit"]["per_candidate_theoretical_configuration_count"] == 2400
    assert sweep["config_space_audit"]["candidate_count"] == 1
    assert sweep["config_space_audit"]["theoretical_configuration_count"] == 2400
    assert sweep["config_space_audit"]["considered_count"] == 2400
    assert sweep["config_space_audit"]["feasible_count"] == sweep["sweep_result_count"]
    assert sweep["config_space_audit"]["pruned_count"] == sweep["config_space_audit"]["pruned_configuration_count"]
    assert sweep["config_space_audit"]["configuration_count_reconciled"] is True
    assert sweep["config_space_audit"]["feasible_plus_pruned_reconciled"] is True
    assert sweep["config_space_audit"]["feasible_configuration_count"] == sweep["sweep_result_count"]
    assert sweep["config_space_audit"][
        "feasible_rows_materialized_across_candidates"
    ] is False
    assert sweep["config_space_audit"]["feasible_rows_aggregated_streaming"] is True
    assert sweep["hedge_accounting_audit"]["configuration_count"] == sweep[
        "sweep_result_count"
    ]
    axis_coverage = sweep["config_space_audit"]["axis_value_coverage"]
    assert axis_coverage["theoretical_axis_values"] == {
        "notional_multipliers": [0.25, 0.5, 1.0, 2.0, 3.0, 5.0],
        "leverage_values": [1.0, 2.0, 5.0, 10.0, 20.0],
        "margin_modes": ["isolated", "cross"],
        "stop_multipliers": [0.5, 0.75, 1.0, 1.5, 2.0],
        "take_profit_plans": ["none", "one_r", "two_r", "three_r"],
        "hedge_flags": [False, True],
    }
    # The expanded grid deliberately explores past the risk envelope; the
    # envelope must still fail-close the aggressive tail, so full feasible
    # axis coverage is impossible by construction: leverage values above
    # max_effective_leverage (3.0) are pruned and the 5x notional multiplier
    # breaches depth capacity for this order book.
    assert axis_coverage["full_feasible_axis_value_coverage"] is False
    assert axis_coverage["feasible_axis_values"]["notional_multipliers"] == [0.25, 0.5, 1.0, 2.0, 3.0]
    assert axis_coverage["feasible_axis_values"]["leverage_values"] == [1.0, 2.0]
    assert all(value <= 3.0 for value in axis_coverage["feasible_axis_values"]["leverage_values"])
    assert axis_coverage["feasible_axis_values"]["margin_modes"] == ["cross", "isolated"]
    assert axis_coverage["feasible_axis_values"]["take_profit_plans"] == ["none", "one_r", "three_r", "two_r"]
    assert axis_coverage["feasible_axis_values"]["hedge_flags"] == [False, True]
    assert axis_coverage["observed_axis_value_counts"] == {
        "notional_multipliers": 5,
        "leverage_values": 2,
        "margin_modes": 2,
        "stop_distance_bps_values": 5,
        "take_profit_plans": 4,
        "hedge_flags": 2,
    }
    assert axis_coverage["required_axis_value_counts"] == {
        "notional_multipliers": 6,
        "leverage_values": 5,
        "margin_modes": 2,
        "stop_distance_bps_values": 5,
        "take_profit_plans": 4,
        "hedge_flags": 2,
    }
    candidate_audit = sweep["config_space_audit"]["candidate_configuration_audit_sample"][0]
    assert candidate_audit["axis_count"] == 6
    assert candidate_audit["configurations_considered_count"] == 2400
    assert candidate_audit["considered_count"] == 2400
    # Every configuration that breached the envelope or the order book must be
    # pruned with an explicit, auditable reason (fail-closed exploration).
    assert candidate_audit["pruned_reason_counts"] == {
        "DEPTH_CAPACITY_EXCEEDED": 400,
        "EFFECTIVE_LEVERAGE_LIMIT_BREACH": 1200,
    }
    assert candidate_audit["feasible_count"] == candidate_audit["feasible_configuration_count"]
    assert candidate_audit["pruned_count"] == candidate_audit["pruned_configuration_count"]
    assert candidate_audit["configuration_count_reconciled"] is True
    assert candidate_audit["feasible_plus_pruned_reconciled"] is True
    assert candidate_audit["axis_value_coverage"] == axis_coverage
    assert sweep["hedge_accounting_audit"]["status"] == "PASSED"
    assert sweep["hedge_accounting_audit"]["hedge_enabled_configuration_count"] > 0
    assert sweep["hedge_accounting_audit"]["hedge_disabled_configuration_count"] > 0
    assert (
        sweep["hedge_accounting_audit"]["hedge_budget_positive_count"]
        == sweep["hedge_accounting_audit"]["hedge_enabled_configuration_count"]
    )
    assert (
        sweep["hedge_accounting_audit"]["expected_shortfall_reduced_count"]
        == sweep["hedge_accounting_audit"]["hedge_enabled_configuration_count"]
    )
    assert sweep["hedge_accounting_audit"]["max_hedge_budget_usd"] > 0.0
    assert sweep["hedge_accounting_audit"]["max_hedge_cost_usd"] > 0.0
    assert sweep["hedge_accounting_audit"]["hedge_tail_loss_reduction_factors"] == [0.75, 1.0]
    assert sweep["best_configuration_count"] == 1
    selected = sweep["best_configurations_sample"][0]["selected"]
    assert selected["expected_log_growth"] > 0
    assert selected["margin_mode"] in {"isolated", "cross"}
    assert selected["gross_notional_usd"] > 0
    assert selected["market_depth_capacity_usd"] == 2000.0
    assert selected["market_depth_source"] == "orderbook_depth_usd"
    assert selected["market_depth_utilization_pct"] > 0
    assert selected["market_cost_evidence_sources"] == {
        "fee_bps": "fee_bps",
        "funding_bps": "expected_funding_bps",
        "slippage_bps": "expected_slippage_bps",
        "spread_bps": "actual_observed_spread_entry_bps",
    }
    assert selected["hedge_budget_usd"] >= 0.0
    assert selected["hedge_cost_bps"] >= 0.0
    assert selected["hedge_cost_usd"] >= 0.0
    assert selected["unhedged_expected_shortfall_usd"] >= selected["expected_shortfall_usd"]
    assert selected["hedge_tail_loss_reduction_factor"] in {0.75, 1.0}
    assert sweep["config_axes"]["hedge_budget_model"] == {
        "hedge_cost_bps_when_enabled": 3.0,
        "tail_loss_reduction_factor_when_enabled": 0.75,
        "hedge_budget_usd_formula": "unhedged_expected_shortfall_usd - expected_shortfall_usd",
    }
    assert sweep["config_axes"]["margin_modes"] == ["isolated", "cross"]
    assert sweep["config_axes"]["hedge_flags"] == [False, True]
    assert selected["liquidation_buffer_bps"] >= CounterfactualRiskEnvelope().min_liquidation_buffer_bps


def test_counterfactual_sweep_prunes_every_configuration_without_maintenance_evidence() -> None:
    candidate = _candidate()
    candidate.pop("maintenance_margin_rate")

    sweep = run_counterfactual_sweep([candidate])

    assert sweep["sweep_result_count"] == 0
    audit = sweep["config_space_audit"]["candidate_configuration_audit_sample"][0]
    assert audit["feasible_configuration_count"] == 0
    assert audit["pruned_configuration_count"] == audit["theoretical_configuration_count"]
    assert audit["pruned_reason_counts"] == {
        "MISSING_OR_INVALID_MAINTENANCE_MARGIN_RATE": audit[
            "theoretical_configuration_count"
        ]
    }


def test_counterfactual_sweep_rejects_out_of_contract_maintenance_rate() -> None:
    sweep = run_counterfactual_sweep([_candidate(maintenance_margin_rate=0.0)])

    assert sweep["sweep_result_count"] == 0
    audit = sweep["config_space_audit"]["candidate_configuration_audit_sample"][0]
    assert audit["pruned_reason_counts"] == {
        "MISSING_OR_INVALID_MAINTENANCE_MARGIN_RATE": audit[
            "theoretical_configuration_count"
        ]
    }


def test_counterfactual_sweep_honors_explicit_source_kind_override() -> None:
    sweep = run_counterfactual_sweep([
        _candidate(counterfactual_source_kind="prediction"),
    ])

    assert sweep["status"] == "PASSED"
    assert sweep["source_coverage"]["source_kind_counts"] == {"prediction": 1}
    assert sweep["a_grade_readiness"]["source_kind_counts"] == {"prediction": 1}
    readiness = sweep["a_grade_readiness"]["source_kind_readiness"]["prediction"]
    assert readiness["a_grade_before_temporal_count"] == 1
    assert readiness["event_time_valid_candidate_count"] == 1
    assert readiness["best_configuration_count"] == 1


def test_counterfactual_sweep_supports_explicit_diagnostic_confidence_threshold() -> None:
    sweep = run_counterfactual_sweep([
        _candidate(confidence_calibrated=0.70),
    ], confidence_threshold=0.65)

    assert sweep["status"] == "PASSED"
    assert sweep["a_grade_thresholds"]["confidence_min"] == 0.65
    assert sweep["a_grade_readiness"]["confidence_threshold"] == 0.65
    readiness = sweep["a_grade_readiness"]["source_kind_readiness"]["__unspecified__"]
    assert readiness["confidence_at_or_above_threshold_count"] == 1
    assert readiness["a_grade_before_temporal_count"] == 1
    assert readiness["event_time_valid_candidate_count"] == 1
    assert readiness["best_configuration_count"] == 1


def test_counterfactual_sweep_can_require_full_observed_symbol_timeframe_coverage() -> None:
    sweep = run_counterfactual_sweep([_candidate()], require_full_source_coverage=True)

    assert sweep["status"] == "NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE"
    assert sweep["counterfactual_blocker_reasons"] == [
        "COUNTERFACTUAL_SOURCE_COVERAGE_INCOMPLETE",
    ]
    assert sweep["source_coverage_required_for_pass"] is True
    assert sweep["source_coverage"]["source_symbol_count"] == 1
    assert sweep["source_coverage"]["required_symbol_timeframe_cell_count"] == 5
    assert sweep["source_coverage"]["observed_required_symbol_timeframe_cell_count"] == 1
    assert sweep["source_coverage"]["missing_required_symbol_timeframe_cell_count"] == 4
    assert sweep["best_configuration_count"] == 1


def test_counterfactual_sweep_passes_full_observed_symbol_timeframe_coverage() -> None:
    rows = [_candidate(timeframe=timeframe) for timeframe in ("1m", "5m", "15m", "1h", "4h")]

    sweep = run_counterfactual_sweep(rows, require_full_source_coverage=True)

    assert sweep["status"] == "PASSED"
    assert sweep["counterfactual_blocker_reasons"] == []
    assert sweep["source_coverage"]["source_coverage_status"] == "PASSED"
    assert sweep["source_coverage"]["required_symbol_timeframe_cell_count"] == 5
    assert sweep["source_coverage"]["observed_required_symbol_timeframe_cell_count"] == 5
    assert sweep["source_coverage"]["missing_required_symbol_timeframe_cell_count"] == 0
    assert sweep["event_time_valid_candidate_count"] == 5
    assert sweep["best_configuration_count"] == 5


def test_counterfactual_sweep_converts_usd_cost_evidence_to_bps() -> None:
    candidate = _candidate()
    for field in ("expected_slippage_bps", "fee_bps", "expected_funding_bps"):
        candidate.pop(field)
    candidate.update({
        "expected_slippage_usd": 0.2,
        "expected_fees_usd": 0.4,
        "expected_funding_usd": 0.0,
    })

    sweep = run_counterfactual_sweep([candidate])

    assert sweep["status"] == "PASSED"
    selected = sweep["best_configurations_sample"][0]["selected"]
    assert selected["slippage_bps"] == 4.0
    assert selected["fee_bps"] == 8.0
    assert selected["funding_bps"] == 0.0
    assert selected["market_cost_evidence_sources"] == {
        "fee_bps": "expected_fees_usd",
        "funding_bps": "expected_funding_usd",
        "slippage_bps": "expected_slippage_usd",
        "spread_bps": "actual_observed_spread_entry_bps",
    }


def test_counterfactual_sweep_accepts_nested_adaptive_allocation_notional_and_costs() -> None:
    candidate = _candidate()
    for field in (
        "gross_notional_usd",
        "notional",
        "notional_usdt",
        "expected_slippage_bps",
        "fee_bps",
        "expected_funding_bps",
    ):
        candidate.pop(field, None)
    candidate["adaptive_allocation"] = {
        "target_notional_usdt": 500.0,
        "expected_slippage_usd": 0.2,
        "expected_fees_usd": 0.4,
        "expected_funding_usd": 0.0,
    }

    sweep = run_counterfactual_sweep([candidate])

    assert sweep["status"] == "PASSED"
    assert sweep["event_time_valid_candidate_count"] == 1
    assert sweep["best_configuration_count"] == 1
    selected = sweep["best_configurations_sample"][0]["selected"]
    assert selected["gross_notional_usd"] > 0.0
    assert selected["market_cost_evidence_sources"] == {
        "fee_bps": "expected_fees_usd",
        "funding_bps": "expected_funding_usd",
        "slippage_bps": "expected_slippage_usd",
        "spread_bps": "actual_observed_spread_entry_bps",
    }
    assert selected["slippage_bps"] == 4.0
    assert selected["fee_bps"] == 8.0
    assert selected["funding_bps"] == 0.0


def test_counterfactual_sweep_accepts_allocator_model_input_fee_and_funding_bps() -> None:
    candidate = _candidate()
    for field in ("fee_bps", "expected_funding_bps"):
        candidate.pop(field, None)
    candidate["adaptive_allocation"] = {
        "model_inputs": {
            "fee_bps": 4.0,
            "expected_funding_bps": 0.25,
        },
    }

    sweep = run_counterfactual_sweep([candidate])

    assert sweep["status"] == "PASSED"
    selected = sweep["best_configurations_sample"][0]["selected"]
    assert selected["fee_bps"] == 4.0
    assert selected["funding_bps"] == 0.25
    assert selected["market_cost_evidence_sources"] == {
        "fee_bps": "adaptive_allocation.model_inputs.fee_bps",
        "funding_bps": "adaptive_allocation.model_inputs.expected_funding_bps",
        "slippage_bps": "expected_slippage_bps",
        "spread_bps": "actual_observed_spread_entry_bps",
    }


def test_counterfactual_sweep_converts_explicit_rate_and_estimated_bps_aliases() -> None:
    candidate = _candidate()
    for field in ("expected_slippage_bps", "fee_bps", "expected_funding_bps"):
        candidate.pop(field, None)
    candidate.update({
        "estimated_slippage_bps": 1.5,
        "fee_rate": 0.0004,
        "funding_rate": -0.000025,
    })

    sweep = run_counterfactual_sweep([candidate])

    assert sweep["status"] == "PASSED"
    selected = sweep["best_configurations_sample"][0]["selected"]
    assert selected["slippage_bps"] == 1.5
    assert selected["fee_bps"] == 4.0
    assert selected["funding_bps"] == 0.25
    assert selected["market_cost_evidence_sources"] == {
        "fee_bps": "fee_rate",
        "funding_bps": "funding_rate",
        "slippage_bps": "estimated_slippage_bps",
        "spread_bps": "actual_observed_spread_entry_bps",
    }


def test_counterfactual_sweep_accepts_allocator_model_input_market_depth() -> None:
    candidate = _candidate()
    candidate.pop("orderbook_depth_usd", None)
    candidate["adaptive_allocation"] = {
        "model_inputs": {
            "orderbook_depth_usd": 2400.0,
        },
    }

    sweep = run_counterfactual_sweep([candidate])

    assert sweep["status"] == "PASSED"
    selected = sweep["best_configurations_sample"][0]["selected"]
    assert selected["market_depth_capacity_usd"] == 2400.0
    assert selected["market_depth_source"] == "adaptive_allocation.model_inputs.orderbook_depth_usd"


def test_counterfactual_sweep_accepts_nested_market_cost_orderbook_levels() -> None:
    candidate = _candidate(side="short", action="short", expected_move_after_cost_bps=-90.0)
    candidate.pop("orderbook_depth_usd", None)
    candidate["market_cost_evidence"] = {
        "bids": [
            {"price": 100.0, "quantity": 3.0},
            {"price": 99.5, "quantity": 2.0},
        ],
    }

    sweep = run_counterfactual_sweep([candidate])

    assert sweep["status"] == "PASSED"
    selected = sweep["best_configurations_sample"][0]["selected"]
    assert selected["market_depth_capacity_usd"] == 499.0
    assert selected["market_depth_source"] == "market_cost_evidence.orderbook_levels"


def test_counterfactual_sweep_seeds_raw_signal_notional_from_risk_envelope() -> None:
    candidate = _candidate(orderbook_depth_usd=10_000.0)
    for field in ("gross_notional_usd", "notional", "notional_usdt"):
        candidate.pop(field, None)

    sweep = run_counterfactual_sweep([
        candidate,
    ], envelope=CounterfactualRiskEnvelope(starting_equity_usd=10_000.0))

    assert sweep["status"] == "PASSED"
    assert sweep["event_time_valid_candidate_count"] == 1
    assert sweep["best_configuration_count"] == 1
    audit = sweep["config_space_audit"]["candidate_configuration_audit_sample"][0]
    # Seed = (equity * max_portfolio_exposure_pct) / max notional multiplier
    # = (10000 * 0.60) / 5.0 = 1200, so the widest multiplier still lands
    # exactly on the envelope's 60% portfolio-exposure ceiling (6000 USD).
    assert audit["base_notional_usd"] == 1200.0
    assert audit["base_notional_source"] == "risk_envelope_seed_max_portfolio_exposure"
    selected = sweep["best_configurations_sample"][0]["selected"]
    assert selected["base_notional_usd"] == 1200.0
    assert selected["base_notional_source"] == "risk_envelope_seed_max_portfolio_exposure"
    assert 0.0 < selected["gross_notional_usd"] <= 6000.0
    assert selected["market_depth_capacity_usd"] == 10000.0


def test_counterfactual_sweep_treats_signed_short_move_as_directional_edge() -> None:
    sweep = run_counterfactual_sweep([
        _candidate(
            side="short",
            action="short",
            expected_move_after_cost_bps=-90.0,
        ),
    ])

    assert sweep["status"] == "PASSED"
    assert sweep["event_time_valid_candidate_count"] == 1
    assert sweep["skipped_not_a_grade_count"] == 0
    assert sweep["best_configuration_count"] == 1
    assert sweep["best_configurations_sample"][0]["selected"]["side"] == "short"


def test_counterfactual_sweep_excludes_non_directional_hold_rows_from_a_grade() -> None:
    sweep = run_counterfactual_sweep([
        _candidate(
            side="hold",
            action="hold",
            confidence_calibrated=0.91,
            expected_move_after_cost_bps=120.0,
        ),
    ])

    assert sweep["status"] == "NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE"
    assert sweep["counterfactual_blocker_reasons"] == ["NO_A_GRADE_SIGNALS"]
    assert sweep["a_grade_before_temporal_count"] == 0
    assert sweep["event_time_valid_candidate_count"] == 0
    assert sweep["skipped_not_a_grade_reason_counts"] == {"NON_DIRECTIONAL_ACTION": 1}
    assert sweep["near_a_grade_sample"][0]["reasons"] == ["NON_DIRECTIONAL_ACTION"]


def test_counterfactual_sweep_caps_configurations_by_actual_depth() -> None:
    sweep = run_counterfactual_sweep([
        _candidate(orderbook_depth_usd=260.0),
    ])

    assert sweep["status"] == "PASSED"
    assert sweep["event_time_valid_candidate_count"] == 1
    assert sweep["sweep_result_count"] > 0
    assert all(
        item["selected"]["gross_notional_usd"] <= 260.0
        for item in sweep["best_configurations_sample"]
    )
    assert sweep["best_configurations_sample"][0]["selected"]["market_depth_utilization_pct"] <= 1.0


def test_counterfactual_sweep_fails_closed_without_actual_depth() -> None:
    candidate = _candidate()
    candidate.pop("orderbook_depth_usd")

    sweep = run_counterfactual_sweep([candidate])

    assert sweep["status"] == "NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE"
    assert sweep["event_time_valid_candidate_count"] == 1
    assert sweep["sweep_result_count"] == 0
    assert sweep["best_configuration_count"] == 0
    assert sweep["skipped_no_feasible_configuration_count"] == 1
    assert sweep["skipped_no_feasible_configuration_reason_counts"] == {
        "MISSING_MARKET_DEPTH": 1,
    }
    assert sweep["config_space_audit"]["candidate_count"] == 1
    assert sweep["config_space_audit"]["theoretical_configuration_count"] == 2400
    assert sweep["config_space_audit"]["considered_count"] == 2400
    assert sweep["config_space_audit"]["feasible_count"] == 0
    assert sweep["config_space_audit"]["pruned_count"] == 2400
    assert sweep["config_space_audit"]["configuration_count_reconciled"] is True
    assert (
        sweep["config_space_audit"]["axis_value_coverage"]["full_feasible_axis_value_coverage"]
        is False
    )
    candidate_audit = sweep["config_space_audit"]["candidate_configuration_audit_sample"][0]
    assert candidate_audit["axis_count"] == 6
    assert candidate_audit["considered_count"] == 2400
    assert candidate_audit["feasible_count"] == 0
    assert candidate_audit["pruned_count"] == 2400
    assert candidate_audit["configuration_count_reconciled"] is True
    assert candidate_audit["feasible_plus_pruned_reconciled"] is True
    assert candidate_audit["axis_value_coverage"]["feasible_axis_values"]["margin_modes"] == []
    assert candidate_audit["pruned_reason_counts"] == {
        "MISSING_MARKET_DEPTH": 2400,
    }


def test_counterfactual_sweep_fails_closed_without_explicit_market_cost_evidence() -> None:
    candidate = _candidate()
    for field in (
        "actual_observed_spread_entry_bps",
        "expected_slippage_bps",
        "fee_bps",
        "expected_funding_bps",
    ):
        candidate.pop(field)

    sweep = run_counterfactual_sweep([candidate])

    assert sweep["status"] == "NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE"
    assert sweep["event_time_valid_candidate_count"] == 1
    assert sweep["sweep_result_count"] == 0
    assert sweep["best_configuration_count"] == 0
    assert sweep["skipped_no_feasible_configuration_count"] == 1
    assert sweep["skipped_no_feasible_configuration_reason_counts"] == {
        "MISSING_ACTUAL_SPREAD": 1,
        "MISSING_FEES": 1,
        "MISSING_FUNDING": 1,
        "MISSING_SLIPPAGE": 1,
    }
    assert sweep["config_space_audit"]["configuration_count_reconciled"] is True
    assert sweep["config_space_audit"]["candidate_configuration_audit_sample"][0]["pruned_configuration_count"] == 2400
    assert sweep["config_space_audit"]["candidate_configuration_audit_sample"][0]["pruned_reason_counts"] == {
        "MISSING_ACTUAL_SPREAD": 2400,
        "MISSING_FEES": 2400,
        "MISSING_FUNDING": 2400,
        "MISSING_SLIPPAGE": 2400,
    }


def test_counterfactual_sweep_rejects_future_leaking_features() -> None:
    sweep = run_counterfactual_sweep([
        _candidate(available_at="2026-06-19T12:01:00Z"),
    ])

    assert sweep["status"] == "NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE"
    assert sweep["counterfactual_blocker_reasons"] == ["NO_EVENT_TIME_VALID_CANDIDATES"]
    assert sweep["a_grade_before_temporal_count"] == 1
    assert sweep["event_time_valid_candidate_count"] == 0
    assert sweep["skipped_temporal_invalid_count"] == 1
    assert "AVAILABLE_AT_AFTER_DECISION_TIME" in sweep["skipped_temporal_invalid_sample"][0]["reasons"]


def test_counterfactual_sweep_reports_not_a_grade_reasons() -> None:
    sweep = run_counterfactual_sweep([
        _candidate(
            confidence_calibrated=0.55,
            expected_move_after_cost_bps=-1.0,
            allocator_decision="BLOCK_NO_EDGE",
        ),
    ])

    assert sweep["status"] == "NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE"
    assert sweep["counterfactual_blocker_reasons"] == ["NO_A_GRADE_SIGNALS"]
    assert sweep["a_grade_thresholds"] == {
        "confidence_min": 0.75,
        "after_cost_edge_bps_min_exclusive": 0.0,
        "allocator_blocked_decisions_excluded": True,
    }
    assert sweep["a_grade_before_temporal_count"] == 0
    assert sweep["event_time_valid_candidate_count"] == 0
    assert sweep["skipped_not_a_grade_count"] == 1
    assert sweep["skipped_not_a_grade_reason_counts"] == {
        "ALLOCATOR_BLOCK_NO_EDGE": 1,
        "LOW_CONFIDENCE": 1,
        "NON_POSITIVE_AFTER_COST_EDGE": 1,
    }
    assert sweep["skipped_not_a_grade_sample"] == [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "source_kind": "__unspecified__",
            "reasons": [
                "ALLOCATOR_BLOCK_NO_EDGE",
                "LOW_CONFIDENCE",
                "NON_POSITIVE_AFTER_COST_EDGE",
            ],
        }
    ]
    near_sample = sweep["near_a_grade_sample"][0]
    assert near_sample["symbol"] == "BTCUSDT"
    assert near_sample["timeframe"] == "1m"
    assert near_sample["side"] == "long"
    assert near_sample["confidence"] == 0.55
    assert near_sample["confidence_threshold"] == 0.75
    assert near_sample["confidence_gap_to_a_grade"] == 0.2
    assert near_sample["after_cost_edge_bps"] == -1.0
    assert near_sample["minimum_after_cost_edge_bps"] == 0.0
    assert near_sample["edge_gap_to_positive_bps"] == 1.0
    assert near_sample["allocator_decision"] == "BLOCK_NO_EDGE"
    assert near_sample["allocator_blocked"] is True
    assert near_sample["reasons"] == [
        "ALLOCATOR_BLOCK_NO_EDGE",
        "LOW_CONFIDENCE",
        "NON_POSITIVE_AFTER_COST_EDGE",
    ]
    assert near_sample["eligibility_gap_score"] == 1.21
    readiness = sweep["a_grade_readiness"]["source_kind_readiness"]["__unspecified__"]
    assert readiness["row_count"] == 1
    assert readiness["confidence_at_or_above_threshold_count"] == 0
    assert readiness["positive_after_cost_edge_count"] == 0
    assert readiness["a_grade_before_temporal_count"] == 0
    assert readiness["event_time_valid_candidate_count"] == 0
    assert readiness["best_configuration_count"] == 0
    assert readiness["confidence_gap_to_threshold"] == 0.2
    assert readiness["not_a_grade_reason_counts"] == {
        "ALLOCATOR_BLOCK_NO_EDGE": 1,
        "LOW_CONFIDENCE": 1,
        "NON_POSITIVE_AFTER_COST_EDGE": 1,
    }


def test_rare_event_stress_runs_against_best_configurations() -> None:
    sweep = run_counterfactual_sweep([_candidate()])
    stress = run_rare_event_capital_stress(sweep)

    assert stress["status"] == "PASSED"
    assert set(stress["completed_scenarios"]) == set(stress["required_scenarios"])
    assert stress["scenario_failures"] == []


def test_rare_event_stress_uses_full_best_configuration_set_not_dashboard_sample() -> None:
    stress = run_rare_event_capital_stress({
        "best_configurations": [
            {
                "selected": {
                    "scenario_losses_usd": {
                        "flash_crash": 1.0,
                        "exchange_outage": 1.0,
                        "spread_explosion": 1.0,
                        "slippage_spike": 1.0,
                        "funding_inversion": 1.0,
                        "squeeze": 1.0,
                        "liquidation_cascade": 1.0,
                    },
                },
            },
        ],
        "best_configurations_sample": [],
    })

    assert stress["status"] == "PASSED"
    assert stress["scenario_max_loss_usd"]["flash_crash"] == 1.0


def test_rare_event_stress_does_not_pass_without_counterfactual_configs() -> None:
    stress = run_rare_event_capital_stress({"best_configurations_sample": []})

    assert stress["status"] == "NO_GO_RARE_EVENT_CAPITAL_STRESS_NOT_RUN"
    assert stress["completed_scenarios"] == []
    assert stress["scenario_failures"] == ["NO_COUNTERFACTUAL_BEST_CONFIGURATIONS"]


def test_runtime_allocation_rare_event_stress_counts_full_row_set_not_sample() -> None:
    rows = [
        {
            "symbol": f"SYM{index}USDT",
            "timeframe": "1m",
            "side": "long",
            "gross_notional_usd": 100.0,
            "allocated_margin_usd": 50.0,
            "effective_leverage": 2.0,
            "stop_distance_bps": 40.0,
            "liquidation_buffer_bps": 2500.0,
            "expected_shortfall_usd": 0.4,
            "hedge_budget_usd": 0.0,
        }
        for index in range(25)
    ]

    stress = run_runtime_allocation_rare_event_stress(rows)

    assert stress["status"] == "PASSED"
    assert stress["runtime_allocation_row_count"] == 25
    assert stress["runtime_stressed_row_count"] == 25
    assert stress["stressed_allocation_sample_count"] == 20
    assert len(stress["stressed_allocation_sample"]) == 20
    assert set(stress["completed_scenarios"]) == set(stress["required_scenarios"])
