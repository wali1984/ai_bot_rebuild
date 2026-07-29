from __future__ import annotations

from dataclasses import replace

import pytest

from v2.backend.app.services.adaptive_system.candidate_outcome_calibration_v2 import (
    OBSERVATION_SCHEMA_VERSION,
    CandidateCalibrationObservationV2,
    CandidateOutcomeCalibrationError,
    extract_calibration_observation,
    fit_candidate_outcome_calibration_v2,
    validate_candidate_outcome_calibration_v2,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_maturer_v2 import (
    mature_candidate,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_maturer_v2 import (
    _hold_record,
    _record,
    _rows_and_proof,
)
from v2.backend.tests.unit.contracts.runtime_v2.test_candidate_decision_outcome_v2 import (
    _actual,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_publisher_v2 import (
    _build,
    _inputs,
)


def _observation(index: int) -> CandidateCalibrationObservationV2:
    after_cost = float((index % 11) - 5)
    return CandidateCalibrationObservationV2(
        schema_version=OBSERVATION_SCHEMA_VERSION,
        candidate_id=f"candidate-{index:03d}",
        decision_time_ms=1_000_000 + index * 1_000,
        label_record_available_at_ms=2_000_000 + index * 1_000,
        checkpoint_generation=3,
        checkpoint_id="checkpoint-3",
        checkpoint_sha256="a" * 64,
        symbol="BTCUSDT",
        timeframe="5m" if index % 2 else "15m",
        side="LONG" if index % 2 else "SHORT",
        decision_disposition="REJECTED" if index % 3 else "INFEASIBLE",
        calibrated_confidence_source=(index % 10) / 10.0,
        predicted_loss_probability_source=(10 - index % 10) / 10.0,
        exit_feasibility_source=(index % 5) / 5.0,
        expected_move_after_cost_source_bps=float(index % 7),
        final_gross_return_bps=after_cost + 2.0,
        final_after_cost_return_bps=after_cost,
        max_favorable_excursion_bps=float(index % 20),
        max_adverse_excursion_bps=-float(index % 15),
        realized_volatility_bps=float(index % 9),
        transaction_cost_bps=2.0,
        slippage_bps=0.5,
        market_impact_bps=0.25,
        funding_bps=0.1,
        profitable=after_cost > 0.0,
        loss=after_cost < 0.0,
        stop_hit=index % 4 == 0,
        profit_target_hit=index % 5 == 0,
        short_horizon_reversal=index % 6 == 0,
        slippage_failure=index % 7 == 0,
        missed_tp_then_stop=index % 20 == 0,
        infeasible=index % 3 == 0,
        label_receipts_sha256="b" * 64,
    )


def test_fits_chronological_calibration_without_holdout_leakage() -> None:
    observations = [_observation(index) for index in range(100)]

    artifact = fit_candidate_outcome_calibration_v2(
        observations,
        generated_at_ms=3_000_000,
        source_archive_chain_sha256="c" * 64,
    )

    assert artifact["fit_sample_count"] == 80
    assert artifact["validation_sample_count"] == 20
    assert artifact["fit_window_end_ms"] < artifact["validation_window_start_ms"]
    assert artifact["holdout_used_for_fitting"] is False
    assert artifact["validation"]["parameters_changed_after_validation"] is False
    assert artifact["mode_allocation"]["permanent_percentage"] is False
    assert artifact["counterfactual_counts_as_realized_paper_profit"] is False
    assert artifact["objective_weight_optimizer"]["optimizer_steps"] >= 100
    assert artifact["objective_weight_optimizer"]["finite_loss"] is True
    assert artifact["objective_weight_optimizer"]["validation_rows_used"] == 0
    assert artifact["objective_weight_optimizer"]["holdout_used"] is False
    assert all(
        artifact["learned_objective_weights"][name] > 0.0
        for name in (
            "drawdown_penalty",
            "tail_loss_penalty",
            "liquidation_risk_penalty",
            "market_impact_penalty",
            "funding_cost_penalty",
            "turnover_penalty",
            "concentration_penalty",
            "information_gain_reward",
        )
    )
    validate_candidate_outcome_calibration_v2(artifact)


def test_validation_suffix_cannot_change_fitted_parameters() -> None:
    observations = [_observation(index) for index in range(100)]
    mutated = [
        replace(row, final_after_cost_return_bps=999.0, profitable=True, loss=False)
        if index >= 80
        else row
        for index, row in enumerate(observations)
    ]

    first = fit_candidate_outcome_calibration_v2(
        observations,
        generated_at_ms=3_000_000,
        source_archive_chain_sha256="c" * 64,
    )
    second = fit_candidate_outcome_calibration_v2(
        mutated,
        generated_at_ms=3_000_000,
        source_archive_chain_sha256="c" * 64,
    )

    assert first["fit_row_digest"] == second["fit_row_digest"]
    assert first["learned_objective_weights"] == second["learned_objective_weights"]
    assert first["objective_weight_optimizer"] == second["objective_weight_optimizer"]
    assert first["global_statistics"] == second["global_statistics"]
    assert first["validation"] != second["validation"]


def test_future_available_label_and_tampered_artifact_fail_closed() -> None:
    observations = [_observation(index) for index in range(100)]
    observations[0] = replace(observations[0], label_record_available_at_ms=4_000_000)
    with pytest.raises(CandidateOutcomeCalibrationError, match="verified_available"):
        fit_candidate_outcome_calibration_v2(
            observations,
            generated_at_ms=3_000_000,
            source_archive_chain_sha256="c" * 64,
        )

    artifact = fit_candidate_outcome_calibration_v2(
        [_observation(index) for index in range(100)],
        generated_at_ms=3_000_000,
        source_archive_chain_sha256="c" * 64,
    )
    artifact["fit_sample_count"] = 999
    with pytest.raises(CandidateOutcomeCalibrationError, match="content_hash_mismatch"):
        validate_candidate_outcome_calibration_v2(artifact)


def test_extracts_only_complete_point_in_time_matured_revision() -> None:
    decision_record = _record()
    rows, proof = _rows_and_proof(decision_record)
    matured = mature_candidate(
        decision_record,
        rows=rows,
        proof=proof,
        label_generated_at_ms=proof["training_observed_at_ms"] + 1,
    )

    observation = extract_calibration_observation(matured)

    assert observation.candidate_id == matured.decision.candidate_id
    assert observation.label_record_available_at_ms > observation.decision_time_ms
    assert observation.transaction_cost_bps > 0.0
    assert observation.label_receipts_sha256 != "0" * 64
    assert observation.final_after_cost_return_bps == (
        matured.matured_labels.counterfactual_outcomes[0].scenarios[0].after_cost_pnl_bps
    )


def test_hold_observation_uses_predeclared_reference_side_missed_edge() -> None:
    decision_record = _hold_record()
    rows, proof = _rows_and_proof(decision_record)
    matured = mature_candidate(
        decision_record,
        rows=rows,
        proof=proof,
        label_generated_at_ms=proof["training_observed_at_ms"] + 1,
    )

    observation = extract_calibration_observation(matured)

    assert observation.side in {"LONG", "SHORT"}
    assert observation.decision_disposition == "REJECTED"
    assert observation.final_gross_return_bps != 0.0
    assert matured.matured_labels is not None
    assert matured.matured_labels.counts_as_paper_profit is False


def test_executed_observation_uses_reconciled_actual_pnl_not_counterfactual() -> None:
    status, intents, snapshots = _inputs(1)
    intents[0].update(
        {
            "paper_fill_allowed": True,
            "allocator_decision": "ALLOW_WITH_SIZE",
            "entry_price": 100.1,
            "paper_execution_mark_price": 100.0,
            "observed_bid": 99.9,
            "observed_ask": 100.1,
            "observed_spread_bps": 20.0,
            "fee_bps": 1.0,
            "expected_slippage_bps": 2.0,
            "expected_funding_bps": 0.5,
            "depth_derived_price_impact_bps": 3.0,
        }
    )
    record = _build(status, intents, snapshots).decision_records[0]
    rows, proof = _rows_and_proof(record)
    generated_at_ms = proof["training_observed_at_ms"] + 1
    actual = _actual(
        record.decision,
        fill_execution_time_ms=record.decision.decision_time_ms + 1,
        fill_record_available_at_ms=record.decision.decision_time_ms + 2,
        close_execution_time_ms=generated_at_ms - 3,
        close_record_available_at_ms=generated_at_ms - 2,
        accounting_record_available_at_ms=generated_at_ms - 1,
        realized_pnl_usd=-0.5,
        realized_pnl_bps=-250.0,
    )
    matured = mature_candidate(
        record,
        rows=rows,
        proof=proof,
        label_generated_at_ms=generated_at_ms,
        actual_paper_outcome=actual,
    )

    observation = extract_calibration_observation(matured)

    assert observation.final_after_cost_return_bps == -250.0
    assert observation.loss is True
    assert matured.matured_labels is not None
    assert matured.matured_labels.counts_as_paper_profit is True
