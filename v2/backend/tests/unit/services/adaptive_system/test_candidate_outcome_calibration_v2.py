from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from v2.backend.app.services.adaptive_system.candidate_outcome_calibration_v2 import (
    OBSERVATION_SCHEMA_VERSION,
    CandidateCalibrationObservationV2,
    CandidateOutcomeCalibrationError,
    _beta_bernoulli_information_gain,
    _canonical_sha256,
    _effective_sample_evidence,
    extract_calibration_observation,
    fit_candidate_outcome_calibration_v2,
    validate_candidate_outcome_calibration_v2,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_maturer_v2 import (
    mature_candidate,
)
from v2.backend.tests.unit.contracts.runtime_v2.test_candidate_decision_outcome_v2 import (
    _actual,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_maturer_v2 import (
    _hold_record,
    _record,
    _rows_and_proof,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_publisher_v2 import (
    _build,
    _inputs,
)


def _observation(index: int) -> CandidateCalibrationObservationV2:
    after_cost = float((index % 11) - 5)
    realized = index % 10 == 0
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
        realized_execution_outcome=realized,
        actual_fill_id=(f"fill-{index:03d}" if realized else None),
        actual_close_id=(f"close-{index:03d}" if realized else None),
        actual_fill_execution_time_ms=(1_000_100 + index * 1_000 if realized else None),
        actual_close_execution_time_ms=(1_000_500 + index * 1_000 if realized else None),
        policy_mode=(
            "bounded_information_seeking_exploration"
            if index % 20 == 0
            else "champion_exploitation"
        ),
        cohort_id="cohort-3",
        regime_bucket=(
            "LOW_REGIME_COMPATIBILITY"
            if index % 3 == 0
            else "HIGH_REGIME_COMPATIBILITY"
        ),
        confidence_raw_source=(index % 10) / 10.0,
        calibrated_confidence_source=(index % 10) / 10.0,
        predicted_loss_probability_source=(10 - index % 10) / 10.0,
        exit_feasibility_source=(index % 5) / 5.0,
        expected_move_after_cost_source_bps=float(index % 7),
        correlation_exposure_source=(index % 10) / 10.0,
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


def test_fit_admits_mixed_legacy_and_measured_correlation_population() -> None:
    # Half the population predates the correlation-exposure contract (None):
    # the fit must complete, report the split honestly in optimizer evidence,
    # and keep the correlation penalty learned from the measured rows only.
    observations = [
        (
            replace(_observation(index), correlation_exposure_source=None)
            if index % 2 == 0
            else _observation(index)
        )
        for index in range(100)
    ]

    artifact = fit_candidate_outcome_calibration_v2(
        observations,
        generated_at_ms=3_000_000,
        source_archive_chain_sha256="c" * 64,
    )

    optimizer = artifact["objective_weight_optimizer"]
    assert optimizer["correlation_exposure_measured_row_count"] > 0
    assert optimizer["correlation_exposure_missing_row_count"] > 0
    assert (
        optimizer["correlation_exposure_measured_row_count"]
        + optimizer["correlation_exposure_missing_row_count"]
        == artifact["fit_sample_count"]
    )
    assert artifact["learned_objective_weights"]["correlation_penalty"] > 0.0


def test_fits_chronological_calibration_without_holdout_leakage() -> None:
    observations = [_observation(index) for index in range(100)]

    artifact = fit_candidate_outcome_calibration_v2(
        observations,
        generated_at_ms=3_000_000,
        source_archive_chain_sha256="c" * 64,
    )

    assert artifact["fit_sample_count"] == 70
    assert artifact["validation_sample_count"] == 15
    assert artifact["holdout_sample_count"] == 15
    assert artifact["fit_window_end_ms"] < artifact["validation_window_start_ms"]
    assert artifact["validation_window_end_ms"] < artifact["holdout_window_start_ms"]
    assert artifact["holdout_used_for_fitting"] is False
    assert artifact["validation"][
        "objective_and_return_parameters_changed_after_validation"
    ] is False
    uncertainty = artifact["posterior_uncertainty_calibration"]
    assert uncertainty["method"] == "HIERARCHICAL_BETA_EFFECTIVE_INDEPENDENT_N"
    assert uncertainty["arbitrary_multiplier_used"] is False
    assert uncertainty["tuned_to_create_trades"] is False
    assert uncertainty["counterfactual_counts_as_realized_execution_profit"] is False
    # Authenticated realized closes are outcome EVIDENCE, never recency-
    # excluded: the one realized close inside the holdout window still counts
    # toward the profitability posterior (10 = 9 partitioned + 1 holdout).
    assert uncertainty["realized_execution_outcome_count"] == 10
    assert artifact["global_statistics"]["posterior_uncertainty"] == uncertainty[
        "epistemic_parameter_uncertainty"
    ]
    assert uncertainty["effective_sample_size"] < uncertainty["raw_row_count"]
    assert uncertainty["expected_information_gain_nats"] > 0.0
    assert artifact["probability_semantics"]["confidence_calibrated"][
        "is_profitability_probability"
    ] is False
    assert artifact["validation"]["untouched_holdout"][
        "holdout_used_to_select_uncertainty_coefficients"
    ] is False
    assert artifact["mode_allocation"]["permanent_percentage"] is False
    assert artifact["counterfactual_counts_as_realized_paper_profit"] is False
    assert artifact["objective_weight_optimizer"]["optimizer_steps"] >= 100
    assert artifact["objective_weight_optimizer"]["finite_loss"] is True
    assert artifact["objective_weight_optimizer"]["validation_rows_used"] == 0
    assert artifact["objective_weight_optimizer"]["holdout_used"] is False
    assert all(
        artifact["learned_objective_weights"][name] > 0.0
        for name in (
            "expected_after_cost_return",
            "terminal_target_probability_reward",
            "expected_log_equity_growth_reward",
            "drawdown_penalty",
            "tail_loss_penalty",
            "liquidation_risk_penalty",
            "market_impact_penalty",
            "funding_cost_penalty",
            "turnover_penalty",
            "concentration_penalty",
            "correlation_penalty",
            "information_gain_reward",
        )
    )
    optimizer = artifact["objective_weight_optimizer"]
    assert optimizer["all_economic_tradeoff_weights_learned_online"] is False
    assert optimizer["expected_log_equity_growth_reward_learned_online"] is False
    assert optimizer["terminal_target_probability_reward_learned_online"] is False
    assert optimizer["terminal_target_probability_selection_authority"] is False
    assert optimizer["expected_log_equity_growth_reward_derivation"]["method"] == (
        "RETURN_SCALE_DIVIDED_BY_MEAN_ABSOLUTE_REALIZED_LOG_RETURN"
    )
    assert optimizer["terminal_target_probability_reward_derivation"]["method"] == (
        "EXPECTED_LOG_EQUITY_GROWTH_REWARD_TIMES_LN_TARGET_MULTIPLE"
    )
    validate_candidate_outcome_calibration_v2(artifact)


@pytest.mark.parametrize(
    "field",
    (
        "terminal_target_probability_reward",
        "expected_log_equity_growth_reward",
        "correlation_penalty",
    ),
)
def test_validation_requires_every_v3_objective_weight(field: str) -> None:
    artifact = fit_candidate_outcome_calibration_v2(
        [_observation(index) for index in range(100)],
        generated_at_ms=3_000_000,
        source_archive_chain_sha256="c" * 64,
    )
    malformed = deepcopy(artifact)
    weights = malformed["learned_objective_weights"]
    weights.pop(field)
    parameter_material = dict(weights)
    parameter_material.pop("objective_parameter_fingerprint")
    weights["objective_parameter_fingerprint"] = _canonical_sha256(
        parameter_material
    )
    material = dict(malformed)
    material.pop("calibration_sha256")
    malformed["calibration_sha256"] = _canonical_sha256(material)

    with pytest.raises(
        CandidateOutcomeCalibrationError,
        match=rf"learned_objective_weights\.{field}:finite_number_required",
    ):
        validate_candidate_outcome_calibration_v2(malformed)


@pytest.mark.parametrize(
    "field",
    (
        "all_economic_tradeoff_weights_learned_online",
        "expected_log_equity_growth_reward_learned_online",
        "terminal_target_probability_reward_learned_online",
        "terminal_target_probability_selection_authority",
    ),
)
def test_validation_prohibits_false_terminal_weight_authority_claims(
    field: str,
) -> None:
    artifact = fit_candidate_outcome_calibration_v2(
        [_observation(index) for index in range(100)],
        generated_at_ms=3_000_000,
        source_archive_chain_sha256="c" * 64,
    )
    malformed = deepcopy(artifact)
    malformed["objective_weight_optimizer"][field] = True
    material = dict(malformed)
    material.pop("calibration_sha256")
    malformed["calibration_sha256"] = _canonical_sha256(material)

    with pytest.raises(
        CandidateOutcomeCalibrationError,
        match="objective_weight_optimizer:optimizer_evidence_invalid",
    ):
        validate_candidate_outcome_calibration_v2(malformed)


def test_validation_suffix_cannot_change_fitted_parameters() -> None:
    observations = [_observation(index) for index in range(100)]
    mutated = [
        replace(row, final_after_cost_return_bps=999.0, profitable=True, loss=False)
        if index >= 85
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
    # FITTED parameters never move with the suffix.  The profitability
    # posterior is outcome EVIDENCE: mutating a realized close inside the
    # suffix legitimately updates it, so only the posterior-evidence keys may
    # differ; every other global statistic stays identical.
    _posterior_evidence_keys = {
        "posterior_alpha",
        "posterior_beta",
        "effective_sample_size",
        "prior_entropy",
        "expected_posterior_entropy",
        "expected_information_gain_nats",
        "posterior_uncertainty",
        "win_rate_posterior_mean",
        "posterior_uncertainty_source",
        # loss probability blends the posterior mean, so it moves with
        # realized-close evidence as well.
        "loss_probability",
    }
    assert {
        key: value
        for key, value in first["global_statistics"].items()
        if key not in _posterior_evidence_keys
    } == {
        key: value
        for key, value in second["global_statistics"].items()
        if key not in _posterior_evidence_keys
    }
    assert first["profitability_posterior_hierarchy"] != second[
        "profitability_posterior_hierarchy"
    ]
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


def test_effective_sample_excludes_counterfactual_rows_and_collapses_close_identity() -> None:
    natural = _observation(0)
    duplicate = replace(
        natural,
        candidate_id="candidate-duplicate-close",
        decision_time_ms=natural.decision_time_ms + 1,
    )
    counterfactuals = [_observation(index) for index in range(1, 10)]

    evidence, profitable_weight, unprofitable_weight = _effective_sample_evidence(
        [natural, duplicate, *counterfactuals],
        source_archive_chain_sha256="c" * 64,
    )

    assert evidence["raw_row_count"] == 11
    assert evidence["natural_execution_count"] == 2
    assert evidence["unique_close_count"] == 1
    assert evidence["duplicate_execution_revisions_collapsed"] == 1
    assert evidence["counterfactual_outcome_count"] == 9
    assert evidence["counterfactual_counts_as_independent_realized_executions"] is False
    assert profitable_weight + unprofitable_weight == pytest.approx(
        evidence["effective_sample_size"]
    )


def test_expected_information_gain_declines_with_authenticated_evidence() -> None:
    sparse = _beta_bernoulli_information_gain(1.0, 1.0)
    learned = _beta_bernoulli_information_gain(100.0, 100.0)

    assert sparse["expected_information_gain_nats"] > 0.0
    assert learned["expected_information_gain_nats"] > 0.0
    assert sparse["expected_information_gain_nats"] > learned[
        "expected_information_gain_nats"
    ]


def test_conflicting_duplicate_close_fails_closed() -> None:
    natural = _observation(0)
    conflicting = replace(
        natural,
        candidate_id="candidate-conflicting-close",
        profitable=not natural.profitable,
        loss=not natural.loss,
        final_after_cost_return_bps=-natural.final_after_cost_return_bps,
    )
    with pytest.raises(CandidateOutcomeCalibrationError, match="conflicting_duplicate_close"):
        _effective_sample_evidence(
            [natural, conflicting],
            source_archive_chain_sha256="c" * 64,
        )


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
    assert observation.realized_execution_outcome is False


def _matured_without_correlation_exposure():
    status, intents, snapshots = _inputs(1)
    intents[0]["correlation_exposure_after_trade"] = None
    intents[0].update(
        {
            "entry_price": 100.1,
            "paper_execution_mark_price": 100.0,
            "observed_bid": 99.9,
            "observed_ask": 100.1,
            "observed_spread_bps": 20.0,
            "fee_bps": 1.0,
            "expected_slippage_bps": 2.0,
            "expected_funding_bps": 0.5,
            "depth_derived_price_impact_bps": 3.0,
            "stop_distance_bps": 100.0,
            "expected_move_after_cost_bps": 80.0,
        }
    )
    decision_record = _build(status, intents, snapshots).decision_records[0]
    rows, proof = _rows_and_proof(decision_record)
    return mature_candidate(
        decision_record,
        rows=rows,
        proof=proof,
        label_generated_at_ms=proof["training_observed_at_ms"] + 1,
    )


def test_extraction_admits_legacy_row_without_correlation_exposure() -> None:
    # The production archive holds rows written before the correlation
    # contract (2026-07-29).  They must be admitted with an honest None,
    # never rejected (crash-looped the 2026-07-30 cutover) and never
    # imputed as a measured 0.0.
    observation = extract_calibration_observation(
        _matured_without_correlation_exposure()
    )

    assert observation.correlation_exposure_source is None


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
    assert observation.realized_execution_outcome is True
    assert matured.matured_labels is not None
    assert matured.matured_labels.counts_as_paper_profit is True
