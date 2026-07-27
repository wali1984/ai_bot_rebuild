"""Pure shadow evaluator for an evidence-fitted adaptive portfolio objective."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass

SCHEMA_VERSION = "adaptive_portfolio_objective_v2"
AUTHORITY_MODE = "SHADOW_DIAGNOSTIC_ONLY"

CHAMPION_EXPLOITATION = "CHAMPION_EXPLOITATION"
BOUNDED_EXPLORATION = "BOUNDED_INFORMATION_SEEKING_EXPLORATION"
POLICY_MODES = (CHAMPION_EXPLOITATION, BOUNDED_EXPLORATION)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AdaptiveObjectiveContractError(ValueError):
    pass


def _raise(reason: str, field: str) -> None:
    raise AdaptiveObjectiveContractError(f"{field}:{reason}")


def _require_identifier(value: object, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        _raise("must_be_non_empty_without_whitespace", field)


def _require_sha256(value: object, field: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _raise("must_be_lowercase_sha256", field)


def _require_finite(value: object, field: str) -> None:
    if not isinstance(value, float) or isinstance(value, bool) or not math.isfinite(value):
        _raise("must_be_finite_float", field)


def _require_nonnegative(value: object, field: str) -> None:
    _require_finite(value, field)
    if value < 0.0:
        _raise("must_be_nonnegative", field)


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FittedObjectiveEvidenceV2:
    optimizer_id: str
    optimizer_family: str
    objective_parameter_fingerprint: str
    fit_receipt_sha256: str
    training_row_digest: str
    training_population_sha256: str
    fit_window_start_ms: int
    fit_window_end_ms: int
    sample_count: int
    checkpoint_generation: int
    checkpoint_id: str
    checkpoint_sha256: str
    fitted: bool
    holdout_used_for_fitting: bool
    paper_only: bool

    def __post_init__(self) -> None:
        for field in ("optimizer_id", "optimizer_family", "checkpoint_id"):
            _require_identifier(getattr(self, field), field)
        for field in (
            "objective_parameter_fingerprint",
            "fit_receipt_sha256",
            "training_row_digest",
            "training_population_sha256",
            "checkpoint_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        for field in (
            "fit_window_start_ms",
            "fit_window_end_ms",
            "sample_count",
            "checkpoint_generation",
        ):
            value = getattr(self, field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                _raise("must_be_positive_int", field)
        if self.fit_window_start_ms > self.fit_window_end_ms:
            _raise("window_order_invalid", "fit_window_end_ms")
        if self.fitted is not True:
            _raise("must_be_true", "fitted")
        if self.holdout_used_for_fitting is not False:
            _raise("must_be_false", "holdout_used_for_fitting")
        if self.paper_only is not True:
            _raise("must_be_true", "paper_only")


@dataclass(frozen=True, slots=True)
class LearnedObjectiveWeightsV2:
    expected_after_cost_return: float
    drawdown_penalty: float
    tail_loss_penalty: float
    liquidation_risk_penalty: float
    market_impact_penalty: float
    funding_cost_penalty: float
    turnover_penalty: float
    concentration_penalty: float
    information_gain_reward: float
    evidence: FittedObjectiveEvidenceV2

    def __post_init__(self) -> None:
        for field in (
            "expected_after_cost_return",
            "drawdown_penalty",
            "tail_loss_penalty",
            "liquidation_risk_penalty",
            "market_impact_penalty",
            "funding_cost_penalty",
            "turnover_penalty",
            "concentration_penalty",
            "information_gain_reward",
        ):
            value = getattr(self, field)
            _require_finite(value, field)
            if value <= 0.0:
                _raise("must_be_strictly_positive_fitted_weight", field)
        if not isinstance(self.evidence, FittedObjectiveEvidenceV2):
            _raise("structured_fit_evidence_required", "evidence")
        parameter_values = {
            field: getattr(self, field)
            for field in (
                "expected_after_cost_return",
                "drawdown_penalty",
                "tail_loss_penalty",
                "liquidation_risk_penalty",
                "market_impact_penalty",
                "funding_cost_penalty",
                "turnover_penalty",
                "concentration_penalty",
                "information_gain_reward",
            )
        }
        if _canonical_hash(parameter_values) != self.evidence.objective_parameter_fingerprint:
            _raise("must_match_fitted_parameter_fingerprint", "evidence")


@dataclass(frozen=True, slots=True)
class AdaptivePolicyModeAllocationV2:
    champion_exploitation_probability: float
    bounded_exploration_probability: float
    allocation_parameter_fingerprint: str
    fit_receipt_sha256: str
    optimizer_id: str
    state_sha256: str
    checkpoint_generation: int
    fitted: bool
    permanent_percentage: bool

    def __post_init__(self) -> None:
        for field in (
            "champion_exploitation_probability",
            "bounded_exploration_probability",
        ):
            value = getattr(self, field)
            _require_finite(value, field)
            if not 0.0 < value < 1.0:
                _raise("must_be_strictly_inside_unit_interval", field)
        if not math.isclose(
            self.champion_exploitation_probability + self.bounded_exploration_probability,
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            _raise("probabilities_must_sum_to_one", "mode_allocation")
        for field in (
            "allocation_parameter_fingerprint",
            "fit_receipt_sha256",
            "state_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        _require_identifier(self.optimizer_id, "optimizer_id")
        if not isinstance(self.checkpoint_generation, int) or self.checkpoint_generation < 1:
            _raise("must_be_positive_int", "checkpoint_generation")
        if self.fitted is not True:
            _raise("must_be_true", "fitted")
        if self.permanent_percentage is not False:
            _raise("must_be_false", "permanent_percentage")
        parameters = {
            "champion_exploitation_probability": self.champion_exploitation_probability,
            "bounded_exploration_probability": self.bounded_exploration_probability,
            "state_sha256": self.state_sha256,
            "checkpoint_generation": self.checkpoint_generation,
        }
        if _canonical_hash(parameters) != self.allocation_parameter_fingerprint:
            _raise("must_match_fitted_parameter_fingerprint", "mode_allocation")


@dataclass(frozen=True, slots=True)
class ActionObjectiveInputsV2:
    action_id: str
    action_sha256: str
    checkpoint_generation: int
    checkpoint_id: str
    checkpoint_sha256: str
    selected_action: str
    policy_mode: str
    expected_after_cost_return_bps: float
    expected_drawdown_contribution_bps: float
    expected_tail_loss_bps: float
    liquidation_risk_probability: float
    expected_market_impact_bps: float
    expected_funding_cost_bps: float
    expected_turnover_bps: float
    expected_concentration_bps: float
    expected_information_gain: float
    hard_constraints_satisfied: bool
    hard_validator_receipt_sha256: str | None
    paper_only: bool

    def __post_init__(self) -> None:
        _require_identifier(self.action_id, "action_id")
        _require_sha256(self.action_sha256, "action_sha256")
        if not isinstance(self.checkpoint_generation, int) or self.checkpoint_generation < 1:
            _raise("must_be_positive_int", "checkpoint_generation")
        _require_identifier(self.checkpoint_id, "checkpoint_id")
        _require_sha256(self.checkpoint_sha256, "checkpoint_sha256")
        _require_identifier(self.selected_action, "selected_action")
        if self.policy_mode not in POLICY_MODES:
            _raise("invalid_policy_mode", "policy_mode")
        _require_finite(
            self.expected_after_cost_return_bps,
            "expected_after_cost_return_bps",
        )
        for field in (
            "expected_drawdown_contribution_bps",
            "expected_tail_loss_bps",
            "liquidation_risk_probability",
            "expected_market_impact_bps",
            "expected_funding_cost_bps",
            "expected_turnover_bps",
            "expected_concentration_bps",
            "expected_information_gain",
        ):
            _require_nonnegative(getattr(self, field), field)
        if self.liquidation_risk_probability > 1.0:
            _raise("must_not_exceed_one", "liquidation_risk_probability")
        if not isinstance(self.hard_constraints_satisfied, bool):
            _raise("must_be_bool", "hard_constraints_satisfied")
        if self.hard_constraints_satisfied:
            _require_sha256(
                self.hard_validator_receipt_sha256,
                "hard_validator_receipt_sha256",
            )
        elif self.hard_validator_receipt_sha256 is not None:
            _raise(
                "hard_failure_forbids_validator_pass_receipt",
                "hard_validator_receipt_sha256",
            )
        if self.paper_only is not True:
            _raise("must_be_true", "paper_only")

    @property
    def is_flat(self) -> bool:
        return self.selected_action == "REMAIN_FLAT"


@dataclass(frozen=True, slots=True)
class ActionObjectiveScoreV2:
    action_id: str
    action_sha256: str
    selected_action: str
    policy_mode: str
    eligible: bool
    utility: float | None
    return_contribution: float | None
    total_penalty: float | None
    information_gain_contribution: float | None
    score_fingerprint: str
    authority_mode: str
    execution_authority: bool
    paper_only: bool

    def __post_init__(self) -> None:
        _require_identifier(self.action_id, "action_id")
        _require_sha256(self.action_sha256, "action_sha256")
        _require_identifier(self.selected_action, "selected_action")
        if self.policy_mode not in POLICY_MODES:
            _raise("invalid_policy_mode", "policy_mode")
        _require_sha256(self.score_fingerprint, "score_fingerprint")
        if not isinstance(self.eligible, bool):
            _raise("must_be_bool", "eligible")
        values = (
            self.utility,
            self.return_contribution,
            self.total_penalty,
            self.information_gain_contribution,
        )
        if self.eligible:
            if any(value is None for value in values):
                _raise("eligible_score_requires_values", "eligible")
            for index, value in enumerate(values):
                _require_finite(value, f"score_values[{index}]")
        elif any(value is not None for value in values):
            _raise("ineligible_score_requires_null_values", "eligible")
        if self.authority_mode != AUTHORITY_MODE:
            _raise("must_be_shadow_diagnostic_only", "authority_mode")
        if self.execution_authority is not False:
            _raise("must_be_false", "execution_authority")
        if self.paper_only is not True:
            _raise("must_be_true", "paper_only")
        if self.score_fingerprint != self.expected_score_fingerprint:
            _raise("must_match_deterministic_identity", "score_fingerprint")

    @property
    def expected_score_fingerprint(self) -> str:
        material = asdict(self)
        material.pop("score_fingerprint")
        return _canonical_hash(material)


@dataclass(frozen=True, slots=True)
class AdaptiveObjectiveEvaluationV2:
    evaluation_id: str
    scores: tuple[ActionObjectiveScoreV2, ...]
    champion_action_id: str | None
    exploration_action_id: str | None
    failure_signals: tuple[str, ...]
    mode_allocation: AdaptivePolicyModeAllocationV2
    objective_evidence_sha256: str
    objective_parameter_fingerprint: str
    checkpoint_generation: int
    authority_mode: str
    consumed_for_policy: bool
    execution_authority: bool
    paper_only: bool
    live_gate: str

    def __post_init__(self) -> None:
        _require_identifier(self.evaluation_id, "evaluation_id")
        if type(self.scores) is not tuple or not self.scores:
            _raise("must_be_non_empty_tuple", "scores")
        if any(not isinstance(item, ActionObjectiveScoreV2) for item in self.scores):
            _raise("invalid_score_type", "scores")
        score_ids = tuple(item.action_id for item in self.scores)
        if score_ids != tuple(sorted(set(score_ids))):
            _raise("score_ids_must_be_unique_and_sorted", "scores")
        if type(self.failure_signals) is not tuple:
            _raise("must_be_tuple", "failure_signals")
        if self.failure_signals != tuple(sorted(set(self.failure_signals))):
            _raise("must_be_unique_and_sorted", "failure_signals")
        eligible_ids = {item.action_id for item in self.scores if item.eligible}
        for field in ("champion_action_id", "exploration_action_id"):
            value = getattr(self, field)
            if value is not None and value not in eligible_ids:
                _raise("must_reference_eligible_score", field)
        if not isinstance(self.mode_allocation, AdaptivePolicyModeAllocationV2):
            _raise("invalid_mode_allocation", "mode_allocation")
        _require_sha256(self.objective_evidence_sha256, "objective_evidence_sha256")
        _require_sha256(
            self.objective_parameter_fingerprint,
            "objective_parameter_fingerprint",
        )
        if not isinstance(self.checkpoint_generation, int) or self.checkpoint_generation < 1:
            _raise("must_be_positive_int", "checkpoint_generation")
        if self.mode_allocation.checkpoint_generation != self.checkpoint_generation:
            _raise("mode_allocation_checkpoint_mismatch", "checkpoint_generation")
        by_mode = {
            mode: [item for item in self.scores if item.eligible and item.policy_mode == mode]
            for mode in POLICY_MODES
        }

        def best(mode: str) -> str | None:
            eligible = by_mode[mode]
            if not eligible:
                return None
            return max(eligible, key=lambda item: (item.utility, item.action_id)).action_id

        expected_champion = best(CHAMPION_EXPLOITATION)
        expected_exploration = best(BOUNDED_EXPLORATION)
        if self.champion_action_id != expected_champion:
            _raise("must_match_best_eligible_score", "champion_action_id")
        if self.exploration_action_id != expected_exploration:
            _raise("must_match_best_eligible_score", "exploration_action_id")
        eligible_scores = [item for item in self.scores if item.eligible]
        expected_failure_signals: set[str] = set()
        if not any(item.selected_action != "REMAIN_FLAT" for item in eligible_scores):
            expected_failure_signals.add("POLICY_FLAT_COLLAPSE_REQUIRES_LEARNING_ESCALATION")
        selected_exploration = next(
            (item for item in eligible_scores if item.action_id == expected_exploration),
            None,
        )
        if selected_exploration is None or selected_exploration.selected_action == "REMAIN_FLAT":
            expected_failure_signals.add("NO_EXECUTABLE_INFORMATION_SEEKING_ACTION")
        if expected_champion is None:
            expected_failure_signals.add("NO_HARD_VALID_CHAMPION_ACTION")
        if self.failure_signals != tuple(sorted(expected_failure_signals)):
            _raise("must_match_recomputed_failure_signals", "failure_signals")
        if self.authority_mode != AUTHORITY_MODE:
            _raise("must_be_shadow_diagnostic_only", "authority_mode")
        if self.consumed_for_policy is not False or self.execution_authority is not False:
            _raise("shadow_evaluation_forbids_authority", "authority")
        if self.paper_only is not True or self.live_gate != "blocked_human_only":
            _raise("paper_only_human_block_required", "safety")
        if self.evaluation_id != self.expected_evaluation_id:
            _raise("must_match_deterministic_identity", "evaluation_id")

    @property
    def expected_evaluation_id(self) -> str:
        material = asdict(self)
        material.pop("evaluation_id")
        return f"aoe2_{_canonical_hash(material)}"


def score_action(
    action: ActionObjectiveInputsV2,
    weights: LearnedObjectiveWeightsV2,
) -> ActionObjectiveScoreV2:
    if not isinstance(action, ActionObjectiveInputsV2):
        raise TypeError("action must be ActionObjectiveInputsV2")
    if not isinstance(weights, LearnedObjectiveWeightsV2):
        raise TypeError("weights must be LearnedObjectiveWeightsV2")
    if (
        action.checkpoint_generation != weights.evidence.checkpoint_generation
        or action.checkpoint_id != weights.evidence.checkpoint_id
        or action.checkpoint_sha256 != weights.evidence.checkpoint_sha256
    ):
        _raise("action_objective_checkpoint_mismatch", "action")
    if not action.hard_constraints_satisfied:
        values = {
            "action_id": action.action_id,
            "action_sha256": action.action_sha256,
            "selected_action": action.selected_action,
            "policy_mode": action.policy_mode,
            "eligible": False,
            "utility": None,
            "return_contribution": None,
            "total_penalty": None,
            "information_gain_contribution": None,
            "authority_mode": AUTHORITY_MODE,
            "execution_authority": False,
            "paper_only": True,
        }
    else:
        return_contribution = (
            weights.expected_after_cost_return * action.expected_after_cost_return_bps
        )
        total_penalty = (
            weights.drawdown_penalty * action.expected_drawdown_contribution_bps
            + weights.tail_loss_penalty * action.expected_tail_loss_bps
            + weights.liquidation_risk_penalty * action.liquidation_risk_probability
            + weights.market_impact_penalty * action.expected_market_impact_bps
            + weights.funding_cost_penalty * action.expected_funding_cost_bps
            + weights.turnover_penalty * action.expected_turnover_bps
            + weights.concentration_penalty * action.expected_concentration_bps
        )
        information_gain_contribution = (
            weights.information_gain_reward * action.expected_information_gain
        )
        values = {
            "action_id": action.action_id,
            "action_sha256": action.action_sha256,
            "selected_action": action.selected_action,
            "policy_mode": action.policy_mode,
            "eligible": True,
            "utility": return_contribution - total_penalty + information_gain_contribution,
            "return_contribution": return_contribution,
            "total_penalty": total_penalty,
            "information_gain_contribution": information_gain_contribution,
            "authority_mode": AUTHORITY_MODE,
            "execution_authority": False,
            "paper_only": True,
        }
    fingerprint = _canonical_hash(values)
    return ActionObjectiveScoreV2(score_fingerprint=fingerprint, **values)


def evaluate_shadow_objective(
    actions: tuple[ActionObjectiveInputsV2, ...],
    weights: LearnedObjectiveWeightsV2,
    mode_allocation: AdaptivePolicyModeAllocationV2,
) -> AdaptiveObjectiveEvaluationV2:
    if type(actions) is not tuple or not actions:
        _raise("must_be_non_empty_tuple", "actions")
    if any(not isinstance(action, ActionObjectiveInputsV2) for action in actions):
        _raise("invalid_action_type", "actions")
    action_ids = tuple(action.action_id for action in actions)
    if len(action_ids) != len(set(action_ids)):
        _raise("action_ids_must_be_unique", "actions")
    scores = tuple(
        sorted(
            (score_action(action, weights) for action in actions), key=lambda item: item.action_id
        )
    )
    by_id = {action.action_id: action for action in actions}

    def best(mode: str) -> str | None:
        eligible = [item for item in scores if item.eligible and item.policy_mode == mode]
        if not eligible:
            return None
        return max(eligible, key=lambda item: (item.utility, item.action_id)).action_id

    champion = best(CHAMPION_EXPLOITATION)
    exploration = best(BOUNDED_EXPLORATION)
    failure_signals: set[str] = set()
    eligible_actions = [by_id[item.action_id] for item in scores if item.eligible]
    if not any(not action.is_flat for action in eligible_actions):
        failure_signals.add("POLICY_FLAT_COLLAPSE_REQUIRES_LEARNING_ESCALATION")
    if exploration is None or by_id[exploration].is_flat:
        failure_signals.add("NO_EXECUTABLE_INFORMATION_SEEKING_ACTION")
    if champion is None:
        failure_signals.add("NO_HARD_VALID_CHAMPION_ACTION")
    values = {
        "scores": scores,
        "champion_action_id": champion,
        "exploration_action_id": exploration,
        "failure_signals": tuple(sorted(failure_signals)),
        "mode_allocation": mode_allocation,
        "objective_evidence_sha256": _canonical_hash(asdict(weights.evidence)),
        "objective_parameter_fingerprint": (weights.evidence.objective_parameter_fingerprint),
        "checkpoint_generation": weights.evidence.checkpoint_generation,
        "authority_mode": AUTHORITY_MODE,
        "consumed_for_policy": False,
        "execution_authority": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
    }
    hash_values = asdict_value(values)
    return AdaptiveObjectiveEvaluationV2(
        evaluation_id=f"aoe2_{_canonical_hash(hash_values)}",
        **values,
    )


def asdict_value(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return {key: asdict_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [asdict_value(item) for item in value]
    return value


__all__ = (
    "AUTHORITY_MODE",
    "BOUNDED_EXPLORATION",
    "CHAMPION_EXPLOITATION",
    "POLICY_MODES",
    "SCHEMA_VERSION",
    "ActionObjectiveInputsV2",
    "ActionObjectiveScoreV2",
    "AdaptiveObjectiveContractError",
    "AdaptiveObjectiveEvaluationV2",
    "AdaptivePolicyModeAllocationV2",
    "FittedObjectiveEvidenceV2",
    "LearnedObjectiveWeightsV2",
    "evaluate_shadow_objective",
    "score_action",
)
