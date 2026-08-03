from __future__ import annotations

from v2.backend.app.services.e2e_verification.service import run_e2e_verification


def test_e2e_verification_runs_all_scenarios_and_passes() -> None:
    report = run_e2e_verification()

    assert report.summary["scenario_count"] == 11
    assert report.summary["critical_failures"] == 0
    assert report.summary["failed_count"] == 0
    assert report.summary["all_decision_ids_replayable"] is True
    assert report.summary["clean_data_valid_decisions"] is True
    assert report.summary["dirty_data_blocked_from_training"] is True
    assert report.summary["dirty_data_blocked_from_execution"] is True


def test_e2e_verification_specific_safety_scenarios_are_blocked() -> None:
    report = run_e2e_verification()
    by_name = {row.scenario_name: row for row in report.scenarios}

    missing = by_name["missing_candle_scenario"]
    assert missing.actual_result == "BLOCKED_BY_DATA_GATE"
    assert missing.trade_approved is False
    assert missing.training_sample_accepted is False

    future = by_name["future_leaking_masa_prediction_scenario"]
    assert future.actual_result == "BLOCKED_BY_RISK_MANAGER"
    assert future.trade_approved is False
    assert future.training_sample_accepted is False
    assert future.masa_ppo_cutoff["future_leakage_detected"] is True
    assert future.risk_decision["risk_reason_code"] == "deny_future_leaking_masa_prediction"

    stale = by_name["stale_masa_prediction_scenario"]
    assert stale.actual_result == "BLOCKED_BY_RISK_MANAGER"
    assert stale.masa_ppo_cutoff["stale_masa_prediction"] is True
    assert stale.training_sample_accepted is False

    invalid_transition = by_name["invalid_position_transition_scenario"]
    assert invalid_transition.actual_result == "BLOCKED_BY_RISK_MANAGER"
    assert invalid_transition.risk_decision["risk_reason_code"] == "deny_position_state_conflict_block"
    assert invalid_transition.training_sample_accepted is False

    poor_execution = by_name["poor_execution_slippage_scenario"]
    assert poor_execution.actual_result == "BLOCKED_BY_EXECUTION_SIMULATOR"
    assert poor_execution.trade_approved is False
    assert poor_execution.training_sample_accepted is False
