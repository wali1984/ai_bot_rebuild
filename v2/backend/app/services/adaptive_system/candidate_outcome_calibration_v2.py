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

SCHEMA_VERSION = "candidate_outcome_calibration_v2"
OBSERVATION_SCHEMA_VERSION = "candidate_calibration_observation_v2"
MINIMUM_FIT_ROWS = 40
MINIMUM_VALIDATION_ROWS = 10
MINIMUM_GROUP_ROWS = 10
CALIBRATION_BIN_COUNT = 5


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
    side = str(proposed.get("proposed_action") or proposed.get("side") or "").upper()
    unhedged = next(
        (arm for arm in labels.counterfactual_outcomes if arm.arm_name == "unhedged"),
        None,
    )
    if unhedged is None or not unhedged.scenarios:
        _fail("unhedged_counterfactual_required", "matured_labels")
    after_cost = statistics.fmean(scenario.after_cost_pnl_bps for scenario in unhedged.scenarios)
    gross = statistics.fmean(scenario.gross_pnl_bps for scenario in unhedged.scenarios)
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


def _learned_weights(rows: Sequence[CandidateCalibrationObservationV2]) -> dict[str, Any]:
    mean_abs_return = max(
        0.01,
        statistics.fmean(abs(row.final_after_cost_return_bps) for row in rows),
    )
    mean_drawdown = max(
        0.01,
        statistics.fmean(abs(row.max_adverse_excursion_bps) for row in rows),
    )
    mean_tail = max(
        0.01,
        statistics.fmean(max(0.0, -row.final_after_cost_return_bps) for row in rows),
    )
    mean_impact = max(0.01, statistics.fmean(row.market_impact_bps for row in rows))
    mean_funding = max(0.01, statistics.fmean(abs(row.funding_bps) for row in rows))
    mean_cost = max(0.01, statistics.fmean(row.transaction_cost_bps for row in rows))
    parameters = {
        "schema_version": WEIGHTS_SCHEMA_VERSION,
        "expected_after_cost_return": 1.0,
        "drawdown_penalty": max(0.01, mean_tail / mean_drawdown),
        "tail_loss_penalty": max(0.01, mean_tail / mean_abs_return),
        "liquidation_risk_penalty": mean_tail,
        "market_impact_penalty": max(0.01, mean_cost / mean_impact),
        "funding_cost_penalty": max(0.01, mean_cost / mean_funding),
        "turnover_penalty": max(0.01, mean_cost / mean_abs_return),
        "concentration_penalty": max(0.01, mean_tail / (10.0 * mean_abs_return)),
        "information_gain_reward": max(0.01, mean_abs_return * 0.1),
        "unit_contract": UNIT_CONTRACT,
    }
    return {**parameters, "objective_parameter_fingerprint": _canonical_sha256(parameters)}


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
    missed_profitable_rate = _posterior(
        [
            row.profitable
            for row in fit_rows
            if row.decision_disposition in {"REJECTED", "INFEASIBLE"}
        ]
    )
    bounded_exploration_probability = min(
        0.5,
        max(0.01, missed_profitable_rate),
    )
    weights = _learned_weights(fit_rows)
    checkpoint_generation, checkpoint_id, checkpoint_sha256 = next(iter(lineage))
    fit_row_digest = _canonical_sha256([asdict(row) for row in fit_rows])
    validation_row_digest = _canonical_sha256([asdict(row) for row in validation_rows])
    population_sha256 = _canonical_sha256([row.candidate_id for row in rows])
    fit_receipt_sha256 = _canonical_sha256(
        {
            "fit_row_digest": fit_row_digest,
            "source_archive_chain_sha256": source_archive_chain_sha256,
            "objective_parameter_fingerprint": weights["objective_parameter_fingerprint"],
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
            "parameters_changed_after_validation": False,
        },
        "learned_objective_weights": weights,
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
        or artifact.get("validation", {}).get("parameters_changed_after_validation") is not False
    ):
        _fail("chronological_fit_validation_boundary_invalid", "split")
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
    "extract_calibration_observation",
    "fit_candidate_outcome_calibration_v2",
    "validate_candidate_outcome_calibration_v2",
)
