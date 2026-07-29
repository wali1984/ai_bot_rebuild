"""Chronological calibration over verified ``CandidateDecisionOutcomeV2`` labels."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from v2.backend.app.contracts.runtime_v2.candidate_decision_outcome_v2 import (
    CandidateDecisionOutcomeV2,
)
from v2.backend.app.services.adaptive_system.adaptive_objective_v2 import (
    UNIT_CONTRACT,
    WEIGHTS_SCHEMA_VERSION,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_maturer_v2 import (
    counterfactual_reference_side,
)

SCHEMA_VERSION = "candidate_outcome_calibration_v2"
OBSERVATION_SCHEMA_VERSION = "candidate_calibration_observation_v2"
MINIMUM_FIT_ROWS = 40
MINIMUM_VALIDATION_ROWS = 10
MINIMUM_GROUP_ROWS = 10
CALIBRATION_BIN_COUNT = 5
MAX_BOUNDED_EXPLORATION_PROBABILITY = 0.5


class CandidateOutcomeCalibrationError(ValueError):
    pass


def _fail(reason: str, field: str) -> None:
    raise CandidateOutcomeCalibrationError(f"{field}:{reason}")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        _fail("finite_number_required", field)
    result = float(value)
    if not math.isfinite(result):
        _fail("finite_number_required", field)
    return result


def _optional_probability(value: object, field: str) -> float | None:
    if value is None:
        return None
    result = _finite(value, field)
    if not 0.0 <= result <= 1.0:
        _fail("probability_0_1_required", field)
    return result


def _payload(record: CandidateDecisionOutcomeV2, name: str) -> dict[str, Any]:
    evidence = getattr(record.decision, name)
    try:
        payload = json.loads(evidence.payload_json)
    except json.JSONDecodeError as exc:
        raise CandidateOutcomeCalibrationError(f"decision.{name}:invalid_json") from exc
    if not isinstance(payload, dict):
        _fail("object_required", f"decision.{name}")
    return payload


@dataclass(frozen=True, slots=True)
class CandidateCalibrationObservationV2:
    schema_version: str
    candidate_id: str
    decision_time_ms: int
    label_record_available_at_ms: int
    checkpoint_generation: int
    checkpoint_id: str
    checkpoint_sha256: str
    symbol: str
    timeframe: str
    side: str
    decision_disposition: str
    realized_execution_outcome: bool
    calibrated_confidence_source: float | None
    predicted_loss_probability_source: float | None
    exit_feasibility_source: float | None
    expected_move_after_cost_source_bps: float | None
    final_gross_return_bps: float
    final_after_cost_return_bps: float
    max_favorable_excursion_bps: float
    max_adverse_excursion_bps: float
    realized_volatility_bps: float
    transaction_cost_bps: float
    slippage_bps: float
    market_impact_bps: float
    funding_bps: float
    profitable: bool
    loss: bool
    stop_hit: bool
    profit_target_hit: bool
    short_horizon_reversal: bool
    slippage_failure: bool
    missed_tp_then_stop: bool
    infeasible: bool
    label_receipts_sha256: str

    def __post_init__(self) -> None:
        if self.schema_version != OBSERVATION_SCHEMA_VERSION:
            _fail("invalid_schema_version", "schema_version")
        for field in ("candidate_id", "checkpoint_id", "symbol", "timeframe"):
            value = getattr(self, field)
            if (
                not isinstance(value, str)
                or not value
                or any(character.isspace() for character in value)
            ):
                _fail("identifier_required", field)
        if self.side not in {"LONG", "SHORT"}:
            _fail("LONG_or_SHORT_required", "side")
        if type(self.realized_execution_outcome) is not bool:
            _fail("bool_required", "realized_execution_outcome")
        for field in (
            "decision_time_ms",
            "label_record_available_at_ms",
            "checkpoint_generation",
        ):
            value = getattr(self, field)
            if type(value) is not int or value < 1:
                _fail("positive_int_required", field)
        if self.label_record_available_at_ms <= self.decision_time_ms:
            _fail("label_must_be_after_decision", "label_record_available_at_ms")
        if (
            not isinstance(self.checkpoint_sha256, str)
            or len(self.checkpoint_sha256) != 64
            or not isinstance(self.label_receipts_sha256, str)
            or len(self.label_receipts_sha256) != 64
        ):
            _fail("sha256_required", "sha256")
        for field in (
            "calibrated_confidence_source",
            "predicted_loss_probability_source",
            "exit_feasibility_source",
        ):
            _optional_probability(getattr(self, field), field)
        if self.expected_move_after_cost_source_bps is not None:
            _finite(
                self.expected_move_after_cost_source_bps,
                "expected_move_after_cost_source_bps",
            )
        for field in (
            "final_gross_return_bps",
            "final_after_cost_return_bps",
            "max_favorable_excursion_bps",
            "max_adverse_excursion_bps",
            "realized_volatility_bps",
            "transaction_cost_bps",
            "slippage_bps",
            "market_impact_bps",
            "funding_bps",
        ):
            _finite(getattr(self, field), field)
        if (
            self.max_favorable_excursion_bps < 0.0
            or self.max_adverse_excursion_bps > 0.0
            or self.realized_volatility_bps < 0.0
            or self.transaction_cost_bps < 0.0
            or self.slippage_bps < 0.0
            or self.market_impact_bps < 0.0
        ):
            _fail("metric_sign_invalid", "labels")
        if self.profitable is not (self.final_after_cost_return_bps > 0.0):
            _fail("must_match_after_cost_return", "profitable")
        if self.loss is not (self.final_after_cost_return_bps < 0.0):
            _fail("must_match_after_cost_return", "loss")


def extract_calibration_observation(
    record: CandidateDecisionOutcomeV2,
) -> CandidateCalibrationObservationV2:
    if not isinstance(record, CandidateDecisionOutcomeV2):
        raise TypeError("record must be CandidateDecisionOutcomeV2")
    labels = record.matured_labels
    if (
        record.archive_sequence != 2
        or labels is None
        or labels.matured is not True
        or labels.complete is not True
        or labels.summary_finality_proven is not True
    ):
        _fail("complete_matured_revision_two_required", "record")
    proposed = _payload(record, "proposed_action")
    components = _payload(record, "component_estimates")
    model = _payload(record, "model_distributions")
    proposed_action = str(
        proposed.get("proposed_action") or proposed.get("side") or ""
    ).upper()
    side = (
        counterfactual_reference_side(record.decision.candidate_id)
        if proposed_action == "HOLD"
        else proposed_action
    )
    unhedged = next(
        (arm for arm in labels.counterfactual_outcomes if arm.arm_name == "unhedged"),
        None,
    )
    if unhedged is None or not unhedged.scenarios:
        _fail("unhedged_counterfactual_required", "matured_labels")
    calibration_arm = unhedged
    if proposed_action == "HOLD":
        calibration_arm = next(
            (
                arm
                for arm in labels.counterfactual_outcomes
                if arm.arm_name == "alternative_side"
            ),
            None,
        )
        if calibration_arm is None or not calibration_arm.scenarios:
            _fail(
                "flat_alternative_side_counterfactual_required",
                "matured_labels",
            )
    selected_scenarios = tuple(calibration_arm.scenarios)
    if proposed_action == "HOLD" and len(selected_scenarios) > 1:
        selected_scenarios = tuple(
            scenario
            for scenario in selected_scenarios
            if scenario.scenario_id.endswith(f"-{side}")
        )
        if len(selected_scenarios) != 1:
            _fail(
                "flat_reference_side_scenario_required",
                "matured_labels",
            )
    after_cost = statistics.fmean(
        scenario.after_cost_pnl_bps for scenario in selected_scenarios
    )
    gross = statistics.fmean(
        scenario.gross_pnl_bps for scenario in selected_scenarios
    )
    # Executed paper decisions learn from their reconciled realized result.
    # Counterfactual paths remain useful for MFE/MAE and opportunity labels but
    # must never override an authenticated actual close or count as paper P&L.
    if labels.actual_paper_outcome is not None:
        after_cost = labels.actual_paper_outcome.realized_pnl_bps
    first_return = labels.horizon_labels[0].future_return_bps
    final_return = labels.horizon_labels[-1].future_return_bps
    expected_move_raw = proposed.get("expected_move_after_cost_bps")
    expected_move = (
        None
        if expected_move_raw is None
        else _finite(expected_move_raw, "expected_move_after_cost_bps")
    )
    transaction_cost = max(
        0.0,
        labels.fees_bps
        + labels.spread_bps
        + labels.slippage_bps
        + labels.market_impact_bps
        + labels.funding_bps,
    )
    receipts = tuple(sorted(labels.label_source_receipt_sha256s))
    return CandidateCalibrationObservationV2(
        schema_version=OBSERVATION_SCHEMA_VERSION,
        candidate_id=record.decision.candidate_id,
        decision_time_ms=record.decision.decision_time_ms,
        label_record_available_at_ms=labels.record_available_at_ms,
        checkpoint_generation=record.decision.checkpoint_generation,
        checkpoint_id=record.decision.checkpoint_id,
        checkpoint_sha256=record.decision.checkpoint_sha256,
        symbol=record.decision.symbol,
        timeframe=record.decision.timeframe,
        side=side,
        decision_disposition=record.decision.decision_disposition,
        realized_execution_outcome=(labels.actual_paper_outcome is not None),
        calibrated_confidence_source=_optional_probability(
            model.get("confidence_calibrated"), "confidence_calibrated"
        ),
        predicted_loss_probability_source=_optional_probability(
            components.get("pre_trade_loss_probability"),
            "pre_trade_loss_probability",
        ),
        exit_feasibility_source=_optional_probability(
            components.get("exit_feasibility_score"), "exit_feasibility_score"
        ),
        expected_move_after_cost_source_bps=expected_move,
        final_gross_return_bps=float(gross),
        final_after_cost_return_bps=float(after_cost),
        max_favorable_excursion_bps=labels.max_favorable_excursion_bps,
        max_adverse_excursion_bps=labels.max_adverse_excursion_bps,
        realized_volatility_bps=labels.realized_volatility_bps,
        transaction_cost_bps=transaction_cost,
        slippage_bps=labels.slippage_bps,
        market_impact_bps=labels.market_impact_bps,
        funding_bps=labels.funding_bps,
        profitable=after_cost > 0.0,
        loss=after_cost < 0.0,
        stop_hit=labels.stop_result == "HIT",
        profit_target_hit=labels.profit_exit_result == "HIT",
        short_horizon_reversal=first_return * final_return < 0.0,
        slippage_failure=(
            expected_move is not None and expected_move > 0.0 and transaction_cost > expected_move
        ),
        missed_tp_then_stop=(labels.profit_exit_result == "HIT" and labels.stop_result == "HIT"),
        infeasible=record.decision.decision_disposition == "INFEASIBLE",
        label_receipts_sha256=_canonical_sha256(receipts),
    )


def _quantiles(values: Sequence[float]) -> dict[str, float]:
    if not values:
        _fail("nonempty_values_required", "quantiles")
    ordered = sorted(float(value) for value in values)
    return {
        str(probability): ordered[round((len(ordered) - 1) * probability)]
        for probability in (0.1, 0.5, 0.9)
    }


def _posterior(events: Sequence[bool]) -> float:
    return (sum(events) + 1.0) / (len(events) + 2.0)


def _statistics(rows: Sequence[CandidateCalibrationObservationV2]) -> dict[str, Any]:
    win_rate = _posterior([row.profitable for row in rows])
    return {
        "sample_count": len(rows),
        "after_cost_expectancy_bps": statistics.fmean(
            row.final_after_cost_return_bps for row in rows
        ),
        "win_rate_posterior_mean": win_rate,
        "posterior_uncertainty": math.sqrt(win_rate * (1.0 - win_rate) / (len(rows) + 3.0)),
        "loss_probability": _posterior([row.loss for row in rows]),
        "stop_out_probability": _posterior([row.stop_hit for row in rows]),
        "profit_exit_probability": _posterior([row.profit_target_hit for row in rows]),
        "reversal_probability": _posterior([row.short_horizon_reversal for row in rows]),
        "slippage_failure_probability": _posterior([row.slippage_failure for row in rows]),
        "missed_tp_then_stop_probability": _posterior([row.missed_tp_then_stop for row in rows]),
        "venue_infeasible_probability": _posterior([row.infeasible for row in rows]),
        "return_bps_quantiles": _quantiles([row.final_after_cost_return_bps for row in rows]),
        "tail_loss_bps_quantiles": _quantiles(
            [max(0.0, -row.final_after_cost_return_bps) for row in rows]
        ),
        "mfe_bps_quantiles": _quantiles([row.max_favorable_excursion_bps for row in rows]),
        "mae_bps_quantiles": _quantiles([row.max_adverse_excursion_bps for row in rows]),
        "transaction_cost_bps_quantiles": _quantiles([row.transaction_cost_bps for row in rows]),
        "slippage_bps_quantiles": _quantiles([row.slippage_bps for row in rows]),
        "market_impact_bps_quantiles": _quantiles([row.market_impact_bps for row in rows]),
        "realized_volatility_bps_quantiles": _quantiles(
            [row.realized_volatility_bps for row in rows]
        ),
        "funding_bps_mean": statistics.fmean(row.funding_bps for row in rows),
    }


def _effective_independent_sample_size(residuals: Sequence[float]) -> float:
    """Estimate chronological effective N from lag-one residual dependence."""

    if len(residuals) < 3:
        return float(len(residuals))
    mean = statistics.fmean(residuals)
    centered = [value - mean for value in residuals]
    denominator = math.fsum(value * value for value in centered)
    if denominator <= 0.0:
        return float(len(residuals))
    lag_covariance = math.fsum(
        centered[index] * centered[index - 1]
        for index in range(1, len(centered))
    )
    lag_one_correlation = max(
        -0.99,
        min(0.99, lag_covariance / denominator),
    )
    effective = len(residuals) * (1.0 - lag_one_correlation) / (
        1.0 + lag_one_correlation
    )
    return max(1.0, min(float(len(residuals)), effective))


def _uncertainty_group_metrics(
    rows: Sequence[CandidateCalibrationObservationV2],
    *,
    predicted_win_probability: float,
    predictive_dispersion: float,
) -> dict[str, Any]:
    residuals = [float(row.profitable) - predicted_win_probability for row in rows]
    if not residuals:
        return {
            "sample_count": 0,
            "residual_dispersion": None,
            "residual_bias": None,
            "effective_independent_sample_size": 0.0,
            "expected_interval_coverage": {"one_sigma": 0.682689, "two_sigma": 0.9545},
            "realized_interval_coverage": {"one_sigma": None, "two_sigma": None},
        }

    def coverage(multiplier: float) -> float:
        lower = max(0.0, predicted_win_probability - multiplier * predictive_dispersion)
        upper = min(1.0, predicted_win_probability + multiplier * predictive_dispersion)
        return statistics.fmean(
            lower <= float(row.profitable) <= upper for row in rows
        )

    return {
        "sample_count": len(rows),
        "residual_dispersion": math.sqrt(
            statistics.fmean(value * value for value in residuals)
        ),
        "residual_bias": statistics.fmean(residuals),
        "effective_independent_sample_size": _effective_independent_sample_size(
            residuals
        ),
        "expected_interval_coverage": {
            "one_sigma": 0.682689,
            "two_sigma": 0.9545,
        },
        "realized_interval_coverage": {
            "one_sigma": coverage(1.0),
            "two_sigma": coverage(2.0),
        },
    }


def _uncertainty_calibration(
    fit_rows: Sequence[CandidateCalibrationObservationV2],
    validation_rows: Sequence[CandidateCalibrationObservationV2],
    *,
    fit_statistics: Mapping[str, Any],
) -> dict[str, Any]:
    """Audit and, when required, recalibrate predictive uncertainty.

    The prior value was the standard error of the aggregate win-rate mean.  It
    is not a predictive interval for the next candidate.  The chronological
    suffix supplies authenticated out-of-sample Bernoulli residuals, which are
    used only for this uncertainty calibration; objective weights and return
    parameters remain fitted solely on the prefix.
    """

    predicted_win = float(fit_statistics["win_rate_posterior_mean"])
    frozen_standard_error = float(fit_statistics["posterior_uncertainty"])
    validation_residuals = [
        float(row.profitable) - predicted_win for row in validation_rows
    ]
    heldout_dispersion = math.sqrt(
        statistics.fmean(value * value for value in validation_residuals)
    )
    frozen_metrics = _uncertainty_group_metrics(
        validation_rows,
        predicted_win_probability=predicted_win,
        predictive_dispersion=frozen_standard_error,
    )
    under_dispersed = (
        heldout_dispersion > frozen_standard_error * 1.25
        or float(frozen_metrics["realized_interval_coverage"]["two_sigma"])
        < 0.90
    )
    calibrated_dispersion = (
        max(1e-9, min(1.0, heldout_dispersion))
        if under_dispersed
        else frozen_standard_error
    )
    calibrated_metrics = _uncertainty_group_metrics(
        validation_rows,
        predicted_win_probability=predicted_win,
        predictive_dispersion=calibrated_dispersion,
    )

    fit_volatility = sorted(row.realized_volatility_bps for row in fit_rows)
    low_index = max(0, int((len(fit_volatility) - 1) * 0.33))
    high_index = max(0, int((len(fit_volatility) - 1) * 0.67))
    low_threshold = fit_volatility[low_index]
    high_threshold = fit_volatility[high_index]

    def regime(row: CandidateCalibrationObservationV2) -> str:
        if row.realized_volatility_bps <= low_threshold:
            return "LOW_REALIZED_VOLATILITY"
        if row.realized_volatility_bps >= high_threshold:
            return "HIGH_REALIZED_VOLATILITY"
        return "MID_REALIZED_VOLATILITY"

    dimensions: dict[str, dict[str, Any]] = {}
    for dimension, key_fn in (
        ("symbol", lambda row: row.symbol),
        ("side", lambda row: row.side),
        ("timeframe", lambda row: row.timeframe),
        ("regime", regime),
    ):
        grouped: dict[str, list[CandidateCalibrationObservationV2]] = defaultdict(list)
        for row in validation_rows:
            grouped[str(key_fn(row))].append(row)
        dimensions[dimension] = {
            key: _uncertainty_group_metrics(
                members,
                predicted_win_probability=predicted_win,
                predictive_dispersion=calibrated_dispersion,
            )
            for key, members in sorted(grouped.items())
        }

    realized_rows = [
        row for row in validation_rows if row.realized_execution_outcome
    ]
    realized_execution_metrics = _uncertainty_group_metrics(
        realized_rows,
        predicted_win_probability=predicted_win,
        predictive_dispersion=calibrated_dispersion,
    )
    return {
        "schema_version": "posterior_uncertainty_calibration_v1",
        "method": "CHRONOLOGICAL_HELDOUT_BERNOULLI_RESIDUAL_DISPERSION",
        "frozen_fit_standard_error": frozen_standard_error,
        "heldout_residual_dispersion": heldout_dispersion,
        "calibrated_predictive_uncertainty": calibrated_dispersion,
        "diagnosis": (
            "MATERIALLY_UNDER_DISPERSED_RECALIBRATED"
            if under_dispersed
            else "EMPIRICALLY_CALIBRATED_NO_CHANGE"
        ),
        "under_dispersed": under_dispersed,
        "arbitrary_multiplier_used": False,
        "tuned_to_create_trades": False,
        "chronological_heldout_used_for_uncertainty_only": True,
        "objective_weights_use_heldout": False,
        "return_parameters_use_heldout": False,
        "validation_row_digest": _canonical_sha256(
            [asdict(row) for row in validation_rows]
        ),
        "all_authenticated_outcome_labels": calibrated_metrics,
        "frozen_interval_audit": frozen_metrics,
        "calibration_by_dimension": dimensions,
        "regime_definition": {
            "source": "authenticated_realized_volatility_bps",
            "fit_prefix_low_threshold_bps": low_threshold,
            "fit_prefix_high_threshold_bps": high_threshold,
        },
        "realized_execution_outcomes": realized_execution_metrics,
        "counterfactual_outcome_count": sum(
            not row.realized_execution_outcome for row in validation_rows
        ),
        "realized_execution_outcome_count": len(realized_rows),
        "counterfactual_counts_as_realized_execution_profit": False,
    }


def _calibration_bins(
    rows: Sequence[CandidateCalibrationObservationV2],
    *,
    source_field: str,
    target_field: str,
) -> list[dict[str, Any]]:
    observed = [row for row in rows if getattr(row, source_field) is not None]
    observed.sort(key=lambda row: (getattr(row, source_field), row.candidate_id))
    if not observed:
        return []
    bin_count = min(CALIBRATION_BIN_COUNT, len(observed))
    bins: list[dict[str, Any]] = []
    for index in range(bin_count):
        start = index * len(observed) // bin_count
        end = (index + 1) * len(observed) // bin_count
        members = observed[start:end]
        source_values = [float(getattr(row, source_field)) for row in members]
        targets = [bool(getattr(row, target_field)) for row in members]
        bins.append(
            {
                "lower_inclusive": min(source_values),
                "upper_inclusive": max(source_values),
                "sample_count": len(members),
                "posterior_probability": _posterior(targets),
                "row_digest": _canonical_sha256([row.candidate_id for row in members]),
            }
        )
    return bins


def _learned_weights(
    rows: Sequence[CandidateCalibrationObservationV2],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fit positive risk prices on the chronological training partition only.

    The former implementation inferred coefficients from ratios of marginal
    means.  Those ratios were deterministic but were not an optimizer and
    systematically charged costs already included in after-cost return.  This
    constrained logistic fit learns the incremental risk prices that best
    separate profitable from unprofitable matured outcomes while keeping the
    declared portfolio objective and every coefficient strictly positive.
    """

    if not rows:
        _fail("nonempty_rows_required", "learned_objective_weights")
    feature_names = (
        "drawdown_penalty",
        "tail_loss_penalty",
        "liquidation_risk_penalty",
        "market_impact_penalty",
        "funding_cost_penalty",
        "turnover_penalty",
    )
    feature_rows = [
        (
            abs(row.max_adverse_excursion_bps),
            max(0.0, -row.final_after_cost_return_bps),
            float(row.stop_hit),
            row.market_impact_bps,
            abs(row.funding_bps),
            row.transaction_cost_bps,
        )
        for row in rows
    ]
    return_scale = max(
        0.01,
        statistics.fmean(abs(row.final_after_cost_return_bps) for row in rows),
    )
    feature_scales = tuple(
        max(0.01, statistics.fmean(values))
        for values in zip(*feature_rows, strict=True)
    )
    normalized = [
        tuple(value / scale for value, scale in zip(values, feature_scales, strict=True))
        for values in feature_rows
    ]
    beta = [1.0 / math.sqrt(len(rows)) for _ in feature_names]
    regularization = 1.0 / len(rows)
    optimizer_steps = 400
    final_loss = math.inf
    for step in range(1, optimizer_steps + 1):
        gradients = [0.0 for _ in feature_names]
        losses: list[float] = []
        for row, features in zip(rows, normalized, strict=True):
            logit = row.final_after_cost_return_bps / return_scale - math.fsum(
                coefficient * value for coefficient, value in zip(beta, features, strict=True)
            )
            if logit >= 0.0:
                probability = 1.0 / (1.0 + math.exp(-logit))
            else:
                exp_logit = math.exp(logit)
                probability = exp_logit / (1.0 + exp_logit)
            target = float(row.profitable)
            clipped = min(1.0 - 1e-15, max(1e-15, probability))
            losses.append(
                -(target * math.log(clipped) + (1.0 - target) * math.log1p(-clipped))
            )
            residual = probability - target
            for index, value in enumerate(features):
                gradients[index] += residual * -value
        learning_rate = 0.2 / math.sqrt(step)
        for index in range(len(beta)):
            gradient = gradients[index] / len(rows) + regularization * beta[index]
            beta[index] = max(1e-6, beta[index] - learning_rate * gradient)
        final_loss = statistics.fmean(losses) + 0.5 * regularization * math.fsum(
            value * value for value in beta
        )
    learned = {
        name: max(1e-6, coefficient * return_scale / scale)
        for name, coefficient, scale in zip(feature_names, beta, feature_scales, strict=True)
    }
    rejected_profitable = [
        row.final_after_cost_return_bps
        for row in rows
        if row.decision_disposition in {"REJECTED", "INFEASIBLE"}
        and row.final_after_cost_return_bps > 0.0
    ]
    information_reward = max(
        1e-6,
        statistics.fmean(rejected_profitable) if rejected_profitable else return_scale,
    )
    concentration_penalty = max(
        1e-6,
        statistics.median(learned.values()) / max(1.0, return_scale),
    )
    parameters = {
        "schema_version": WEIGHTS_SCHEMA_VERSION,
        "expected_after_cost_return": 1.0,
        **learned,
        "concentration_penalty": concentration_penalty,
        "information_gain_reward": information_reward,
        "unit_contract": UNIT_CONTRACT,
    }
    weights = {
        **parameters,
        "objective_parameter_fingerprint": _canonical_sha256(parameters),
    }
    optimizer = {
        "schema_version": "candidate_outcome_objective_weight_optimizer_v2",
        "optimizer_family": "positive_projected_logistic_risk_price_fit",
        "optimizer_steps": optimizer_steps,
        "finite_loss": math.isfinite(final_loss),
        "final_loss": final_loss,
        "fit_sample_count": len(rows),
        "fit_row_time_ordered": True,
        "validation_rows_used": 0,
        "holdout_used": False,
    }
    return weights, optimizer


def fit_candidate_outcome_calibration_v2(
    observations: Sequence[CandidateCalibrationObservationV2],
    *,
    generated_at_ms: int,
    source_archive_chain_sha256: str,
) -> dict[str, Any]:
    """Fit on the chronological prefix and evaluate once on the suffix."""

    if type(generated_at_ms) is not int or generated_at_ms < 1:
        _fail("positive_int_required", "generated_at_ms")
    if not isinstance(source_archive_chain_sha256, str) or len(source_archive_chain_sha256) != 64:
        _fail("sha256_required", "source_archive_chain_sha256")
    rows = sorted(observations, key=lambda row: (row.decision_time_ms, row.candidate_id))
    if len({row.candidate_id for row in rows}) != len(rows):
        _fail("candidate_ids_must_be_unique", "observations")
    if any(
        not isinstance(row, CandidateCalibrationObservationV2)
        or row.label_record_available_at_ms > generated_at_ms
        for row in rows
    ):
        _fail("verified_available_observations_required", "observations")
    lineage = {
        (row.checkpoint_generation, row.checkpoint_id, row.checkpoint_sha256) for row in rows
    }
    if len(lineage) != 1:
        _fail("single_checkpoint_lineage_required", "observations")
    unique_times = sorted({row.decision_time_ms for row in rows})
    if len(unique_times) < 2:
        _fail("multiple_decision_time_groups_required", "observations")
    proposed_index = max(1, min(len(unique_times) - 1, int(len(unique_times) * 0.8)))
    validation_start = unique_times[proposed_index]
    fit_rows = [row for row in rows if row.decision_time_ms < validation_start]
    validation_rows = [row for row in rows if row.decision_time_ms >= validation_start]
    if len(fit_rows) < MINIMUM_FIT_ROWS:
        _fail("minimum_fit_rows_not_met", "observations")
    if len(validation_rows) < MINIMUM_VALIDATION_ROWS:
        _fail("minimum_validation_rows_not_met", "observations")
    fit_statistics = _statistics(fit_rows)
    groups: dict[str, list[CandidateCalibrationObservationV2]] = defaultdict(list)
    for row in fit_rows:
        groups[f"{row.side}:{row.timeframe}"].append(row)
    group_statistics = {
        name: _statistics(group)
        for name, group in sorted(groups.items())
        if len(group) >= MINIMUM_GROUP_ROWS
    }
    confidence_bins = _calibration_bins(
        fit_rows,
        source_field="calibrated_confidence_source",
        target_field="profitable",
    )
    loss_bins = _calibration_bins(
        fit_rows,
        source_field="predicted_loss_probability_source",
        target_field="loss",
    )
    exit_bins = _calibration_bins(
        fit_rows,
        source_field="exit_feasibility_source",
        target_field="profit_target_hit",
    )
    expected_win = float(fit_statistics["win_rate_posterior_mean"])
    expected_return = float(fit_statistics["after_cost_expectancy_bps"])
    validation_brier = statistics.fmean(
        (expected_win - float(row.profitable)) ** 2 for row in validation_rows
    )
    validation_mae = statistics.fmean(
        abs(expected_return - row.final_after_cost_return_bps) for row in validation_rows
    )
    uncertainty_calibration = _uncertainty_calibration(
        fit_rows,
        validation_rows,
        fit_statistics=fit_statistics,
    )
    fit_statistics = {
        **fit_statistics,
        "posterior_uncertainty": uncertainty_calibration[
            "calibrated_predictive_uncertainty"
        ],
        "posterior_uncertainty_source": (
            "CHRONOLOGICAL_HELDOUT_BERNOULLI_RESIDUAL_DISPERSION"
        ),
    }
    group_statistics = {
        name: {
            **values,
            "posterior_uncertainty": uncertainty_calibration[
                "calibrated_predictive_uncertainty"
            ],
            "posterior_uncertainty_source": (
                "GLOBAL_CHRONOLOGICAL_HELDOUT_RESIDUAL_CALIBRATION"
            ),
        }
        for name, values in group_statistics.items()
    }
    missed_profitable_rate = _posterior(
        [
            row.profitable
            for row in fit_rows
            if row.decision_disposition in {"REJECTED", "INFEASIBLE"}
        ]
    )
    bounded_exploration_probability = min(
        MAX_BOUNDED_EXPLORATION_PROBABILITY,
        max(0.01, missed_profitable_rate),
    )
    weights, objective_optimizer = _learned_weights(fit_rows)
    checkpoint_generation, checkpoint_id, checkpoint_sha256 = next(iter(lineage))
    fit_row_digest = _canonical_sha256([asdict(row) for row in fit_rows])
    validation_row_digest = _canonical_sha256([asdict(row) for row in validation_rows])
    uncertainty_calibration_sha256 = _canonical_sha256(uncertainty_calibration)
    population_sha256 = _canonical_sha256([row.candidate_id for row in rows])
    fit_receipt_sha256 = _canonical_sha256(
        {
            "fit_row_digest": fit_row_digest,
            "source_archive_chain_sha256": source_archive_chain_sha256,
            "objective_parameter_fingerprint": weights["objective_parameter_fingerprint"],
            "uncertainty_calibration_sha256": uncertainty_calibration_sha256,
        }
    )
    material: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_ms": generated_at_ms,
        "source_archive_chain_sha256": source_archive_chain_sha256,
        "checkpoint_generation": checkpoint_generation,
        "checkpoint_id": checkpoint_id,
        "checkpoint_sha256": checkpoint_sha256,
        "chronological_split": True,
        "fit_window_start_ms": fit_rows[0].decision_time_ms,
        "fit_window_end_ms": fit_rows[-1].decision_time_ms,
        "validation_window_start_ms": validation_rows[0].decision_time_ms,
        "validation_window_end_ms": validation_rows[-1].decision_time_ms,
        "fit_record_available_at_ms": generated_at_ms,
        "fit_sample_count": len(fit_rows),
        "validation_sample_count": len(validation_rows),
        "holdout_used_for_fitting": False,
        "fit_row_digest": fit_row_digest,
        "validation_row_digest": validation_row_digest,
        "uncertainty_calibration_sha256": uncertainty_calibration_sha256,
        "training_population_sha256": population_sha256,
        "fit_receipt_sha256": fit_receipt_sha256,
        "global_statistics": fit_statistics,
        "side_timeframe_statistics": group_statistics,
        "calibrators": {
            "confidence_to_profitability": confidence_bins,
            "loss_score_to_loss_probability": loss_bins,
            "exit_score_to_profit_exit_probability": exit_bins,
        },
        "validation": {
            "frozen_global_probability_brier": validation_brier,
            "frozen_global_return_mae_bps": validation_mae,
            "parameters_changed_after_validation": uncertainty_calibration[
                "under_dispersed"
            ],
            "objective_and_return_parameters_changed_after_validation": False,
            "posterior_uncertainty_changed_after_validation": uncertainty_calibration[
                "under_dispersed"
            ],
        },
        "posterior_uncertainty_calibration": uncertainty_calibration,
        "heldout_used_for_uncertainty_calibration": True,
        "learned_objective_weights": weights,
        "objective_weight_optimizer": objective_optimizer,
        "mode_allocation": {
            "champion_exploitation_probability": 1.0 - bounded_exploration_probability,
            "bounded_exploration_probability": bounded_exploration_probability,
            "fit_method": "BETA_POSTERIOR_MISSED_PROFITABLE_REJECTION_RATE",
            "permanent_percentage": False,
        },
        "counterfactual_counts_as_realized_paper_profit": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    artifact = {**material, "calibration_sha256": _canonical_sha256(material)}
    validate_candidate_outcome_calibration_v2(artifact)
    return artifact


def validate_candidate_outcome_calibration_v2(artifact: Mapping[str, Any]) -> None:
    if artifact.get("schema_version") != SCHEMA_VERSION:
        _fail("invalid_schema_version", "schema_version")
    material = dict(artifact)
    stored = material.pop("calibration_sha256", None)
    if stored != _canonical_sha256(material):
        _fail("content_hash_mismatch", "calibration_sha256")
    if (
        artifact.get("chronological_split") is not True
        or int(artifact["fit_window_end_ms"]) >= int(artifact["validation_window_start_ms"])
        or artifact.get("holdout_used_for_fitting") is not False
    ):
        _fail("chronological_fit_validation_boundary_invalid", "split")
    uncertainty = artifact.get("posterior_uncertainty_calibration")
    if not isinstance(uncertainty, Mapping):
        _fail("uncertainty_calibration_required", "posterior_uncertainty_calibration")
    validation = artifact.get("validation")
    if not isinstance(validation, Mapping):
        _fail("validation_required", "validation")
    if (
        artifact.get("heldout_used_for_uncertainty_calibration") is not True
        or uncertainty.get("chronological_heldout_used_for_uncertainty_only") is not True
        or uncertainty.get("objective_weights_use_heldout") is not False
        or uncertainty.get("return_parameters_use_heldout") is not False
        or uncertainty.get("arbitrary_multiplier_used") is not False
        or uncertainty.get("tuned_to_create_trades") is not False
        or uncertainty.get("counterfactual_counts_as_realized_execution_profit")
        is not False
        or validation.get("objective_and_return_parameters_changed_after_validation")
        is not False
        or validation.get("posterior_uncertainty_changed_after_validation")
        is not uncertainty.get("under_dispersed")
        or validation.get("parameters_changed_after_validation")
        is not uncertainty.get("under_dispersed")
        or artifact.get("uncertainty_calibration_sha256")
        != _canonical_sha256(uncertainty)
    ):
        _fail("uncertainty_calibration_invalid", "posterior_uncertainty_calibration")
    global_statistics = artifact.get("global_statistics")
    if (
        not isinstance(global_statistics, Mapping)
        or global_statistics.get("posterior_uncertainty")
        != uncertainty.get("calibrated_predictive_uncertainty")
        or global_statistics.get("posterior_uncertainty_source")
        != "CHRONOLOGICAL_HELDOUT_BERNOULLI_RESIDUAL_DISPERSION"
    ):
        _fail("uncertainty_projection_mismatch", "global_statistics")
    if (
        int(artifact["fit_sample_count"]) < MINIMUM_FIT_ROWS
        or int(artifact["validation_sample_count"]) < MINIMUM_VALIDATION_ROWS
    ):
        _fail("minimum_samples_not_met", "sample_count")
    weights = artifact.get("learned_objective_weights")
    if not isinstance(weights, Mapping):
        _fail("weights_required", "learned_objective_weights")
    parameter_material = dict(weights)
    fingerprint = parameter_material.pop("objective_parameter_fingerprint", None)
    if fingerprint != _canonical_sha256(parameter_material):
        _fail("parameter_fingerprint_mismatch", "learned_objective_weights")
    optimizer = artifact.get("objective_weight_optimizer")
    if not isinstance(optimizer, Mapping):
        _fail("optimizer_evidence_required", "objective_weight_optimizer")
    if (
        optimizer.get("schema_version")
        != "candidate_outcome_objective_weight_optimizer_v2"
        or type(optimizer.get("optimizer_steps")) is not int
        or int(optimizer["optimizer_steps"]) < 100
        or optimizer.get("finite_loss") is not True
        or type(optimizer.get("final_loss")) is not float
        or not math.isfinite(float(optimizer["final_loss"]))
        or optimizer.get("fit_sample_count") != artifact.get("fit_sample_count")
        or optimizer.get("fit_row_time_ordered") is not True
        or optimizer.get("validation_rows_used") != 0
        or optimizer.get("holdout_used") is not False
    ):
        _fail("optimizer_evidence_invalid", "objective_weight_optimizer")
    if artifact.get("paper_only") is not True or artifact.get("live_gate") != (
        "blocked_human_only"
    ):
        _fail("paper_only_human_block_required", "safety")
    if any(
        artifact.get(field) is not False
        for field in ("routes_to_live", "places_real_order", "exchange_action_taken")
    ):
        _fail("no_live_authority_required", "safety")


__all__ = (
    "CandidateCalibrationObservationV2",
    "CandidateOutcomeCalibrationError",
    "MAX_BOUNDED_EXPLORATION_PROBABILITY",
    "extract_calibration_observation",
    "fit_candidate_outcome_calibration_v2",
    "validate_candidate_outcome_calibration_v2",
)
