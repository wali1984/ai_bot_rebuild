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

SCHEMA_VERSION = "candidate_outcome_calibration_v3"
OBSERVATION_SCHEMA_VERSION = "candidate_calibration_observation_v3"
MINIMUM_FIT_ROWS = 40
MINIMUM_VALIDATION_ROWS = 10
MINIMUM_GROUP_ROWS = 10
CALIBRATION_BIN_COUNT = 5
MAX_BOUNDED_EXPLORATION_PROBABILITY = 0.5
REQUIRED_OBJECTIVE_WEIGHT_FIELDS = (
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
    actual_fill_id: str | None
    actual_close_id: str | None
    actual_fill_execution_time_ms: int | None
    actual_close_execution_time_ms: int | None
    policy_mode: str
    cohort_id: str
    regime_bucket: str
    confidence_raw_source: float | None
    calibrated_confidence_source: float | None
    predicted_loss_probability_source: float | None
    exit_feasibility_source: float | None
    expected_move_after_cost_source_bps: float | None
    # None on archive rows written before the correlation-exposure contract
    # (2026-07-29); such rows are admitted without correlation evidence.
    correlation_exposure_source: float | None
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
        actual_identity = (
            self.actual_fill_id,
            self.actual_close_id,
            self.actual_fill_execution_time_ms,
            self.actual_close_execution_time_ms,
        )
        if self.realized_execution_outcome:
            if any(value is None for value in actual_identity):
                _fail("actual_execution_identity_required", "actual_execution")
            if (
                type(self.actual_fill_id) is not str
                or not self.actual_fill_id
                or type(self.actual_close_id) is not str
                or not self.actual_close_id
                or type(self.actual_fill_execution_time_ms) is not int
                or type(self.actual_close_execution_time_ms) is not int
                or self.actual_fill_execution_time_ms < self.decision_time_ms
                or self.actual_close_execution_time_ms
                <= self.actual_fill_execution_time_ms
            ):
                _fail("actual_execution_identity_invalid", "actual_execution")
        elif any(value is not None for value in actual_identity):
            _fail("counterfactual_cannot_claim_execution", "actual_execution")
        for field in ("policy_mode", "cohort_id", "regime_bucket"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value or any(
                character.isspace() for character in value
            ):
                _fail("identifier_required", field)
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
            "confidence_raw_source",
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
        if self.correlation_exposure_source is not None:
            correlation_exposure = _finite(
                self.correlation_exposure_source,
                "correlation_exposure_source",
            )
            if not 0.0 <= correlation_exposure <= 1.0:
                _fail("probability_0_1_required", "correlation_exposure_source")
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
    selected = _payload(record, "selected_action")
    portfolio = _payload(record, "portfolio_state")
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
    actual = labels.actual_paper_outcome
    policy_mode_raw = selected.get("adaptive_policy_action_policy_mode")
    policy_mode = (
        str(policy_mode_raw)
        if isinstance(policy_mode_raw, str) and policy_mode_raw
        else "LEGACY_OR_UNTYPED"
    )
    cohort_raw = selected.get("cohort_id")
    cohort_id = (
        str(cohort_raw)
        if isinstance(cohort_raw, str) and cohort_raw
        else f"derived_{_canonical_sha256({'policy_id': record.decision.policy_id, 'checkpoint_generation': record.decision.checkpoint_generation})[:24]}"
    )
    regime_score = _optional_probability(
        components.get("regime_compatibility_score"),
        "regime_compatibility_score",
    )
    if regime_score is None:
        regime_bucket = "REGIME_EVIDENCE_UNAVAILABLE"
    elif regime_score < 1.0 / 3.0:
        regime_bucket = "LOW_REGIME_COMPATIBILITY"
    elif regime_score > 2.0 / 3.0:
        regime_bucket = "HIGH_REGIME_COMPATIBILITY"
    else:
        regime_bucket = "MID_REGIME_COMPATIBILITY"
    return CandidateCalibrationObservationV2(
        schema_version=OBSERVATION_SCHEMA_VERSION,
        candidate_id=record.decision.candidate_id,
        # For an EXECUTED observation the decision instant is the typed
        # action's own authenticated ``action_decision_time_ms`` (bound to
        # the close via the verified selected-action hash); the record-level
        # ``decision_time_ms`` is the cycle ARCHIVAL stamp, which postdates
        # an intra-cycle fill and would invert execution causality.
        # Counterfactual observations keep the archival stamp exactly as
        # before.
        decision_time_ms=(
            record.decision.decision_time_ms
            if actual is None
            else actual.action_decision_time_ms
        ),
        label_record_available_at_ms=labels.record_available_at_ms,
        checkpoint_generation=record.decision.checkpoint_generation,
        checkpoint_id=record.decision.checkpoint_id,
        checkpoint_sha256=record.decision.checkpoint_sha256,
        symbol=record.decision.symbol,
        timeframe=record.decision.timeframe,
        side=side,
        decision_disposition=record.decision.decision_disposition,
        realized_execution_outcome=(actual is not None),
        actual_fill_id=(None if actual is None else actual.fill_id),
        actual_close_id=(None if actual is None else actual.closed_trade_id),
        actual_fill_execution_time_ms=(
            None if actual is None else actual.fill_execution_time_ms
        ),
        actual_close_execution_time_ms=(
            None if actual is None else actual.close_execution_time_ms
        ),
        policy_mode=policy_mode,
        cohort_id=cohort_id,
        regime_bucket=regime_bucket,
        confidence_raw_source=_optional_probability(
            model.get("selected_action_probability"),
            "selected_action_probability",
        ),
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
        correlation_exposure_source=(
            None
            if portfolio.get("correlation_exposure_after_trade") is None
            else max(
                0.0,
                min(
                    1.0,
                    _finite(
                        portfolio.get("correlation_exposure_after_trade"),
                        "correlation_exposure_after_trade",
                    ),
                ),
            )
        ),
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


def _statistics(
    rows: Sequence[CandidateCalibrationObservationV2],
    *,
    profitability_posterior: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    reference_win_rate = _posterior([row.profitable for row in rows])
    win_rate = (
        reference_win_rate
        if profitability_posterior is None
        else float(profitability_posterior["posterior_mean"])
    )
    loss_probability = (
        _posterior([row.loss for row in rows])
        if profitability_posterior is None
        else 1.0 - win_rate
    )
    result = {
        "sample_count": len(rows),
        "after_cost_expectancy_bps": statistics.fmean(
            row.final_after_cost_return_bps for row in rows
        ),
        "win_rate_posterior_mean": win_rate,
        "reference_outcome_win_rate_posterior_mean": reference_win_rate,
        "loss_probability": loss_probability,
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
    if profitability_posterior is None:
        result.update(
            {
                "posterior_uncertainty": math.sqrt(
                    win_rate * (1.0 - win_rate) / (len(rows) + 3.0)
                ),
                "posterior_uncertainty_source": "LEGACY_RAW_REFERENCE_ROW_STANDARD_ERROR_DIAGNOSTIC_ONLY",
                "expected_information_gain_nats": 0.0,
            }
        )
    else:
        result.update(
            {
                "posterior_uncertainty": float(
                    profitability_posterior["posterior_standard_deviation"]
                ),
                "posterior_uncertainty_source": (
                    "HIERARCHICAL_BETA_EFFECTIVE_N_NATURAL_EXECUTIONS"
                ),
                "expected_information_gain_nats": float(
                    profitability_posterior["expected_information_gain_nats"]
                ),
                "prior_entropy": float(profitability_posterior["prior_entropy"]),
                "expected_posterior_entropy": float(
                    profitability_posterior["expected_posterior_entropy"]
                ),
                "effective_sample_size": float(
                    profitability_posterior["effective_sample_evidence"][
                        "effective_sample_size"
                    ]
                ),
                "bucket_identity": str(
                    profitability_posterior["bucket_identity"]
                ),
                "parent_bucket_identity": profitability_posterior[
                    "parent_bucket_identity"
                ],
                "posterior_alpha": float(
                    profitability_posterior["posterior_alpha"]
                ),
                "posterior_beta": float(
                    profitability_posterior["posterior_beta"]
                ),
            }
        )
    return result


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


def _digamma(value: float) -> float:
    """Stable positive-domain digamma approximation for Beta evidence."""

    if value <= 0.0 or not math.isfinite(value):
        _fail("positive_finite_required", "digamma")
    result = 0.0
    while value < 8.0:
        result -= 1.0 / value
        value += 1.0
    inverse = 1.0 / value
    inverse_squared = inverse * inverse
    return result + math.log(value) - 0.5 * inverse - inverse_squared * (
        1.0 / 12.0
        - inverse_squared
        * (1.0 / 120.0 - inverse_squared * (1.0 / 252.0))
    )


def _beta_entropy(alpha: float, beta: float) -> float:
    total = alpha + beta
    return (
        math.lgamma(alpha)
        + math.lgamma(beta)
        - math.lgamma(total)
        - (alpha - 1.0) * _digamma(alpha)
        - (beta - 1.0) * _digamma(beta)
        + (total - 2.0) * _digamma(total)
    )


def _beta_bernoulli_information_gain(alpha: float, beta: float) -> dict[str, float]:
    """Expected reduction in Beta-parameter entropy from one execution."""

    total = alpha + beta
    profitable_probability = alpha / total
    prior_entropy = _beta_entropy(alpha, beta)
    expected_posterior_entropy = (
        profitable_probability * _beta_entropy(alpha + 1.0, beta)
        + (1.0 - profitable_probability) * _beta_entropy(alpha, beta + 1.0)
    )
    return {
        "prior_entropy": prior_entropy,
        "expected_posterior_entropy": expected_posterior_entropy,
        "expected_information_gain_nats": max(
            0.0, prior_entropy - expected_posterior_entropy
        ),
    }


def _beta_continued_fraction(alpha: float, beta: float, value: float) -> float:
    maximum_iterations = 200
    epsilon = 3e-14
    floor = 1e-300
    qab = alpha + beta
    qap = alpha + 1.0
    qam = alpha - 1.0
    c = 1.0
    d = 1.0 - qab * value / qap
    if abs(d) < floor:
        d = floor
    d = 1.0 / d
    result = d
    for iteration in range(1, maximum_iterations + 1):
        twice = 2 * iteration
        coefficient = iteration * (beta - iteration) * value / (
            (qam + twice) * (alpha + twice)
        )
        d = 1.0 + coefficient * d
        if abs(d) < floor:
            d = floor
        c = 1.0 + coefficient / c
        if abs(c) < floor:
            c = floor
        d = 1.0 / d
        result *= d * c
        coefficient = -(
            (alpha + iteration)
            * (qab + iteration)
            * value
            / ((alpha + twice) * (qap + twice))
        )
        d = 1.0 + coefficient * d
        if abs(d) < floor:
            d = floor
        c = 1.0 + coefficient / c
        if abs(c) < floor:
            c = floor
        d = 1.0 / d
        delta = d * c
        result *= delta
        if abs(delta - 1.0) <= epsilon:
            return result
    _fail("continued_fraction_did_not_converge", "beta_cdf")


def _regularized_beta(value: float, alpha: float, beta: float) -> float:
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(alpha + beta)
        - math.lgamma(alpha)
        - math.lgamma(beta)
        + alpha * math.log(value)
        + beta * math.log1p(-value)
    )
    if value < (alpha + 1.0) / (alpha + beta + 2.0):
        return front * _beta_continued_fraction(alpha, beta, value) / alpha
    return 1.0 - front * _beta_continued_fraction(
        beta, alpha, 1.0 - value
    ) / beta


def _beta_quantile(probability: float, alpha: float, beta: float) -> float:
    lower = 0.0
    upper = 1.0
    for _ in range(80):
        midpoint = (lower + upper) / 2.0
        if _regularized_beta(midpoint, alpha, beta) < probability:
            lower = midpoint
        else:
            upper = midpoint
    return (lower + upper) / 2.0


def _concentration_effective_count(values: Sequence[str]) -> float:
    if not values:
        return 0.0
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    total = float(len(values))
    return 1.0 / math.fsum((count / total) ** 2 for count in counts.values())


def _effective_sample_evidence(
    rows: Sequence[CandidateCalibrationObservationV2],
    *,
    source_archive_chain_sha256: str,
) -> tuple[dict[str, Any], float, float]:
    """Collapse executions and conservatively estimate independent evidence."""

    natural_rows = [row for row in rows if row.realized_execution_outcome]
    by_close: dict[str, CandidateCalibrationObservationV2] = {}
    for row in natural_rows:
        close_id = str(row.actual_close_id)
        previous = by_close.get(close_id)
        if previous is not None and (
            previous.profitable != row.profitable
            or previous.actual_fill_id != row.actual_fill_id
            or previous.symbol != row.symbol
            or previous.side != row.side
        ):
            _fail("conflicting_duplicate_close", "natural_execution_outcomes")
        if previous is None or row.decision_time_ms < previous.decision_time_ms:
            by_close[close_id] = row
    unique_rows = sorted(
        by_close.values(), key=lambda row: (row.decision_time_ms, row.candidate_id)
    )
    count = len(unique_rows)
    if count:
        latest_decision_time_ms = max(row.decision_time_ms for row in unique_rows)
        half_life_ms = 30.0 * 24.0 * 60.0 * 60.0 * 1_000.0
        decay_weights = [
            math.exp(
                -math.log(2.0)
                * (latest_decision_time_ms - row.decision_time_ms)
                / half_life_ms
            )
            for row in unique_rows
        ]
        decay_sum = math.fsum(decay_weights)
        decay_kish = decay_sum * decay_sum / math.fsum(
            weight * weight for weight in decay_weights
        )
        autocorrelation_n = _effective_independent_sample_size(
            [float(row.profitable) for row in unique_rows]
        )
        nonoverlap_count = 0
        last_close_ms = -1
        for row in sorted(
            unique_rows,
            key=lambda item: (
                int(item.actual_close_execution_time_ms or 0),
                item.candidate_id,
            ),
        ):
            fill_ms = int(row.actual_fill_execution_time_ms or 0)
            close_ms = int(row.actual_close_execution_time_ms or 0)
            if fill_ms >= last_close_ms:
                nonoverlap_count += 1
                last_close_ms = close_ms
        symbol_diversity = _concentration_effective_count(
            [row.symbol for row in unique_rows]
        )
        timeframe_diversity = _concentration_effective_count(
            [row.timeframe for row in unique_rows]
        )
        cohort_diversity = _concentration_effective_count(
            [row.cohort_id for row in unique_rows]
        )
        policy_diversity = _concentration_effective_count(
            [row.policy_mode for row in unique_rows]
        )
        symbol_factor = min(1.0, symbol_diversity / min(4.0, count))
        timeframe_factor = min(1.0, timeframe_diversity / min(3.0, count))
        cohort_policy_factor = min(
            1.0,
            max(1.0, min(cohort_diversity, policy_diversity)) / min(2.0, count),
        )
        correlation_factor = min(
            symbol_factor, timeframe_factor, cohort_policy_factor
        )
        effective_sample_size = max(
            1e-9,
            min(
                float(count),
                autocorrelation_n,
                float(nonoverlap_count),
                decay_kish,
            )
            * correlation_factor,
        )
        scaled_weights = [
            weight * effective_sample_size / decay_sum for weight in decay_weights
        ]
        weighted_profitable = math.fsum(
            weight * float(row.profitable)
            for row, weight in zip(unique_rows, scaled_weights, strict=True)
        )
        weighted_unprofitable = math.fsum(scaled_weights) - weighted_profitable
    else:
        decay_kish = autocorrelation_n = symbol_diversity = 0.0
        timeframe_diversity = cohort_diversity = policy_diversity = 0.0
        nonoverlap_count = 0
        correlation_factor = 0.0
        effective_sample_size = weighted_profitable = weighted_unprofitable = 0.0
    row_digest = _canonical_sha256([asdict(row) for row in unique_rows])
    material = {
        "schema_version": "authenticated_effective_sample_evidence_v1",
        "raw_row_count": len(rows),
        "natural_execution_count": len(natural_rows),
        "counterfactual_outcome_count": sum(
            not row.realized_execution_outcome for row in rows
        ),
        "unique_candidate_count": len({row.candidate_id for row in rows}),
        "unique_close_count": count,
        "duplicate_execution_revisions_collapsed": len(natural_rows) - count,
        "effective_sample_size": effective_sample_size,
        "effective_sample_method": (
            "DURABLE_CLOSE_COLLAPSE_MIN_AUTOCORRELATION_NONOVERLAP_DECAY_KISH_"
            "WITH_SYMBOL_TIMEFRAME_COHORT_POLICY_CONCENTRATION"
        ),
        "correlation_adjustment": {
            "lag_one_outcome_effective_n": autocorrelation_n,
            "nonoverlapping_execution_interval_count": nonoverlap_count,
            "symbol_effective_diversity": symbol_diversity,
            "timeframe_effective_diversity": timeframe_diversity,
            "cohort_effective_diversity": cohort_diversity,
            "policy_mode_effective_diversity": policy_diversity,
            "combined_correlation_factor": correlation_factor,
            "symbol_correlation_method": "CONSERVATIVE_CONCENTRATION_PROXY",
            "timeframe_overlap_method": "CONSERVATIVE_CONCENTRATION_AND_EXECUTION_INTERVALS",
        },
        "temporal_decay": {
            "method": "EXPONENTIAL_POINT_IN_TIME_DECISION_RECENCY",
            "half_life_days": 30.0,
            "kish_effective_n": decay_kish,
        },
        "checkpoint_generations": sorted(
            {row.checkpoint_generation for row in unique_rows}
        ),
        "cohort_ids": sorted({row.cohort_id for row in unique_rows}),
        "policy_modes": sorted({row.policy_mode for row in unique_rows}),
        "regime_buckets": sorted({row.regime_bucket for row in unique_rows}),
        "row_digest": row_digest,
        "source_archive_chain_sha256": source_archive_chain_sha256,
        "counterfactual_counts_as_independent_realized_executions": False,
    }
    evidence = {**material, "receipt_sha256": _canonical_sha256(material)}
    return evidence, weighted_profitable, weighted_unprofitable


def _posterior_entry(
    *,
    bucket_identity: str,
    parent_bucket_identity: str | None,
    rows: Sequence[CandidateCalibrationObservationV2],
    prior_alpha: float,
    prior_beta: float,
    source_archive_chain_sha256: str,
) -> dict[str, Any]:
    effective, weighted_profitable, weighted_unprofitable = _effective_sample_evidence(
        rows,
        source_archive_chain_sha256=source_archive_chain_sha256,
    )
    alpha = prior_alpha + weighted_profitable
    beta = prior_beta + weighted_unprofitable
    total = alpha + beta
    variance = alpha * beta / (total * total * (total + 1.0))
    information = _beta_bernoulli_information_gain(alpha, beta)
    credible_intervals = {
        str(level): {
            "lower": _beta_quantile((1.0 - level / 100.0) / 2.0, alpha, beta),
            "upper": _beta_quantile(1.0 - (1.0 - level / 100.0) / 2.0, alpha, beta),
        }
        for level in (50, 80, 95)
    }
    return {
        "schema_version": "hierarchical_beta_posterior_bucket_v1",
        "bucket_identity": bucket_identity,
        "parent_bucket_identity": parent_bucket_identity,
        "prior_alpha": prior_alpha,
        "prior_beta": prior_beta,
        "posterior_alpha": alpha,
        "posterior_beta": beta,
        "posterior_mean": alpha / total,
        "posterior_variance": variance,
        "posterior_standard_deviation": math.sqrt(variance),
        "credible_intervals": credible_intervals,
        **information,
        "effective_sample_evidence": effective,
    }


def _hierarchical_profitability_posteriors(
    rows: Sequence[CandidateCalibrationObservationV2],
    *,
    source_archive_chain_sha256: str,
) -> dict[str, Any]:
    levels: dict[str, dict[str, dict[str, Any]]] = {}
    global_entry = _posterior_entry(
        bucket_identity="global",
        parent_bucket_identity=None,
        rows=rows,
        prior_alpha=1.0,
        prior_beta=1.0,
        source_archive_chain_sha256=source_archive_chain_sha256,
    )
    levels["global"] = {"global": global_entry}

    level_specs = (
        ("timeframe", lambda row: row.timeframe, lambda _: "global"),
        (
            "side_timeframe",
            lambda row: f"{row.side}:{row.timeframe}",
            lambda key: key.split(":", 1)[1],
        ),
        (
            "side_timeframe_regime",
            lambda row: f"{row.side}:{row.timeframe}:{row.regime_bucket}",
            lambda key: ":".join(key.split(":")[:2]),
        ),
        (
            "symbol_side_timeframe_regime",
            lambda row: (
                f"{row.symbol}:{row.side}:{row.timeframe}:{row.regime_bucket}"
            ),
            lambda key: ":".join(key.split(":")[1:]),
        ),
    )
    previous_level_name = "global"
    for level_name, key_fn, parent_key_fn in level_specs:
        grouped: dict[str, list[CandidateCalibrationObservationV2]] = defaultdict(list)
        for row in rows:
            grouped[str(key_fn(row))].append(row)
        entries: dict[str, dict[str, Any]] = {}
        for key, members in sorted(grouped.items()):
            parent_key = parent_key_fn(key)
            parent = levels[previous_level_name][parent_key]
            parent_mean = float(parent["posterior_mean"])
            parent_effective_n = float(
                parent["effective_sample_evidence"]["effective_sample_size"]
            )
            shrinkage_strength = min(
                4.0, 2.0 + math.log1p(parent_effective_n)
            )
            entries[key] = _posterior_entry(
                bucket_identity=f"{level_name}:{key}",
                parent_bucket_identity=str(parent["bucket_identity"]),
                rows=members,
                prior_alpha=parent_mean * shrinkage_strength,
                prior_beta=(1.0 - parent_mean) * shrinkage_strength,
                source_archive_chain_sha256=source_archive_chain_sha256,
            )
            entries[key]["parent_shrinkage_strength"] = shrinkage_strength
        levels[level_name] = entries
        previous_level_name = level_name
    material = {
        "schema_version": "hierarchical_beta_profitability_posterior_v1",
        "hierarchy": [
            "global",
            "timeframe",
            "side_timeframe",
            "side_timeframe_regime",
            "symbol_side_timeframe_regime",
        ],
        "outcome_population": "AUTHENTICATED_RECONCILED_NATURAL_EXECUTION_CLOSES_ONLY",
        "point_in_time_regime_source": "decision.component_estimates.regime_compatibility_score",
        "sparse_bucket_shrinkage": "AUTHENTICATED_PARENT_POSTERIOR_EMPIRICAL_BAYES",
        "levels": levels,
        "counterfactual_counts_as_realized_execution_profit": False,
        "source_archive_chain_sha256": source_archive_chain_sha256,
    }
    return {**material, "posterior_hierarchy_sha256": _canonical_sha256(material)}


def _select_posterior(
    hierarchy: Mapping[str, Any], row: CandidateCalibrationObservationV2
) -> Mapping[str, Any]:
    levels = hierarchy["levels"]
    keys = (
        (
            "symbol_side_timeframe_regime",
            f"{row.symbol}:{row.side}:{row.timeframe}:{row.regime_bucket}",
        ),
        (
            "side_timeframe_regime",
            f"{row.side}:{row.timeframe}:{row.regime_bucket}",
        ),
        ("side_timeframe", f"{row.side}:{row.timeframe}"),
        ("timeframe", row.timeframe),
        ("global", "global"),
    )
    for level, key in keys:
        entry = levels[level].get(key)
        if isinstance(entry, Mapping):
            return entry
    _fail("posterior_bucket_missing", "profitability_posterior_hierarchy")


def _reliability_metrics(
    rows: Sequence[CandidateCalibrationObservationV2],
    hierarchy: Mapping[str, Any],
) -> dict[str, Any]:
    if not rows:
        return {
            "sample_count": 0,
            "brier_score": None,
            "log_loss": None,
            "ece": None,
            "residual_dispersion": None,
            "residual_bias": None,
            "outcome_surprise": {"mean_nats": None, "p90_nats": None},
        }
    probabilities = [
        float(_select_posterior(hierarchy, row)["posterior_mean"]) for row in rows
    ]
    targets = [float(row.profitable) for row in rows]
    residuals = [target - probability for target, probability in zip(targets, probabilities, strict=True)]
    surprises = [
        -math.log(
            max(1e-15, probability if target else 1.0 - probability)
        )
        for target, probability in zip(targets, probabilities, strict=True)
    ]
    ordered_surprises = sorted(surprises)
    return {
        "sample_count": len(rows),
        "brier_score": statistics.fmean(
            residual * residual for residual in residuals
        ),
        "log_loss": statistics.fmean(surprises),
        "ece": abs(statistics.fmean(probabilities) - statistics.fmean(targets)),
        "residual_dispersion": math.sqrt(
            statistics.fmean(residual * residual for residual in residuals)
        ),
        "residual_bias": statistics.fmean(residuals),
        "outcome_surprise": {
            "mean_nats": statistics.fmean(surprises),
            "p90_nats": ordered_surprises[
                round((len(ordered_surprises) - 1) * 0.9)
            ],
        },
    }


def _holdout_evaluation(
    holdout_rows: Sequence[CandidateCalibrationObservationV2],
    hierarchy: Mapping[str, Any],
) -> dict[str, Any]:
    natural = [row for row in holdout_rows if row.realized_execution_outcome]
    dimensions: dict[str, dict[str, Any]] = {}
    for dimension, key_fn in (
        ("symbol", lambda row: row.symbol),
        ("side", lambda row: row.side),
        ("timeframe", lambda row: row.timeframe),
        ("regime", lambda row: row.regime_bucket),
    ):
        grouped: dict[str, list[CandidateCalibrationObservationV2]] = defaultdict(list)
        for row in natural:
            grouped[str(key_fn(row))].append(row)
        dimensions[dimension] = {
            key: _reliability_metrics(members, hierarchy)
            for key, members in sorted(grouped.items())
        }
    coverage: dict[str, float | None] = {}
    grouped_buckets: dict[str, list[CandidateCalibrationObservationV2]] = defaultdict(list)
    for row in natural:
        posterior = _select_posterior(hierarchy, row)
        grouped_buckets[str(posterior["bucket_identity"])].append(row)
    for level in (50, 80, 95):
        included: list[bool] = []
        for members in grouped_buckets.values():
            posterior = _select_posterior(hierarchy, members[0])
            interval = posterior["credible_intervals"][str(level)]
            realized_rate = statistics.fmean(row.profitable for row in members)
            included.append(
                float(interval["lower"]) <= realized_rate <= float(interval["upper"])
            )
        coverage[str(level)] = statistics.fmean(included) if included else None
    return {
        "schema_version": "profitability_holdout_evaluation_v1",
        "population": "AUTHENTICATED_RECONCILED_NATURAL_EXECUTION_CLOSES_ONLY",
        "holdout_row_count": len(holdout_rows),
        "natural_execution_holdout_count": len(natural),
        "counterfactual_holdout_count": len(holdout_rows) - len(natural),
        "metrics": _reliability_metrics(natural, hierarchy),
        "reliability_by_dimension": dimensions,
        "credible_interval_coverage": coverage,
        "holdout_used_to_select_uncertainty_coefficients": False,
        "counterfactual_counts_as_realized_execution_profit": False,
        "holdout_row_digest": _canonical_sha256([asdict(row) for row in holdout_rows]),
    }


def _probability_semantics() -> dict[str, Any]:
    return {
        "schema_version": "adaptive_probability_semantics_v1",
        "confidence_raw": {
            "source_field": "model_distributions.selected_action_probability",
            "meaning": "ACTION_CLASS_PROBABILITY",
            "is_profitability_probability": False,
            "producer_contract": "v2.backend.app.services.rl_core.trainer_output",
            "producer_definition": "softmax_probability_at_selected_action_index",
        },
        "confidence_calibrated": {
            "source_field": "model_distributions.confidence_calibrated",
            "meaning": "CALIBRATED_ACTION_CLASS_CONFIDENCE",
            "is_profitability_probability": False,
            "producer_contract": "v2.backend.app.services.rl_core.trainer_output",
            "producer_definition": "temperature_scaled_selected_action_logit",
        },
        "confidence_to_profitability": {
            "meaning": "P_POSITIVE_AFTER_COST_REFERENCE_OUTCOME_CONDITIONAL_ON_ACTION_CONFIDENCE",
            "population": "MATURED_CANDIDATE_REFERENCE_OUTCOMES",
            "is_realized_execution_profitability_probability": False,
        },
        "win_rate_posterior_mean": {
            "meaning": "P_POSITIVE_AFTER_COST_NATURAL_EXECUTION_OUTCOME",
            "population": "AUTHENTICATED_RECONCILED_NATURAL_EXECUTION_CLOSES_ONLY",
        },
        "loss_probability": {
            "meaning": "P_NEGATIVE_AFTER_COST_NATURAL_EXECUTION_OUTCOME",
            "population": "AUTHENTICATED_RECONCILED_NATURAL_EXECUTION_CLOSES_ONLY",
        },
        "posterior_uncertainty": {
            "meaning": "EPISTEMIC_STANDARD_DEVIATION_OF_PROFITABILITY_PARAMETER",
            "is_predictive_aleatoric_uncertainty": False,
        },
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
        "correlation_penalty",
    )
    correlation_measured_rows = sum(
        1 for row in rows if row.correlation_exposure_source is not None
    )
    feature_rows = [
        (
            abs(row.max_adverse_excursion_bps),
            max(0.0, -row.final_after_cost_return_bps),
            float(row.stop_hit),
            row.market_impact_bps,
            abs(row.funding_bps),
            row.transaction_cost_bps,
            (
                0.0
                if row.correlation_exposure_source is None
                else row.correlation_exposure_source
            )
            * abs(row.max_adverse_excursion_bps),
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
    realized_log_growth = [
        abs(math.log1p(max(-0.999999999999, row.final_after_cost_return_bps / 10_000.0)))
        for row in rows
    ]
    observed_log_growth_scale = max(
        1e-12,
        statistics.fmean(realized_log_growth),
    )
    expected_log_equity_growth_reward = max(
        1e-6,
        return_scale / observed_log_growth_scale,
    )
    terminal_target_probability_reward = max(
        1e-6,
        expected_log_equity_growth_reward * math.log(1000.0),
    )
    expected_return_pairs = [
        (
            float(row.expected_move_after_cost_source_bps),
            row.final_after_cost_return_bps,
        )
        for row in rows
        if row.expected_move_after_cost_source_bps is not None
    ]
    expected_return_denominator = math.fsum(
        predicted * predicted for predicted, _realized in expected_return_pairs
    )
    expected_after_cost_return = max(
        1e-6,
        (
            math.fsum(
                predicted * realized
                for predicted, realized in expected_return_pairs
            )
            / expected_return_denominator
            if expected_return_denominator > 0.0
            else 1.0 / (1.0 + return_scale)
        ),
    )
    parameters = {
        "schema_version": WEIGHTS_SCHEMA_VERSION,
        "expected_after_cost_return": expected_after_cost_return,
        "terminal_target_probability_reward": terminal_target_probability_reward,
        "expected_log_equity_growth_reward": expected_log_equity_growth_reward,
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
        "terminal_target_multiple": 1000.0,
        "terminal_target_probability_reward_learned_online": False,
        "terminal_target_probability_reward_derivation": {
            "method": (
                "EXPECTED_LOG_EQUITY_GROWTH_REWARD_TIMES_LN_TARGET_MULTIPLE"
            ),
            "source_parameters": {
                "expected_log_equity_growth_reward": (
                    expected_log_equity_growth_reward
                ),
                "terminal_target_multiple": 1000.0,
            },
            "derived_value": terminal_target_probability_reward,
        },
        "terminal_target_probability_selection_authority": False,
        "expected_log_equity_growth_reward_learned_online": False,
        "expected_log_equity_growth_reward_derivation": {
            "method": (
                "RETURN_SCALE_DIVIDED_BY_MEAN_ABSOLUTE_REALIZED_LOG_RETURN"
            ),
            "source_parameters": {
                "return_scale_bps": return_scale,
                "mean_absolute_realized_log_return": observed_log_growth_scale,
            },
            "derived_value": expected_log_equity_growth_reward,
        },
        # Rows archived before the correlation-exposure contract carry no
        # measured exposure; they contribute zero to the correlation feature
        # and are counted here rather than silently imputed.  A coefficient
        # cannot be claimed as empirically learned from a feature that was
        # absent for every fit row: with zero measured rows the fitted value
        # is pure regularized-prior initialization and is attested as such.
        "correlation_penalty_learned_online": correlation_measured_rows > 0,
        "correlation_penalty_evidence_available": correlation_measured_rows > 0,
        "correlation_penalty_derivation_or_initialization": (
            "CONSTRAINED_LOGISTIC_FIT_ON_MEASURED_CORRELATION_EXPOSURE"
            "_TIMES_ABS_MAE"
            if correlation_measured_rows > 0
            else "REGULARIZED_LOGISTIC_PRIOR_ONLY_ZERO_FEATURE"
            "_NO_MEASURED_EXPOSURE_ROWS"
        ),
        "correlation_exposure_measured_row_count": correlation_measured_rows,
        "correlation_exposure_missing_row_count": (
            len(rows) - correlation_measured_rows
        ),
        "expected_after_cost_return_reward_learned_online": True,
        "all_economic_tradeoff_weights_learned_online": False,
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
    if len(unique_times) < 3:
        _fail("three_chronological_time_groups_required", "observations")
    calibration_index = max(
        1,
        min(
            len(unique_times) - 2 * MINIMUM_VALIDATION_ROWS,
            int(len(unique_times) * 0.70),
        ),
    )
    holdout_index = min(
        len(unique_times) - MINIMUM_VALIDATION_ROWS,
        max(
            calibration_index + MINIMUM_VALIDATION_ROWS,
            int(len(unique_times) * 0.85),
        ),
    )
    calibration_start = unique_times[calibration_index]
    holdout_start = unique_times[holdout_index]
    fit_rows = [row for row in rows if row.decision_time_ms < calibration_start]
    calibration_rows = [
        row
        for row in rows
        if calibration_start <= row.decision_time_ms < holdout_start
    ]
    holdout_rows = [row for row in rows if row.decision_time_ms >= holdout_start]
    if len(fit_rows) < MINIMUM_FIT_ROWS:
        _fail("minimum_fit_rows_not_met", "observations")
    if len(calibration_rows) < MINIMUM_VALIDATION_ROWS:
        _fail("minimum_calibration_rows_not_met", "observations")
    if len(holdout_rows) < MINIMUM_VALIDATION_ROWS:
        _fail("minimum_holdout_rows_not_met", "observations")
    # The profitability Beta posterior counts AUTHENTICATED RECONCILED
    # NATURAL EXECUTION CLOSES (its declared population): a realized close is
    # ground-truth outcome evidence, not a fitted coefficient, so recency
    # never excludes it.  Counterfactual rows keep the chronological
    # partition discipline exactly as before (holdout counterfactuals stay
    # out), and the learned weights / probability calibrations continue to
    # fit only on the partitioned rows.
    posterior_rows = [
        *fit_rows,
        *calibration_rows,
        *[row for row in holdout_rows if row.realized_execution_outcome],
    ]
    posterior_hierarchy = _hierarchical_profitability_posteriors(
        posterior_rows,
        source_archive_chain_sha256=source_archive_chain_sha256,
    )
    global_posterior = posterior_hierarchy["levels"]["global"]["global"]
    fit_statistics = _statistics(
        fit_rows, profitability_posterior=global_posterior
    )
    groups: dict[str, list[CandidateCalibrationObservationV2]] = defaultdict(list)
    for row in fit_rows:
        groups[f"{row.side}:{row.timeframe}"].append(row)
    group_statistics = {
        name: _statistics(
            group,
            profitability_posterior=posterior_hierarchy["levels"][
                "side_timeframe"
            ].get(name, global_posterior),
        )
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
    expected_return = float(fit_statistics["after_cost_expectancy_bps"])
    holdout_evaluation = _holdout_evaluation(holdout_rows, posterior_hierarchy)
    holdout_metrics = holdout_evaluation["metrics"]
    validation_mae = statistics.fmean(
        abs(expected_return - row.final_after_cost_return_bps)
        for row in holdout_rows
    )
    global_effective = global_posterior["effective_sample_evidence"]
    recent_surprise = holdout_metrics["outcome_surprise"]
    uncertainty_calibration = {
        "schema_version": "posterior_uncertainty_calibration_v2",
        "method": "HIERARCHICAL_BETA_EFFECTIVE_INDEPENDENT_N",
        "diagnosis": (
            "PARTIALLY_VALID_ROOT_CAUSE_REFINED_TO_RAW_N_AND_SEMANTIC_MISMATCH"
        ),
        "raw_row_count": len(posterior_rows),
        "natural_execution_count": global_effective["natural_execution_count"],
        "unique_candidate_count": global_effective["unique_candidate_count"],
        "unique_close_count": global_effective["unique_close_count"],
        "effective_sample_size": global_effective["effective_sample_size"],
        "effective_sample_method": global_effective["effective_sample_method"],
        "correlation_adjustment": global_effective["correlation_adjustment"],
        "temporal_decay": global_effective["temporal_decay"],
        "checkpoint_generation": next(iter(lineage))[0],
        "cohort_ids": global_effective["cohort_ids"],
        "row_digest": global_effective["row_digest"],
        "receipt_sha256": global_effective["receipt_sha256"],
        "posterior_alpha": global_posterior["posterior_alpha"],
        "posterior_beta": global_posterior["posterior_beta"],
        "posterior_mean": global_posterior["posterior_mean"],
        "posterior_variance": global_posterior["posterior_variance"],
        "epistemic_parameter_uncertainty": global_posterior[
            "posterior_standard_deviation"
        ],
        "prior_entropy": global_posterior["prior_entropy"],
        "expected_posterior_entropy": global_posterior[
            "expected_posterior_entropy"
        ],
        "expected_information_gain_nats": global_posterior[
            "expected_information_gain_nats"
        ],
        "epistemic_signal_components": {
            "bucket_sparsity": 1.0
            / (1.0 + float(global_effective["effective_sample_size"])),
            "chronological_holdout_calibration_residual": holdout_metrics[
                "residual_dispersion"
            ],
            "recent_outcome_surprise_mean_nats": recent_surprise["mean_nats"],
            "regime_drift": {
                "available": bool(holdout_rows),
                "method": "POINT_IN_TIME_REGIME_BUCKET_FREQUENCY_AUDIT",
            },
            "feature_distribution_drift": {
                "available": False,
                "reason": "NOT_PRESENT_IN_CANDIDATE_OUTCOME_CALIBRATION_CONTRACT",
            },
            "challenger_ensemble_disagreement": {
                "available": False,
                "reason": "NO_AUTHENTICATED_MULTI_MODEL_PROJECTION_IN_THIS_ARTIFACT",
            },
        },
        "bounded_learned_epistemic_estimate": global_posterior[
            "posterior_standard_deviation"
        ],
        "predictive_aleatoric_dispersion_used_as_epistemic_authority": False,
        "arbitrary_multiplier_used": False,
        "tuned_to_create_trades": False,
        "chronological_calibration_period_used_for_posterior": True,
        "untouched_holdout_used_for_posterior": False,
        "objective_weights_use_holdout": False,
        "return_parameters_use_holdout": False,
        "holdout_evaluation": holdout_evaluation,
        "counterfactual_outcome_count": global_effective[
            "counterfactual_outcome_count"
        ],
        "realized_execution_outcome_count": global_effective[
            "natural_execution_count"
        ],
        "counterfactual_counts_as_realized_execution_profit": False,
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
    validation_row_digest = _canonical_sha256(
        [asdict(row) for row in calibration_rows]
    )
    holdout_row_digest = _canonical_sha256([asdict(row) for row in holdout_rows])
    uncertainty_calibration_sha256 = _canonical_sha256(uncertainty_calibration)
    posterior_hierarchy_sha256 = posterior_hierarchy[
        "posterior_hierarchy_sha256"
    ]
    probability_semantics = _probability_semantics()
    probability_semantics_sha256 = _canonical_sha256(probability_semantics)
    population_sha256 = _canonical_sha256([row.candidate_id for row in rows])
    fit_receipt_sha256 = _canonical_sha256(
        {
            "fit_row_digest": fit_row_digest,
            "source_archive_chain_sha256": source_archive_chain_sha256,
            "objective_parameter_fingerprint": weights["objective_parameter_fingerprint"],
            "uncertainty_calibration_sha256": uncertainty_calibration_sha256,
            "posterior_hierarchy_sha256": posterior_hierarchy_sha256,
            "probability_semantics_sha256": probability_semantics_sha256,
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
        "validation_window_start_ms": calibration_rows[0].decision_time_ms,
        "validation_window_end_ms": calibration_rows[-1].decision_time_ms,
        "holdout_window_start_ms": holdout_rows[0].decision_time_ms,
        "holdout_window_end_ms": holdout_rows[-1].decision_time_ms,
        "fit_record_available_at_ms": generated_at_ms,
        "fit_sample_count": len(fit_rows),
        "validation_sample_count": len(calibration_rows),
        "holdout_sample_count": len(holdout_rows),
        "holdout_used_for_fitting": False,
        "fit_row_digest": fit_row_digest,
        "validation_row_digest": validation_row_digest,
        "holdout_row_digest": holdout_row_digest,
        "uncertainty_calibration_sha256": uncertainty_calibration_sha256,
        "posterior_hierarchy_sha256": posterior_hierarchy_sha256,
        "probability_semantics_sha256": probability_semantics_sha256,
        "training_population_sha256": population_sha256,
        "fit_receipt_sha256": fit_receipt_sha256,
        "global_statistics": fit_statistics,
        "side_timeframe_statistics": group_statistics,
        "profitability_posterior_hierarchy": posterior_hierarchy,
        "probability_semantics": probability_semantics,
        "calibrators": {
            "confidence_to_profitability": confidence_bins,
            "loss_score_to_loss_probability": loss_bins,
            "exit_score_to_profit_exit_probability": exit_bins,
        },
        "validation": {
            "frozen_global_probability_brier": holdout_metrics["brier_score"],
            "frozen_global_probability_log_loss": holdout_metrics["log_loss"],
            "frozen_global_probability_ece": holdout_metrics["ece"],
            "frozen_global_return_mae_bps": validation_mae,
            "parameters_changed_after_validation": False,
            "objective_and_return_parameters_changed_after_validation": False,
            "posterior_uncertainty_changed_after_validation": False,
            "untouched_holdout": holdout_evaluation,
        },
        "posterior_uncertainty_calibration": uncertainty_calibration,
        "heldout_used_for_uncertainty_calibration": False,
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
        or int(artifact["validation_window_end_ms"])
        >= int(artifact["holdout_window_start_ms"])
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
        artifact.get("heldout_used_for_uncertainty_calibration") is not False
        or uncertainty.get("method")
        != "HIERARCHICAL_BETA_EFFECTIVE_INDEPENDENT_N"
        or uncertainty.get("untouched_holdout_used_for_posterior") is not False
        or uncertainty.get("objective_weights_use_holdout") is not False
        or uncertainty.get("return_parameters_use_holdout") is not False
        or uncertainty.get("predictive_aleatoric_dispersion_used_as_epistemic_authority")
        is not False
        or uncertainty.get("arbitrary_multiplier_used") is not False
        or uncertainty.get("tuned_to_create_trades") is not False
        or uncertainty.get("counterfactual_counts_as_realized_execution_profit")
        is not False
        or validation.get("objective_and_return_parameters_changed_after_validation")
        is not False
        or validation.get("posterior_uncertainty_changed_after_validation")
        is not False
        or validation.get("parameters_changed_after_validation")
        is not False
        or artifact.get("uncertainty_calibration_sha256")
        != _canonical_sha256(uncertainty)
    ):
        _fail("uncertainty_calibration_invalid", "posterior_uncertainty_calibration")
    global_statistics = artifact.get("global_statistics")
    if (
        not isinstance(global_statistics, Mapping)
        or global_statistics.get("posterior_uncertainty")
        != uncertainty.get("epistemic_parameter_uncertainty")
        or global_statistics.get("posterior_uncertainty_source")
        != "HIERARCHICAL_BETA_EFFECTIVE_N_NATURAL_EXECUTIONS"
        or global_statistics.get("expected_information_gain_nats")
        != uncertainty.get("expected_information_gain_nats")
    ):
        _fail("uncertainty_projection_mismatch", "global_statistics")
    hierarchy = artifact.get("profitability_posterior_hierarchy")
    semantics = artifact.get("probability_semantics")
    if (
        not isinstance(hierarchy, Mapping)
        or hierarchy.get("counterfactual_counts_as_realized_execution_profit")
        is not False
        or artifact.get("posterior_hierarchy_sha256")
        != hierarchy.get("posterior_hierarchy_sha256")
        or not isinstance(semantics, Mapping)
        or artifact.get("probability_semantics_sha256")
        != _canonical_sha256(semantics)
        or semantics.get("confidence_calibrated", {}).get(
            "is_profitability_probability"
        )
        is not False
    ):
        _fail("posterior_or_probability_semantics_invalid", "epistemic_contract")
    if (
        int(artifact["fit_sample_count"]) < MINIMUM_FIT_ROWS
        or int(artifact["validation_sample_count"]) < MINIMUM_VALIDATION_ROWS
        or int(artifact["holdout_sample_count"]) < MINIMUM_VALIDATION_ROWS
    ):
        _fail("minimum_samples_not_met", "sample_count")
    weights = artifact.get("learned_objective_weights")
    if not isinstance(weights, Mapping):
        _fail("weights_required", "learned_objective_weights")
    if weights.get("schema_version") != WEIGHTS_SCHEMA_VERSION:
        _fail("invalid_schema_version", "learned_objective_weights.schema_version")
    if weights.get("unit_contract") != UNIT_CONTRACT:
        _fail("invalid_unit_contract", "learned_objective_weights.unit_contract")
    for field in REQUIRED_OBJECTIVE_WEIGHT_FIELDS:
        value = _finite(
            weights.get(field), f"learned_objective_weights.{field}"
        )
        if value <= 0.0:
            _fail("strictly_positive_required", f"learned_objective_weights.{field}")
    parameter_material = dict(weights)
    fingerprint = parameter_material.pop("objective_parameter_fingerprint", None)
    if fingerprint != _canonical_sha256(parameter_material):
        _fail("parameter_fingerprint_mismatch", "learned_objective_weights")
    optimizer = artifact.get("objective_weight_optimizer")
    if not isinstance(optimizer, Mapping):
        _fail("optimizer_evidence_required", "objective_weight_optimizer")
    log_growth_derivation = optimizer.get(
        "expected_log_equity_growth_reward_derivation"
    )
    target_probability_derivation = optimizer.get(
        "terminal_target_probability_reward_derivation"
    )
    log_growth_sources = (
        log_growth_derivation.get("source_parameters")
        if isinstance(log_growth_derivation, Mapping)
        else None
    )
    target_probability_sources = (
        target_probability_derivation.get("source_parameters")
        if isinstance(target_probability_derivation, Mapping)
        else None
    )
    if not isinstance(log_growth_sources, Mapping) or not isinstance(
        target_probability_sources, Mapping
    ):
        _fail("derivation_sources_required", "objective_weight_optimizer")
    derivation_return_scale = _finite(
        log_growth_sources.get("return_scale_bps"),
        "objective_weight_optimizer.log_growth.return_scale_bps",
    )
    derivation_mean_log_return = _finite(
        log_growth_sources.get("mean_absolute_realized_log_return"),
        "objective_weight_optimizer.log_growth.mean_absolute_realized_log_return",
    )
    derivation_target_multiple = _finite(
        target_probability_sources.get("terminal_target_multiple"),
        "objective_weight_optimizer.target.terminal_target_multiple",
    )
    if (
        derivation_return_scale <= 0.0
        or derivation_mean_log_return <= 0.0
        or derivation_target_multiple != 1000.0
    ):
        _fail("positive_derivation_sources_required", "objective_weight_optimizer")
    derived_log_growth_reward = max(
        1e-6,
        derivation_return_scale / derivation_mean_log_return,
    )
    derived_target_probability_reward = max(
        1e-6,
        _finite(
            target_probability_sources.get("expected_log_equity_growth_reward"),
            "objective_weight_optimizer.target.expected_log_equity_growth_reward",
        )
        * math.log(derivation_target_multiple),
    )
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
        or optimizer.get("terminal_target_multiple") != 1000.0
        or optimizer.get("expected_log_equity_growth_reward_learned_online")
        is not False
        or optimizer.get("terminal_target_probability_reward_learned_online")
        is not False
        or optimizer.get("terminal_target_probability_selection_authority")
        is not False
        or optimizer.get("all_economic_tradeoff_weights_learned_online")
        is not False
        or not isinstance(log_growth_derivation, Mapping)
        or log_growth_derivation.get("method")
        != "RETURN_SCALE_DIVIDED_BY_MEAN_ABSOLUTE_REALIZED_LOG_RETURN"
        or log_growth_derivation.get("derived_value")
        != weights.get("expected_log_equity_growth_reward")
        or not math.isclose(
            derived_log_growth_reward,
            float(weights["expected_log_equity_growth_reward"]),
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        or not isinstance(target_probability_derivation, Mapping)
        or target_probability_derivation.get("method")
        != "EXPECTED_LOG_EQUITY_GROWTH_REWARD_TIMES_LN_TARGET_MULTIPLE"
        or target_probability_derivation.get("derived_value")
        != weights.get("terminal_target_probability_reward")
        or target_probability_sources.get("expected_log_equity_growth_reward")
        != weights.get("expected_log_equity_growth_reward")
        or not math.isclose(
            derived_target_probability_reward,
            float(weights["terminal_target_probability_reward"]),
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
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
