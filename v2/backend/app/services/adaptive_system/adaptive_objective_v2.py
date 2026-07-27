"""Pure shadow evaluator for an evidence-fitted adaptive portfolio objective."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from v2.backend.app.domain.adaptive_policy_action_v2 import (
    ACTION_CLOSE_EXISTING_EXPOSURE,
    ACTION_DIRECTIONAL_TRADE,
    ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE,
    ACTION_REDUCE_EXISTING_EXPOSURE,
    ACTION_REMAIN_FLAT,
    POLICY_MODE_BOUNDED_EXPLORATION,
    POLICY_MODE_CHAMPION_EXPLOITATION,
)

SCHEMA_VERSION = "adaptive_portfolio_objective_v2"
FIT_EVIDENCE_SCHEMA_VERSION = "fitted_objective_evidence_v2"
WEIGHTS_SCHEMA_VERSION = "learned_objective_weights_v2"
MODE_ALLOCATION_SCHEMA_VERSION = "adaptive_policy_mode_allocation_v2"
HARD_VALIDATION_SCHEMA_VERSION = "hard_constraint_validation_receipt_v2"
HARD_VALIDATION_CHECK_SCHEMA_VERSION = "hard_constraint_check_evidence_v2"
ACTION_INPUT_SCHEMA_VERSION = "action_objective_inputs_v2"
ACTION_SCORE_SCHEMA_VERSION = "action_objective_score_v2"
AUTHORITY_MODE = "SHADOW_DIAGNOSTIC_ONLY"

CHAMPION_EXPLOITATION = POLICY_MODE_CHAMPION_EXPLOITATION
BOUNDED_EXPLORATION = POLICY_MODE_BOUNDED_EXPLORATION
POLICY_MODES = (CHAMPION_EXPLOITATION, BOUNDED_EXPLORATION)
ACTION_SET = frozenset(
    {
        ACTION_DIRECTIONAL_TRADE,
        ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE,
        ACTION_REDUCE_EXISTING_EXPOSURE,
        ACTION_CLOSE_EXISTING_EXPOSURE,
        ACTION_REMAIN_FLAT,
    }
)
UNIT_CONTRACT = (
    "INPUTS_RETURN_DRAWDOWN_TAIL_IMPACT_FUNDING_TURNOVER_CONCENTRATION_BPS;"
    "LIQUIDATION_PROBABILITY_0_1;INFORMATION_GAIN_NATS;"
    "COEFFICIENTS_LEARNED_UTILITY_PER_DECLARED_INPUT_UNIT;OUTPUT_LEARNED_UTILITY"
)
CANONICAL_HARD_VALIDATOR_ID = "canonical_adaptive_hard_constraint_validator_v2"
CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX = (
    "a39845e2ed7a9e3e526dcc88e45e18ee823ef34018da876952aba9609ea48903"
)
HARD_VALIDATION_SIGNATURE_ALGORITHM = "Ed25519"
HARD_VALIDATION_SIGNATURE_DOMAIN = (
    b"v2/adaptive-system/hard-constraint-validation-receipt/v2\0"
)
CANONICAL_HARD_VALIDATOR_REQUIRED_CHECKS = (
    "accounting_and_reservation_conservation",
    "authorization_and_paper_only",
    "catastrophic_loss_envelope",
    "data_integrity_and_point_in_time",
    "identity_and_lineage",
    "position_transition_validity",
    "venue_and_physical_feasibility",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ED25519_SIGNATURE_RE = re.compile(r"^[0-9a-f]{128}$")


class AdaptiveObjectiveContractError(ValueError):
    pass


def _raise(reason: str, field: str) -> None:
    raise AdaptiveObjectiveContractError(f"{field}:{reason}")


def _require_identifier(value: object, field: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        _raise("must_be_non_empty_without_whitespace", field)


def _require_sha256(value: object, field: str) -> None:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _raise("must_be_lowercase_sha256", field)


def _require_finite(value: object, field: str) -> None:
    if type(value) is not float or not math.isfinite(value):
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


CANONICAL_HARD_VALIDATOR_FINGERPRINT_SHA256 = _canonical_hash(
    {
        "schema_version": HARD_VALIDATION_SCHEMA_VERSION,
        "validator_id": CANONICAL_HARD_VALIDATOR_ID,
        "required_checks": CANONICAL_HARD_VALIDATOR_REQUIRED_CHECKS,
    }
)


@dataclass(frozen=True, slots=True)
class FittedObjectiveEvidenceV2:
    schema_version: str
    optimizer_id: str
    optimizer_family: str
    objective_parameter_fingerprint: str
    fit_receipt_sha256: str
    training_row_digest: str
    training_population_sha256: str
    fit_window_start_ms: int
    fit_window_end_ms: int
    fit_record_available_at_ms: int
    sample_count: int
    checkpoint_generation: int
    checkpoint_id: str
    checkpoint_sha256: str
    fitted: bool
    holdout_used_for_fitting: bool
    paper_only: bool

    def __post_init__(self) -> None:
        if self.schema_version != FIT_EVIDENCE_SCHEMA_VERSION:
            _raise("invalid_schema_version", "schema_version")
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
            "fit_record_available_at_ms",
            "sample_count",
            "checkpoint_generation",
        ):
            value = getattr(self, field)
            if type(value) is not int or value < 1:
                _raise("must_be_positive_int", field)
        if self.fit_window_start_ms > self.fit_window_end_ms:
            _raise("window_order_invalid", "fit_window_end_ms")
        if self.fit_window_end_ms > self.fit_record_available_at_ms:
            _raise("fit_available_before_window_end", "fit_record_available_at_ms")
        if self.fitted is not True:
            _raise("must_be_true", "fitted")
        if self.holdout_used_for_fitting is not False:
            _raise("must_be_false", "holdout_used_for_fitting")
        if self.paper_only is not True:
            _raise("must_be_true", "paper_only")


@dataclass(frozen=True, slots=True)
class LearnedObjectiveWeightsV2:
    schema_version: str
    expected_after_cost_return: float
    drawdown_penalty: float
    tail_loss_penalty: float
    liquidation_risk_penalty: float
    market_impact_penalty: float
    funding_cost_penalty: float
    turnover_penalty: float
    concentration_penalty: float
    information_gain_reward: float
    unit_contract: str
    evidence: FittedObjectiveEvidenceV2

    def __post_init__(self) -> None:
        if self.schema_version != WEIGHTS_SCHEMA_VERSION:
            _raise("invalid_schema_version", "schema_version")
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
        if type(self.evidence) is not FittedObjectiveEvidenceV2:
            _raise("structured_fit_evidence_required", "evidence")
        if self.unit_contract != UNIT_CONTRACT:
            _raise("invalid_unit_contract", "unit_contract")
        parameter_values = {
            field: getattr(self, field)
            for field in (
                "schema_version",
                "expected_after_cost_return",
                "drawdown_penalty",
                "tail_loss_penalty",
                "liquidation_risk_penalty",
                "market_impact_penalty",
                "funding_cost_penalty",
                "turnover_penalty",
                "concentration_penalty",
                "information_gain_reward",
                "unit_contract",
            )
        }
        if _canonical_hash(parameter_values) != self.evidence.objective_parameter_fingerprint:
            _raise("must_match_fitted_parameter_fingerprint", "evidence")


@dataclass(frozen=True, slots=True)
class AdaptivePolicyModeAllocationV2:
    schema_version: str
    champion_exploitation_probability: float
    bounded_exploration_probability: float
    allocation_parameter_fingerprint: str
    fit_receipt_sha256: str
    optimizer_id: str
    state_id: str
    state_sha256: str
    checkpoint_generation: int
    checkpoint_id: str
    checkpoint_sha256: str
    fit_window_start_ms: int
    fit_window_end_ms: int
    fit_record_available_at_ms: int
    fit_sample_count: int
    fit_row_digest: str
    fit_population_sha256: str
    holdout_used_for_fitting: bool
    paper_only: bool
    fitted: bool
    permanent_percentage: bool

    def __post_init__(self) -> None:
        if self.schema_version != MODE_ALLOCATION_SCHEMA_VERSION:
            _raise("invalid_schema_version", "schema_version")
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
            "checkpoint_sha256",
            "fit_row_digest",
            "fit_population_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        for field in ("optimizer_id", "state_id", "checkpoint_id"):
            _require_identifier(getattr(self, field), field)
        if (
            type(self.checkpoint_generation) is not int
            or self.checkpoint_generation < 1
        ):
            _raise("must_be_positive_int", "checkpoint_generation")
        for field in (
            "fit_window_start_ms",
            "fit_window_end_ms",
            "fit_record_available_at_ms",
            "fit_sample_count",
        ):
            value = getattr(self, field)
            if type(value) is not int or value < 1:
                _raise("must_be_positive_int", field)
        if self.fit_window_start_ms > self.fit_window_end_ms:
            _raise("window_order_invalid", "fit_window_end_ms")
        if self.fit_window_end_ms > self.fit_record_available_at_ms:
            _raise("fit_available_before_window_end", "fit_record_available_at_ms")
        if self.fitted is not True:
            _raise("must_be_true", "fitted")
        if self.permanent_percentage is not False:
            _raise("must_be_false", "permanent_percentage")
        if self.holdout_used_for_fitting is not False:
            _raise("must_be_false", "holdout_used_for_fitting")
        if self.paper_only is not True:
            _raise("must_be_true", "paper_only")
        parameters = asdict(self)
        parameters.pop("allocation_parameter_fingerprint")
        if _canonical_hash(parameters) != self.allocation_parameter_fingerprint:
            _raise("must_match_fitted_parameter_fingerprint", "mode_allocation")


@dataclass(frozen=True, slots=True)
class HardConstraintCheckEvidenceV2:
    schema_version: str
    check_name: str
    input_evidence_sha256s: tuple[str, ...]
    check_result_sha256: str
    passed: bool

    def __post_init__(self) -> None:
        if self.schema_version != HARD_VALIDATION_CHECK_SCHEMA_VERSION:
            _raise("invalid_schema_version", "schema_version")
        if self.check_name not in CANONICAL_HARD_VALIDATOR_REQUIRED_CHECKS:
            _raise("unknown_hard_constraint_check", "check_name")
        if type(self.input_evidence_sha256s) is not tuple or not self.input_evidence_sha256s:
            _raise("must_be_non_empty_tuple", "input_evidence_sha256s")
        if self.input_evidence_sha256s != tuple(
            sorted(set(self.input_evidence_sha256s))
        ):
            _raise("must_be_unique_and_sorted", "input_evidence_sha256s")
        for index, value in enumerate(self.input_evidence_sha256s):
            _require_sha256(value, f"input_evidence_sha256s[{index}]")
        _require_sha256(self.check_result_sha256, "check_result_sha256")
        if self.passed is not True:
            _raise("must_be_true", "passed")
        expected_result_sha256 = _canonical_hash(
            {
                "schema_version": self.schema_version,
                "check_name": self.check_name,
                "input_evidence_sha256s": self.input_evidence_sha256s,
                "passed": self.passed,
            }
        )
        if self.check_result_sha256 != expected_result_sha256:
            _raise("must_match_deterministic_identity", "check_result_sha256")


@dataclass(frozen=True, slots=True)
class HardConstraintValidationReceiptV2:
    schema_version: str
    receipt_sha256: str
    validator_id: str
    validator_fingerprint_sha256: str
    declared_public_key_sha256: str
    signature_algorithm: str
    signature_hex: str
    check_evidence: tuple[HardConstraintCheckEvidenceV2, ...]
    action_sha256: str
    state_id: str
    state_sha256: str
    checkpoint_generation: int
    checkpoint_id: str
    checkpoint_sha256: str
    decision_time_ms: int
    evaluated_at_ms: int
    validator_generated_at_ms: int
    record_available_at_ms: int
    passed: bool
    paper_only: bool
    routes_to_live: bool
    places_real_order: bool

    def __post_init__(self) -> None:
        if self.schema_version != HARD_VALIDATION_SCHEMA_VERSION:
            _raise("invalid_schema_version", "schema_version")
        for field in (
            "receipt_sha256",
            "validator_fingerprint_sha256",
            "declared_public_key_sha256",
            "action_sha256",
            "state_sha256",
            "checkpoint_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        for field in ("validator_id", "state_id", "checkpoint_id"):
            _require_identifier(getattr(self, field), field)
        if self.validator_id != CANONICAL_HARD_VALIDATOR_ID:
            _raise("untrusted_validator_id", "validator_id")
        if (
            self.validator_fingerprint_sha256
            != CANONICAL_HARD_VALIDATOR_FINGERPRINT_SHA256
        ):
            _raise("untrusted_validator_fingerprint", "validator_fingerprint_sha256")
        if self.signature_algorithm != HARD_VALIDATION_SIGNATURE_ALGORITHM:
            _raise("invalid_signature_algorithm", "signature_algorithm")
        if (
            type(self.signature_hex) is not str
            or _ED25519_SIGNATURE_RE.fullmatch(self.signature_hex) is None
        ):
            _raise("invalid_ed25519_signature", "signature_hex")
        if type(self.check_evidence) is not tuple:
            _raise("must_be_tuple", "check_evidence")
        if any(
            type(item) is not HardConstraintCheckEvidenceV2
            for item in self.check_evidence
        ):
            _raise("invalid_check_evidence_type", "check_evidence")
        check_names = tuple(item.check_name for item in self.check_evidence)
        if check_names != tuple(sorted(CANONICAL_HARD_VALIDATOR_REQUIRED_CHECKS)):
            _raise("complete_canonical_check_evidence_required", "check_evidence")
        for field in (
            "checkpoint_generation",
            "decision_time_ms",
            "evaluated_at_ms",
            "validator_generated_at_ms",
            "record_available_at_ms",
        ):
            value = getattr(self, field)
            if type(value) is not int or value < 1:
                _raise("must_be_positive_int", field)
        if not (
            self.evaluated_at_ms
            <= self.validator_generated_at_ms
            <= self.record_available_at_ms
            <= self.decision_time_ms
        ):
            _raise("clock_order_invalid", "hard_validation_receipt")
        if self.passed is not True or self.paper_only is not True:
            _raise("must_be_true", "hard_validation")
        if self.routes_to_live is not False or self.places_real_order is not False:
            _raise("must_be_false", "hard_validation_authority")
        try:
            public_key_bytes = bytes.fromhex(CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX)
        except ValueError:
            _raise("invalid_trust_anchor", "canonical_public_key")
        if len(public_key_bytes) != 32:
            _raise("invalid_trust_anchor", "canonical_public_key")
        if hashlib.sha256(public_key_bytes).hexdigest() != self.declared_public_key_sha256:
            _raise("untrusted_public_key", "declared_public_key_sha256")
        try:
            Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
                bytes.fromhex(self.signature_hex),
                self.signature_payload,
            )
        except (InvalidSignature, ValueError):
            _raise("signature_verification_failed", "signature_hex")
        if self.receipt_sha256 != self.expected_receipt_sha256:
            _raise("must_match_deterministic_identity", "receipt_sha256")

    @property
    def expected_receipt_sha256(self) -> str:
        material = asdict(self)
        material.pop("receipt_sha256")
        return _canonical_hash(material)

    @property
    def signature_payload(self) -> bytes:
        material = asdict(self)
        material.pop("receipt_sha256")
        material.pop("signature_hex")
        encoded = json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return HARD_VALIDATION_SIGNATURE_DOMAIN + encoded


@dataclass(frozen=True, slots=True)
class ActionObjectiveInputsV2:
    schema_version: str
    objective_input_fingerprint_sha256: str
    action_id: str
    action_sha256: str
    state_id: str
    state_sha256: str
    decision_time_ms: int
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
    hard_validation_receipt: HardConstraintValidationReceiptV2 | None
    unit_contract: str
    paper_only: bool

    def __post_init__(self) -> None:
        if self.schema_version != ACTION_INPUT_SCHEMA_VERSION:
            _raise("invalid_schema_version", "schema_version")
        _require_identifier(self.action_id, "action_id")
        for field in (
            "objective_input_fingerprint_sha256",
            "action_sha256",
            "state_sha256",
            "checkpoint_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        for field in ("state_id", "checkpoint_id"):
            _require_identifier(getattr(self, field), field)
        for field in ("checkpoint_generation", "decision_time_ms"):
            value = getattr(self, field)
            if type(value) is not int or value < 1:
                _raise("must_be_positive_int", field)
        if self.selected_action not in ACTION_SET:
            _raise("invalid_adaptive_policy_action", "selected_action")
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
        if type(self.hard_constraints_satisfied) is not bool:
            _raise("must_be_bool", "hard_constraints_satisfied")
        if self.hard_constraints_satisfied:
            if type(self.hard_validation_receipt) is not HardConstraintValidationReceiptV2:
                _raise("structured_hard_validation_required", "hard_validation_receipt")
            receipt = self.hard_validation_receipt
            if (
                receipt.action_sha256 != self.action_sha256
                or receipt.state_id != self.state_id
                or receipt.state_sha256 != self.state_sha256
                or receipt.checkpoint_generation != self.checkpoint_generation
                or receipt.checkpoint_id != self.checkpoint_id
                or receipt.checkpoint_sha256 != self.checkpoint_sha256
                or receipt.decision_time_ms != self.decision_time_ms
            ):
                _raise("hard_validation_lineage_mismatch", "hard_validation_receipt")
            if receipt.record_available_at_ms > self.decision_time_ms:
                _raise("hard_validation_after_decision", "hard_validation_receipt")
        elif self.hard_validation_receipt is not None:
            _raise(
                "hard_failure_forbids_validator_pass_receipt",
                "hard_validation_receipt",
            )
        if self.unit_contract != UNIT_CONTRACT:
            _raise("invalid_unit_contract", "unit_contract")
        if self.paper_only is not True:
            _raise("must_be_true", "paper_only")
        if self.objective_input_fingerprint_sha256 != self.expected_input_fingerprint:
            _raise("must_match_deterministic_identity", "objective_input_fingerprint_sha256")

    @property
    def expected_input_fingerprint(self) -> str:
        material = asdict(self)
        material.pop("objective_input_fingerprint_sha256")
        return _canonical_hash(material)

    @classmethod
    def create(cls, **values: object) -> ActionObjectiveInputsV2:
        if "objective_input_fingerprint_sha256" in values:
            _raise("must_be_derived", "objective_input_fingerprint_sha256")
        material = dict(values)
        fingerprint = _canonical_hash(asdict_value(material))
        return cls(objective_input_fingerprint_sha256=fingerprint, **material)  # type: ignore[arg-type]

    @property
    def is_flat(self) -> bool:
        return self.selected_action == ACTION_REMAIN_FLAT


def _derive_score_values(
    action: ActionObjectiveInputsV2,
    weights: LearnedObjectiveWeightsV2,
) -> dict[str, bool | float | None]:
    if type(action) is not ActionObjectiveInputsV2:
        raise TypeError("action must be ActionObjectiveInputsV2")
    if type(weights) is not LearnedObjectiveWeightsV2:
        raise TypeError("weights must be LearnedObjectiveWeightsV2")
    if (
        action.checkpoint_generation != weights.evidence.checkpoint_generation
        or action.checkpoint_id != weights.evidence.checkpoint_id
        or action.checkpoint_sha256 != weights.evidence.checkpoint_sha256
    ):
        _raise("action_objective_checkpoint_mismatch", "action")
    if weights.evidence.fit_record_available_at_ms > action.decision_time_ms:
        _raise("objective_fit_future_leakage", "action")
    if not action.hard_constraints_satisfied:
        return {
            "eligible": False,
            "utility": None,
            "return_contribution": None,
            "total_penalty": None,
            "information_gain_contribution": None,
        }
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
    return {
        "eligible": True,
        "utility": return_contribution - total_penalty + information_gain_contribution,
        "return_contribution": return_contribution,
        "total_penalty": total_penalty,
        "information_gain_contribution": information_gain_contribution,
    }


@dataclass(frozen=True, slots=True)
class ActionObjectiveScoreV2:
    schema_version: str
    action_inputs: ActionObjectiveInputsV2
    objective_weights: LearnedObjectiveWeightsV2
    action_id: str
    action_sha256: str
    objective_input_fingerprint_sha256: str
    state_id: str
    state_sha256: str
    decision_time_ms: int
    checkpoint_generation: int
    checkpoint_id: str
    checkpoint_sha256: str
    objective_evidence_sha256: str
    objective_parameter_fingerprint: str
    selected_action: str
    policy_mode: str
    eligible: bool
    utility: float | None
    return_contribution: float | None
    total_penalty: float | None
    information_gain_contribution: float | None
    score_fingerprint: str
    unit_contract: str
    authority_mode: str
    execution_authority: bool
    paper_only: bool

    def __post_init__(self) -> None:
        if self.schema_version != ACTION_SCORE_SCHEMA_VERSION:
            _raise("invalid_schema_version", "schema_version")
        if type(self.action_inputs) is not ActionObjectiveInputsV2:
            _raise("structured_action_inputs_required", "action_inputs")
        if type(self.objective_weights) is not LearnedObjectiveWeightsV2:
            _raise("structured_objective_weights_required", "objective_weights")
        for field in ("action_id", "state_id", "checkpoint_id"):
            _require_identifier(getattr(self, field), field)
        for field in (
            "action_sha256",
            "objective_input_fingerprint_sha256",
            "state_sha256",
            "checkpoint_sha256",
            "objective_evidence_sha256",
            "objective_parameter_fingerprint",
        ):
            _require_sha256(getattr(self, field), field)
        for field in ("decision_time_ms", "checkpoint_generation"):
            value = getattr(self, field)
            if type(value) is not int or value < 1:
                _raise("must_be_positive_int", field)
        if self.selected_action not in ACTION_SET:
            _raise("invalid_adaptive_policy_action", "selected_action")
        if self.policy_mode not in POLICY_MODES:
            _raise("invalid_policy_mode", "policy_mode")
        _require_sha256(self.score_fingerprint, "score_fingerprint")
        if type(self.eligible) is not bool:
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
        if self.unit_contract != UNIT_CONTRACT:
            _raise("invalid_unit_contract", "unit_contract")
        action_projection = {
            "action_id": self.action_id,
            "action_sha256": self.action_sha256,
            "objective_input_fingerprint_sha256": self.objective_input_fingerprint_sha256,
            "state_id": self.state_id,
            "state_sha256": self.state_sha256,
            "decision_time_ms": self.decision_time_ms,
            "checkpoint_generation": self.checkpoint_generation,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_sha256": self.checkpoint_sha256,
            "selected_action": self.selected_action,
            "policy_mode": self.policy_mode,
        }
        expected_action_projection = {
            field: getattr(self.action_inputs, field) for field in action_projection
        }
        if action_projection != expected_action_projection:
            _raise("score_action_projection_mismatch", "action_inputs")
        expected_evidence_sha256 = _canonical_hash(
            asdict(self.objective_weights.evidence)
        )
        if (
            self.objective_evidence_sha256 != expected_evidence_sha256
            or self.objective_parameter_fingerprint
            != self.objective_weights.evidence.objective_parameter_fingerprint
        ):
            _raise("score_objective_projection_mismatch", "objective_weights")
        expected_values = _derive_score_values(
            self.action_inputs,
            self.objective_weights,
        )
        actual_values = {
            "eligible": self.eligible,
            "utility": self.utility,
            "return_contribution": self.return_contribution,
            "total_penalty": self.total_penalty,
            "information_gain_contribution": self.information_gain_contribution,
        }
        if actual_values != expected_values:
            _raise("must_match_recomputed_objective", "score_values")
        if self.score_fingerprint != self.expected_score_fingerprint:
            _raise("must_match_deterministic_identity", "score_fingerprint")

    @property
    def expected_score_fingerprint(self) -> str:
        material = asdict(self)
        material.pop("score_fingerprint")
        return _canonical_hash(material)


@dataclass(frozen=True, slots=True)
class AdaptiveObjectiveEvaluationV2:
    schema_version: str
    evaluation_id: str
    state_id: str
    state_sha256: str
    decision_time_ms: int
    scores: tuple[ActionObjectiveScoreV2, ...]
    champion_action_id: str | None
    exploration_action_id: str | None
    failure_signals: tuple[str, ...]
    mode_allocation: AdaptivePolicyModeAllocationV2
    objective_evidence_sha256: str
    objective_parameter_fingerprint: str
    checkpoint_generation: int
    checkpoint_id: str
    checkpoint_sha256: str
    unit_contract: str
    authority_mode: str
    consumed_for_policy: bool
    execution_authority: bool
    paper_only: bool
    live_gate: str

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            _raise("invalid_schema_version", "schema_version")
        _require_identifier(self.evaluation_id, "evaluation_id")
        for field in ("state_id", "checkpoint_id"):
            _require_identifier(getattr(self, field), field)
        for field in ("state_sha256", "checkpoint_sha256"):
            _require_sha256(getattr(self, field), field)
        for field in ("decision_time_ms", "checkpoint_generation"):
            value = getattr(self, field)
            if type(value) is not int or value < 1:
                _raise("must_be_positive_int", field)
        if type(self.scores) is not tuple or not self.scores:
            _raise("must_be_non_empty_tuple", "scores")
        if any(type(item) is not ActionObjectiveScoreV2 for item in self.scores):
            _raise("invalid_score_type", "scores")
        score_ids = tuple(item.action_id for item in self.scores)
        if score_ids != tuple(sorted(set(score_ids))):
            _raise("score_ids_must_be_unique_and_sorted", "scores")
        score_action_shas = tuple(item.action_sha256 for item in self.scores)
        if len(score_action_shas) != len(set(score_action_shas)):
            _raise("action_sha256s_must_be_unique", "scores")
        score_input_fingerprints = tuple(
            item.objective_input_fingerprint_sha256 for item in self.scores
        )
        if len(score_input_fingerprints) != len(set(score_input_fingerprints)):
            _raise("objective_input_fingerprints_must_be_unique", "scores")
        for item in self.scores:
            if (
                item.state_id != self.state_id
                or item.state_sha256 != self.state_sha256
                or item.decision_time_ms != self.decision_time_ms
                or item.checkpoint_generation != self.checkpoint_generation
                or item.checkpoint_id != self.checkpoint_id
                or item.checkpoint_sha256 != self.checkpoint_sha256
                or item.objective_evidence_sha256 != self.objective_evidence_sha256
                or item.objective_parameter_fingerprint
                != self.objective_parameter_fingerprint
            ):
                _raise("score_evaluation_lineage_mismatch", "scores")
        if type(self.failure_signals) is not tuple:
            _raise("must_be_tuple", "failure_signals")
        if self.failure_signals != tuple(sorted(set(self.failure_signals))):
            _raise("must_be_unique_and_sorted", "failure_signals")
        eligible_ids = {item.action_id for item in self.scores if item.eligible}
        for field in ("champion_action_id", "exploration_action_id"):
            value = getattr(self, field)
            if value is not None and value not in eligible_ids:
                _raise("must_reference_eligible_score", field)
        if type(self.mode_allocation) is not AdaptivePolicyModeAllocationV2:
            _raise("invalid_mode_allocation", "mode_allocation")
        _require_sha256(self.objective_evidence_sha256, "objective_evidence_sha256")
        _require_sha256(
            self.objective_parameter_fingerprint,
            "objective_parameter_fingerprint",
        )
        if (
            self.mode_allocation.state_id != self.state_id
            or self.mode_allocation.state_sha256 != self.state_sha256
            or self.mode_allocation.checkpoint_generation != self.checkpoint_generation
            or self.mode_allocation.checkpoint_id != self.checkpoint_id
            or self.mode_allocation.checkpoint_sha256 != self.checkpoint_sha256
        ):
            _raise("mode_allocation_lineage_mismatch", "mode_allocation")
        if self.mode_allocation.fit_record_available_at_ms > self.decision_time_ms:
            _raise("mode_allocation_future_leakage", "mode_allocation")
        if self.unit_contract != UNIT_CONTRACT:
            _raise("invalid_unit_contract", "unit_contract")
        by_mode = {
            mode: [item for item in self.scores if item.eligible and item.policy_mode == mode]
            for mode in POLICY_MODES
        }

        hard_valid_flat_baseline = any(
            item.selected_action == ACTION_REMAIN_FLAT
            and item.policy_mode == CHAMPION_EXPLOITATION
            for item in self.scores
            if item.eligible
        )

        def best(mode: str) -> str | None:
            eligible = [
                item
                for item in by_mode[mode]
                if mode != BOUNDED_EXPLORATION
                or (
                    item.selected_action != ACTION_REMAIN_FLAT
                    and item.utility is not None
                    and item.utility > 0.0
                    and item.information_gain_contribution is not None
                    and item.information_gain_contribution > 0.0
                )
            ]
            if mode == CHAMPION_EXPLOITATION and not hard_valid_flat_baseline:
                return None
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
        if not hard_valid_flat_baseline:
            expected_failure_signals.add("MISSING_HARD_VALID_FLAT_BASELINE")
        if not any(item.selected_action != ACTION_REMAIN_FLAT for item in eligible_scores):
            expected_failure_signals.add("POLICY_FLAT_COLLAPSE_REQUIRES_LEARNING_ESCALATION")
        selected_exploration = next(
            (item for item in eligible_scores if item.action_id == expected_exploration),
            None,
        )
        if selected_exploration is None:
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
    common_values = {
        "schema_version": ACTION_SCORE_SCHEMA_VERSION,
        "action_inputs": action,
        "objective_weights": weights,
        "action_id": action.action_id,
        "action_sha256": action.action_sha256,
        "objective_input_fingerprint_sha256": action.objective_input_fingerprint_sha256,
        "state_id": action.state_id,
        "state_sha256": action.state_sha256,
        "decision_time_ms": action.decision_time_ms,
        "checkpoint_generation": action.checkpoint_generation,
        "checkpoint_id": action.checkpoint_id,
        "checkpoint_sha256": action.checkpoint_sha256,
        "objective_evidence_sha256": _canonical_hash(asdict(weights.evidence)),
        "objective_parameter_fingerprint": (
            weights.evidence.objective_parameter_fingerprint
        ),
        "selected_action": action.selected_action,
        "policy_mode": action.policy_mode,
        "unit_contract": UNIT_CONTRACT,
        "authority_mode": AUTHORITY_MODE,
        "execution_authority": False,
        "paper_only": True,
    }
    values = {**common_values, **_derive_score_values(action, weights)}
    fingerprint = _canonical_hash(asdict_value(values))
    return ActionObjectiveScoreV2(score_fingerprint=fingerprint, **values)


def evaluate_shadow_objective(
    actions: tuple[ActionObjectiveInputsV2, ...],
    weights: LearnedObjectiveWeightsV2,
    mode_allocation: AdaptivePolicyModeAllocationV2,
) -> AdaptiveObjectiveEvaluationV2:
    if type(actions) is not tuple or not actions:
        _raise("must_be_non_empty_tuple", "actions")
    if any(type(action) is not ActionObjectiveInputsV2 for action in actions):
        _raise("invalid_action_type", "actions")
    if type(weights) is not LearnedObjectiveWeightsV2:
        _raise("invalid_objective_weights", "weights")
    if type(mode_allocation) is not AdaptivePolicyModeAllocationV2:
        _raise("invalid_mode_allocation", "mode_allocation")
    action_ids = tuple(action.action_id for action in actions)
    if len(action_ids) != len(set(action_ids)):
        _raise("action_ids_must_be_unique", "actions")
    action_shas = tuple(action.action_sha256 for action in actions)
    if len(action_shas) != len(set(action_shas)):
        _raise("action_sha256s_must_be_unique", "actions")
    lineage = {
        (
            action.state_id,
            action.state_sha256,
            action.decision_time_ms,
            action.checkpoint_generation,
            action.checkpoint_id,
            action.checkpoint_sha256,
        )
        for action in actions
    }
    if len(lineage) != 1:
        _raise("actions_must_share_state_decision_checkpoint", "actions")
    (
        state_id,
        state_sha256,
        decision_time_ms,
        checkpoint_generation,
        checkpoint_id,
        checkpoint_sha256,
    ) = next(iter(lineage))
    if (
        mode_allocation.state_id != state_id
        or mode_allocation.state_sha256 != state_sha256
        or mode_allocation.checkpoint_generation != checkpoint_generation
        or mode_allocation.checkpoint_id != checkpoint_id
        or mode_allocation.checkpoint_sha256 != checkpoint_sha256
    ):
        _raise("mode_allocation_lineage_mismatch", "mode_allocation")
    if (
        mode_allocation.fit_record_available_at_ms > decision_time_ms
        or weights.evidence.fit_record_available_at_ms > decision_time_ms
    ):
        _raise("fit_future_leakage", "decision_time_ms")
    scores = tuple(
        sorted(
            (score_action(action, weights) for action in actions), key=lambda item: item.action_id
        )
    )
    by_id = {action.action_id: action for action in actions}

    hard_valid_flat_baseline = any(
        item.eligible
        and item.policy_mode == CHAMPION_EXPLOITATION
        and item.selected_action == ACTION_REMAIN_FLAT
        for item in scores
    )

    def best(mode: str) -> str | None:
        eligible = [
            item
            for item in scores
            if item.eligible
            and item.policy_mode == mode
            and (
                mode != BOUNDED_EXPLORATION
                or (
                    item.selected_action != ACTION_REMAIN_FLAT
                    and item.utility is not None
                    and item.utility > 0.0
                    and item.information_gain_contribution is not None
                    and item.information_gain_contribution > 0.0
                )
            )
        ]
        if mode == CHAMPION_EXPLOITATION and not hard_valid_flat_baseline:
            return None
        if not eligible:
            return None
        return max(eligible, key=lambda item: (item.utility, item.action_id)).action_id

    champion = best(CHAMPION_EXPLOITATION)
    exploration = best(BOUNDED_EXPLORATION)
    failure_signals: set[str] = set()
    if not hard_valid_flat_baseline:
        failure_signals.add("MISSING_HARD_VALID_FLAT_BASELINE")
    eligible_actions = [by_id[item.action_id] for item in scores if item.eligible]
    if not any(not action.is_flat for action in eligible_actions):
        failure_signals.add("POLICY_FLAT_COLLAPSE_REQUIRES_LEARNING_ESCALATION")
    if exploration is None:
        failure_signals.add("NO_EXECUTABLE_INFORMATION_SEEKING_ACTION")
    if champion is None:
        failure_signals.add("NO_HARD_VALID_CHAMPION_ACTION")
    values = {
        "schema_version": SCHEMA_VERSION,
        "state_id": state_id,
        "state_sha256": state_sha256,
        "decision_time_ms": decision_time_ms,
        "scores": scores,
        "champion_action_id": champion,
        "exploration_action_id": exploration,
        "failure_signals": tuple(sorted(failure_signals)),
        "mode_allocation": mode_allocation,
        "objective_evidence_sha256": _canonical_hash(asdict(weights.evidence)),
        "objective_parameter_fingerprint": (weights.evidence.objective_parameter_fingerprint),
        "checkpoint_generation": checkpoint_generation,
        "checkpoint_id": checkpoint_id,
        "checkpoint_sha256": checkpoint_sha256,
        "unit_contract": UNIT_CONTRACT,
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
    "ACTION_SET",
    "ACTION_INPUT_SCHEMA_VERSION",
    "ACTION_SCORE_SCHEMA_VERSION",
    "AUTHORITY_MODE",
    "BOUNDED_EXPLORATION",
    "CHAMPION_EXPLOITATION",
    "CANONICAL_HARD_VALIDATOR_FINGERPRINT_SHA256",
    "CANONICAL_HARD_VALIDATOR_ID",
    "CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX",
    "CANONICAL_HARD_VALIDATOR_REQUIRED_CHECKS",
    "FIT_EVIDENCE_SCHEMA_VERSION",
    "HARD_VALIDATION_CHECK_SCHEMA_VERSION",
    "HARD_VALIDATION_SCHEMA_VERSION",
    "HARD_VALIDATION_SIGNATURE_ALGORITHM",
    "HARD_VALIDATION_SIGNATURE_DOMAIN",
    "MODE_ALLOCATION_SCHEMA_VERSION",
    "POLICY_MODES",
    "SCHEMA_VERSION",
    "ActionObjectiveInputsV2",
    "ActionObjectiveScoreV2",
    "AdaptiveObjectiveContractError",
    "AdaptiveObjectiveEvaluationV2",
    "AdaptivePolicyModeAllocationV2",
    "FittedObjectiveEvidenceV2",
    "HardConstraintCheckEvidenceV2",
    "HardConstraintValidationReceiptV2",
    "LearnedObjectiveWeightsV2",
    "UNIT_CONTRACT",
    "WEIGHTS_SCHEMA_VERSION",
    "evaluate_shadow_objective",
    "score_action",
)
