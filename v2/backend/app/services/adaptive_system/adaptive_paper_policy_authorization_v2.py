"""Bind one adaptive policy selection to hard-validated PAPER authority.

``AdaptivePolicyActionV2`` deliberately has no execution authority.  This
module is the narrow hand-off that consumes the selected objective input, its
signed canonical hard-validator receipt, and (for a new position) the exact
venue-feasibility attestation.  It never selects, resizes, rounds, or repairs an
action and it never grants live authority.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Mapping

from v2.backend.app.domain.adaptive_policy_action_v2 import (
    ACTION_DIRECTIONAL_TRADE,
    ACTION_REMAIN_FLAT,
    POLICY_MODE_BOOTSTRAP_INFORMATION_ACQUISITION,
    POLICY_MODE_BOUNDED_EXPLORATION,
    AdaptivePolicyActionV2,
)
from v2.backend.app.services.adaptive_system.adaptive_objective_v2 import (
    ActionObjectiveInputsV2,
    AdaptiveObjectiveEvaluationV2,
    HardConstraintValidationReceiptV2,
)
from v2.backend.app.services.adaptive_system.adaptive_policy_shadow_v2 import (
    AdaptivePolicyShadowCandidateV2,
)
from v2.backend.app.services.adaptive_system.selected_action_venue_feasibility_v2 import (
    DECISION_EXECUTABLE,
    SelectedActionVenueFeasibilityV2,
)

SCHEMA_VERSION = "adaptive_paper_policy_authorization_v2"
AUTHORITY_ID = "canonical_adaptive_paper_policy_authority_v2"
LIVE_GATE = "blocked_human_only"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AdaptivePaperPolicyAuthorizationError(ValueError):
    pass


def _fail(reason: str, field: str) -> None:
    raise AdaptivePaperPolicyAuthorizationError(f"{field}:{reason}")


def _json_value(value: object) -> object:
    if dataclasses.is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_value(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _identifier(value: object, field: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        _fail("identifier_required", field)


def _sha(value: object, field: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail("lowercase_sha256_required", field)


def _decimal(value: object, field: str, *, allow_zero: bool = True) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        _fail("finite_Decimal_required", field)
    if value < 0 or (not allow_zero and value == 0):
        _fail("nonnegative_required" if allow_zero else "positive_required", field)
    return value


@dataclass(frozen=True, slots=True)
class AdaptivePaperPolicyAuthorizationV2:
    authorization_id: str
    authority_id: str
    candidate_id: str
    source_intent_sha256: str
    adaptive_policy_action_id: str
    adaptive_policy_action_sha256: str
    adaptive_policy_action_fingerprint_sha256: str
    objective_evaluation_id: str
    objective_evaluation_sha256: str
    selected_objective_input_id: str
    selected_objective_input_fingerprint_sha256: str
    hard_validation_receipt_sha256: str
    venue_attestation_id: str | None
    venue_attestation_sha256: str | None
    state_id: str
    state_sha256: str
    operator_catastrophic_envelope_sha256: str
    checkpoint_generation: int
    checkpoint_id: str
    checkpoint_sha256: str
    policy_id: str
    policy_generation: int
    policy_mode: str
    selected_action: str
    primary_symbol: str
    primary_timeframe: str
    primary_side: str
    exact_entry_price: Decimal
    exact_stop_price: Decimal
    exact_target_notional_usd: Decimal
    exact_target_quantity: Decimal
    exact_leverage: Decimal
    exact_margin_allocation_usd: Decimal
    exact_bounded_loss_usd: Decimal
    exact_round_trip_cost_bps: Decimal
    expected_after_cost_return_bps: float
    expected_holding_horizon_seconds: int
    policy_decision_time_ms: int
    hard_validation_available_at_ms: int
    authorized_at_ms: int
    policy_trading_action_authority: bool
    paper_entry_authority: bool
    hard_validator_passed: bool
    exact_action_venue_executable: bool
    mandatory_stop_present: bool
    static_confidence_final_authority: bool
    static_loss_final_authority: bool
    static_microstructure_final_authority: bool
    static_exit_feasibility_final_authority: bool
    static_exploration_tier_final_authority: bool
    paper_only: bool
    live_gate: str
    routes_to_live: bool
    places_real_order: bool
    exchange_action_taken: bool
    live_eligible: bool
    live_submission_ready: bool
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            _fail("invalid_schema_version", "schema_version")
        for field in (
            "authorization_id",
            "authority_id",
            "candidate_id",
            "adaptive_policy_action_id",
            "objective_evaluation_id",
            "selected_objective_input_id",
            "state_id",
            "checkpoint_id",
            "policy_id",
            "policy_mode",
            "selected_action",
            "primary_symbol",
            "primary_timeframe",
            "primary_side",
        ):
            _identifier(getattr(self, field), field)
        if self.authority_id != AUTHORITY_ID:
            _fail("untrusted_authority", "authority_id")
        for field in (
            "source_intent_sha256",
            "adaptive_policy_action_sha256",
            "adaptive_policy_action_fingerprint_sha256",
            "objective_evaluation_sha256",
            "selected_objective_input_fingerprint_sha256",
            "hard_validation_receipt_sha256",
            "state_sha256",
            "operator_catastrophic_envelope_sha256",
            "checkpoint_sha256",
        ):
            _sha(getattr(self, field), field)
        if (self.venue_attestation_id is None) != (
            self.venue_attestation_sha256 is None
        ):
            _fail("id_and_sha_must_have_same_presence", "venue_attestation")
        if self.venue_attestation_id is not None:
            _identifier(self.venue_attestation_id, "venue_attestation_id")
            _sha(self.venue_attestation_sha256, "venue_attestation_sha256")
        for field in ("checkpoint_generation", "policy_generation"):
            value = getattr(self, field)
            if type(value) is not int or value < 1:
                _fail("positive_int_required", field)
        for field in (
            "expected_holding_horizon_seconds",
            "policy_decision_time_ms",
            "hard_validation_available_at_ms",
            "authorized_at_ms",
        ):
            value = getattr(self, field)
            if type(value) is not int or value < 0:
                _fail("nonnegative_int_required", field)
        if not (
            self.hard_validation_available_at_ms
            <= self.policy_decision_time_ms
            <= self.authorized_at_ms
        ):
            _fail("point_in_time_order_invalid", "authorized_at_ms")
        for field in (
            "exact_entry_price",
            "exact_stop_price",
            "exact_target_notional_usd",
            "exact_target_quantity",
            "exact_leverage",
            "exact_margin_allocation_usd",
            "exact_bounded_loss_usd",
            "exact_round_trip_cost_bps",
        ):
            _decimal(getattr(self, field), field)
        if type(self.expected_after_cost_return_bps) not in {int, float}:
            _fail("finite_number_required", "expected_after_cost_return_bps")
        try:
            expected_return = Decimal(str(self.expected_after_cost_return_bps))
        except Exception:
            expected_return = Decimal("NaN")
        if not expected_return.is_finite():
            _fail("finite_number_required", "expected_after_cost_return_bps")
        for field in (
            "policy_trading_action_authority",
            "paper_entry_authority",
            "hard_validator_passed",
            "exact_action_venue_executable",
            "mandatory_stop_present",
            "static_confidence_final_authority",
            "static_loss_final_authority",
            "static_microstructure_final_authority",
            "static_exit_feasibility_final_authority",
            "static_exploration_tier_final_authority",
            "paper_only",
            "routes_to_live",
            "places_real_order",
            "exchange_action_taken",
            "live_eligible",
            "live_submission_ready",
        ):
            if type(getattr(self, field)) is not bool:
                _fail("bool_required", field)
        if self.policy_trading_action_authority is not True:
            _fail("must_be_true", "policy_trading_action_authority")
        if self.hard_validator_passed is not True:
            _fail("must_be_true", "hard_validator_passed")
        for field in (
            "static_confidence_final_authority",
            "static_loss_final_authority",
            "static_microstructure_final_authority",
            "static_exit_feasibility_final_authority",
            "static_exploration_tier_final_authority",
            "routes_to_live",
            "places_real_order",
            "exchange_action_taken",
            "live_eligible",
            "live_submission_ready",
        ):
            if getattr(self, field) is not False:
                _fail("must_be_false", field)
        if self.paper_only is not True or self.live_gate != LIVE_GATE:
            _fail("paper_only_human_block_required", "safety")
        if self.primary_symbol != self.primary_symbol.upper():
            _fail("uppercase_required", "primary_symbol")
        directional = self.selected_action == ACTION_DIRECTIONAL_TRADE
        if directional:
            if self.primary_side not in {"long", "short"}:
                _fail("long_or_short_required", "primary_side")
            for field in (
                "exact_entry_price",
                "exact_stop_price",
                "exact_target_notional_usd",
                "exact_target_quantity",
                "exact_leverage",
                "exact_margin_allocation_usd",
                "exact_bounded_loss_usd",
            ):
                _decimal(getattr(self, field), field, allow_zero=False)
            if self.paper_entry_authority is not True:
                _fail("must_be_true_for_directional_action", "paper_entry_authority")
            if self.exact_action_venue_executable is not True:
                _fail("must_be_true_for_directional_action", "exact_action_venue_executable")
            if self.mandatory_stop_present is not True:
                _fail("must_be_true_for_directional_action", "mandatory_stop_present")
            if self.venue_attestation_id is None:
                _fail("required_for_directional_action", "venue_attestation_id")
            if self.expected_holding_horizon_seconds < 1:
                _fail("positive_required_for_directional_action", "expected_holding_horizon_seconds")
        elif self.selected_action == ACTION_REMAIN_FLAT:
            if self.primary_side != "flat":
                _fail("flat_required", "primary_side")
            if self.paper_entry_authority is not False:
                _fail("must_be_false_for_flat", "paper_entry_authority")
            if self.exact_action_venue_executable is not False:
                _fail("must_be_false_for_flat", "exact_action_venue_executable")
            if self.mandatory_stop_present is not False:
                _fail("must_be_false_for_flat", "mandatory_stop_present")
            if self.venue_attestation_id is not None:
                _fail("forbidden_for_flat", "venue_attestation_id")
            if any(
                getattr(self, field) != Decimal("0")
                for field in (
                    "exact_entry_price",
                    "exact_stop_price",
                    "exact_target_notional_usd",
                    "exact_target_quantity",
                    "exact_leverage",
                    "exact_margin_allocation_usd",
                    "exact_bounded_loss_usd",
                    "exact_round_trip_cost_bps",
                )
            ):
                _fail("exact_zero_required_for_flat", "exact_action")
            if self.expected_holding_horizon_seconds != 0:
                _fail("zero_required_for_flat", "expected_holding_horizon_seconds")
        else:
            _fail("unsupported_initial_entry_action", "selected_action")
        if self.authorization_id != self.expected_authorization_id:
            _fail("deterministic_identity_mismatch", "authorization_id")

    @property
    def expected_authorization_id(self) -> str:
        material = asdict(self)
        material.pop("authorization_id")
        return f"appa2_{_canonical_sha256(material)}"

    @property
    def content_sha256(self) -> str:
        return _canonical_sha256(asdict(self))

    def to_payload(self) -> dict[str, Any]:
        return _json_value(asdict(self))  # type: ignore[return-value]


def _selected_input(
    result: AdaptivePolicyShadowCandidateV2,
    action: AdaptivePolicyActionV2,
    evaluation: AdaptiveObjectiveEvaluationV2,
) -> ActionObjectiveInputsV2:
    if action.policy_mode == POLICY_MODE_BOOTSTRAP_INFORMATION_ACQUISITION:
        # A bootstrap information-acquisition action binds to the exact
        # hard-valid venue-minimum exploration input by identity.  It can
        # never ride the champion/exploration slots: its monetary utility may
        # be nonpositive, so it is only legitimate when neither slot holds a
        # positive-utility action.  Every downstream gate (signed hard
        # validator receipt, exact venue attestation, mandatory stop) applies
        # unchanged.
        if evaluation.exploration_action_id is not None:
            _fail(
                "bootstrap_requires_no_positive_utility_exploration",
                "objective_evaluation",
            )
        champion_matches = tuple(
            item
            for item in result.objective_inputs
            if item.action_id == evaluation.champion_action_id
        )
        if (
            len(champion_matches) != 1
            or champion_matches[0].selected_action != ACTION_REMAIN_FLAT
        ):
            _fail(
                "bootstrap_requires_flat_champion_baseline",
                "objective_evaluation",
            )
        if action.selected_action != ACTION_DIRECTIONAL_TRADE:
            _fail("bootstrap_requires_directional_trade", "selected_adaptive_action")
        bootstrap_side = action.primary_side.lower()
        side_suffixes = (
            f":{POLICY_MODE_BOUNDED_EXPLORATION}:{bootstrap_side}",
            f":{bootstrap_side}:venue_minimum",
        )
        matches = tuple(
            item
            for item in result.objective_inputs
            if item.policy_mode == POLICY_MODE_BOUNDED_EXPLORATION
            and item.selected_action == ACTION_DIRECTIONAL_TRADE
            and item.action_id.endswith(side_suffixes)
            and item.hard_constraints_satisfied is True
        )
        if len(matches) != 1:
            _fail("selected_objective_input_not_unique", "objective_inputs")
        selected = matches[0]
        if selected.expected_information_gain <= 0.0:
            _fail(
                "bootstrap_requires_positive_information_gain",
                "selected_objective_input",
            )
        if selected.selected_action != action.selected_action:
            _fail("selected_action_mismatch", "selected_objective_input")
        return selected
    selected_id = (
        evaluation.exploration_action_id
        if action.policy_mode == POLICY_MODE_BOUNDED_EXPLORATION
        else evaluation.champion_action_id
    )
    if selected_id is None:
        _fail("selected_objective_input_missing", "objective_evaluation")
    matches = tuple(item for item in result.objective_inputs if item.action_id == selected_id)
    if len(matches) != 1:
        _fail("selected_objective_input_not_unique", "objective_inputs")
    selected = matches[0]
    if selected.selected_action != action.selected_action:
        _fail("selected_action_mismatch", "selected_objective_input")
    if selected.policy_mode != action.policy_mode:
        _fail("policy_mode_mismatch", "selected_objective_input")
    return selected


def authorize_adaptive_paper_policy_action(
    result: AdaptivePolicyShadowCandidateV2,
    *,
    authorized_at_ms: int,
) -> AdaptivePaperPolicyAuthorizationV2:
    """Authorize only the exact hard-valid adaptive PAPER policy selection."""

    if type(result) is not AdaptivePolicyShadowCandidateV2:
        raise TypeError("result must be AdaptivePolicyShadowCandidateV2")
    if result.parity_status != "PASS" or result.parity_disagreement_count != 0:
        _fail("independent_reference_parity_required", "result")
    if (
        result.paper_only is not True
        or result.live_gate != LIVE_GATE
        or any((result.routes_to_live, result.places_real_order, result.exchange_action_taken))
    ):
        _fail("paper_only_human_block_required", "result")
    action = result.selected_adaptive_action
    evaluation = result.objective_evaluation
    if type(action) is not AdaptivePolicyActionV2:
        _fail("AdaptivePolicyActionV2_required", "selected_adaptive_action")
    if type(evaluation) is not AdaptiveObjectiveEvaluationV2:
        _fail("AdaptiveObjectiveEvaluationV2_required", "objective_evaluation")
    if action.selection_receipt_sha256 != _canonical_sha256(asdict(evaluation)):
        _fail("selection_receipt_mismatch", "selected_adaptive_action")
    selected = _selected_input(result, action, evaluation)
    receipt = selected.hard_validation_receipt
    if (
        selected.hard_constraints_satisfied is not True
        or type(receipt) is not HardConstraintValidationReceiptV2
        or receipt.passed is not True
    ):
        _fail("signed_hard_validator_pass_required", "selected_objective_input")
    if (
        receipt.action_sha256 != selected.action_sha256
        or receipt.state_id != action.state_id
        or receipt.state_sha256 != action.state_sha256
        or receipt.checkpoint_generation != action.checkpoint_generation
        or receipt.checkpoint_id != action.checkpoint_id
        or receipt.checkpoint_sha256 != action.checkpoint_sha256
        or receipt.decision_time_ms != action.decision_time_ms
    ):
        _fail("hard_validator_lineage_mismatch", "hard_validation_receipt")
    if authorized_at_ms < action.decision_time_ms:
        _fail("must_not_precede_policy_decision", "authorized_at_ms")

    directional = action.selected_action == ACTION_DIRECTIONAL_TRADE
    selected_venues = tuple(
        item
        for item in result.venue_attestations
        if item.request.policy_action_sha256 == selected.action_sha256
    )
    venue: SelectedActionVenueFeasibilityV2 | None = None
    if directional:
        if len(selected_venues) != 1:
            _fail("exact_selected_venue_attestation_required", "venue_attestations")
        venue = selected_venues[0]
        request = venue.request
        if venue.decision != DECISION_EXECUTABLE or venue.failed_checks:
            _fail("exact_selected_action_not_executable", "venue_attestation")
        exact_action = {
            "candidate_id": request.candidate_id == result.candidate_id,
            "side": request.side == action.primary_side.upper(),
            "entry_price": request.selected_entry_price
            == Decimal(str(action.entry_policy.reference_price)),
            "stop_price": request.selected_stop_price == Decimal(str(action.stop_price)),
            "notional": request.selected_notional_usd
            == Decimal(str(action.target_notional_usd)),
            "leverage": request.selected_leverage == Decimal(str(action.leverage)),
            "margin": request.selected_margin_usd
            == Decimal(str(action.margin_allocation_usd)),
        }
        if not all(exact_action.values()):
            failed = ",".join(sorted(name for name, passed in exact_action.items() if not passed))
            _fail(f"selected_action_changed:{failed}", "venue_attestation")
        if (
            action.entry_policy.active is not True
            or action.exit_policy.active is not True
            or action.stop_price is None
            or action.stop_distance <= 0.0
            or action.expected_holding_horizon < 1
        ):
            _fail("mandatory_entry_stop_exit_contract_required", "selected_adaptive_action")
        entry_price = request.selected_entry_price
        stop_price = request.selected_stop_price
        target_notional = venue.exact_selected_notional_usd
        target_quantity = venue.exact_selected_quantity
        leverage = request.selected_leverage
        margin = venue.exact_selected_margin_usd
        bounded_loss = venue.exact_selected_bounded_loss_usd
        round_trip_cost = request.selected_round_trip_cost_bps
    elif action.selected_action == ACTION_REMAIN_FLAT:
        if selected_venues:
            _fail("flat_action_forbids_venue_execution", "venue_attestations")
        entry_price = stop_price = target_notional = target_quantity = Decimal("0")
        leverage = margin = bounded_loss = round_trip_cost = Decimal("0")
    else:
        _fail("unsupported_initial_entry_action", "selected_adaptive_action")

    values: dict[str, Any] = {
        "authority_id": AUTHORITY_ID,
        "candidate_id": result.candidate_id,
        "source_intent_sha256": result.source_intent_sha256,
        "adaptive_policy_action_id": action.decision_id,
        "adaptive_policy_action_sha256": action.content_sha256,
        "adaptive_policy_action_fingerprint_sha256": action.action_fingerprint_sha256,
        "objective_evaluation_id": evaluation.evaluation_id,
        "objective_evaluation_sha256": _canonical_sha256(asdict(evaluation)),
        "selected_objective_input_id": selected.action_id,
        "selected_objective_input_fingerprint_sha256": (
            selected.objective_input_fingerprint_sha256
        ),
        "hard_validation_receipt_sha256": receipt.receipt_sha256,
        "venue_attestation_id": venue.attestation_id if venue is not None else None,
        "venue_attestation_sha256": (
            _canonical_sha256(asdict(venue)) if venue is not None else None
        ),
        "state_id": action.state_id,
        "state_sha256": action.state_sha256,
        "operator_catastrophic_envelope_sha256": (
            action.operator_catastrophic_envelope_sha256
        ),
        "checkpoint_generation": action.checkpoint_generation,
        "checkpoint_id": action.checkpoint_id,
        "checkpoint_sha256": action.checkpoint_sha256,
        "policy_id": action.policy_id,
        "policy_generation": action.policy_generation,
        "policy_mode": action.policy_mode,
        "selected_action": action.selected_action,
        "primary_symbol": action.primary_symbol,
        "primary_timeframe": action.primary_timeframe,
        "primary_side": action.primary_side,
        "exact_entry_price": entry_price,
        "exact_stop_price": stop_price,
        "exact_target_notional_usd": target_notional,
        "exact_target_quantity": target_quantity,
        "exact_leverage": leverage,
        "exact_margin_allocation_usd": margin,
        "exact_bounded_loss_usd": bounded_loss,
        "exact_round_trip_cost_bps": round_trip_cost,
        "expected_after_cost_return_bps": action.expected_after_cost_return,
        "expected_holding_horizon_seconds": action.expected_holding_horizon,
        "policy_decision_time_ms": action.decision_time_ms,
        "hard_validation_available_at_ms": receipt.record_available_at_ms,
        "authorized_at_ms": authorized_at_ms,
        "policy_trading_action_authority": True,
        "paper_entry_authority": directional,
        "hard_validator_passed": True,
        "exact_action_venue_executable": directional,
        "mandatory_stop_present": directional,
        "static_confidence_final_authority": False,
        "static_loss_final_authority": False,
        "static_microstructure_final_authority": False,
        "static_exit_feasibility_final_authority": False,
        "static_exploration_tier_final_authority": False,
        "paper_only": True,
        "live_gate": LIVE_GATE,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "live_eligible": False,
        "live_submission_ready": False,
        "schema_version": SCHEMA_VERSION,
    }
    authorization_id = f"appa2_{_canonical_sha256(values)}"
    return AdaptivePaperPolicyAuthorizationV2(
        authorization_id=authorization_id,
        **values,
    )


__all__ = (
    "AUTHORITY_ID",
    "SCHEMA_VERSION",
    "AdaptivePaperPolicyAuthorizationError",
    "AdaptivePaperPolicyAuthorizationV2",
    "authorize_adaptive_paper_policy_action",
)
