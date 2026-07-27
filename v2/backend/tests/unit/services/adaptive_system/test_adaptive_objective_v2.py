from __future__ import annotations

import ast
import dataclasses
import hashlib
import importlib
import inspect
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.domain.adaptive_policy_action_v2 import (
    ACTION_DIRECTIONAL_TRADE,
    ACTION_REMAIN_FLAT,
)
from v2.backend.app.services.adaptive_system import adaptive_objective_v2 as objective_module
from v2.backend.app.services.adaptive_system.adaptive_objective_v2 import (
    ACTION_INPUT_SCHEMA_VERSION,
    ACTION_SCORE_SCHEMA_VERSION,
    BOUNDED_EXPLORATION,
    CANONICAL_HARD_VALIDATOR_FINGERPRINT_SHA256,
    CANONICAL_HARD_VALIDATOR_ID,
    CHAMPION_EXPLOITATION,
    FIT_EVIDENCE_SCHEMA_VERSION,
    HARD_VALIDATION_CHECK_SCHEMA_VERSION,
    HARD_VALIDATION_SCHEMA_VERSION,
    HARD_VALIDATION_SIGNATURE_ALGORITHM,
    HARD_VALIDATION_SIGNATURE_DOMAIN,
    MODE_ALLOCATION_SCHEMA_VERSION,
    SCHEMA_VERSION,
    UNIT_CONTRACT,
    WEIGHTS_SCHEMA_VERSION,
    ActionObjectiveInputsV2,
    ActionObjectiveScoreV2,
    AdaptiveObjectiveContractError,
    AdaptivePolicyModeAllocationV2,
    FittedObjectiveEvidenceV2,
    HardConstraintCheckEvidenceV2,
    HardConstraintValidationReceiptV2,
    LearnedObjectiveWeightsV2,
    evaluate_shadow_objective,
    score_action,
)

_TEST_VALIDATOR_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(
    hashlib.sha256(b"adaptive-objective-v2-test-hard-validator-key").digest()
)
_TEST_VALIDATOR_PUBLIC_KEY = _TEST_VALIDATOR_PRIVATE_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)


@pytest.fixture(autouse=True)
def _pin_test_hard_validator_public_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        objective_module,
        "CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX",
        _TEST_VALIDATOR_PUBLIC_KEY.hex(),
    )


def _sha(character: str) -> str:
    return character * 64


def _json_value(value: object) -> object:
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(_json_value(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _forged_score(
    score: ActionObjectiveScoreV2,
    **changes: object,
) -> ActionObjectiveScoreV2:
    values = {field.name: getattr(score, field.name) for field in dataclasses.fields(score)}
    values.update(changes)
    values.pop("score_fingerprint")
    return ActionObjectiveScoreV2(
        **values,
        score_fingerprint=_hash(values),
    )


def _signed_hard_validation_receipt(
    *,
    action_sha256: str,
    state_id: str,
    state_sha256: str,
    checkpoint_generation: int,
    checkpoint_id: str,
    checkpoint_sha256: str,
    decision_time_ms: int = 1_000,
    evaluated_at_ms: int = 980,
    validator_generated_at_ms: int = 985,
    record_available_at_ms: int = 990,
) -> HardConstraintValidationReceiptV2:
    evidence_inputs = tuple(sorted({action_sha256, state_sha256, checkpoint_sha256}))
    check_evidence = tuple(
        HardConstraintCheckEvidenceV2(
            schema_version=HARD_VALIDATION_CHECK_SCHEMA_VERSION,
            check_name=check_name,
            input_evidence_sha256s=evidence_inputs,
            check_result_sha256=_hash(
                {
                    "schema_version": HARD_VALIDATION_CHECK_SCHEMA_VERSION,
                    "check_name": check_name,
                    "input_evidence_sha256s": evidence_inputs,
                    "passed": True,
                }
            ),
            passed=True,
        )
        for check_name in sorted(objective_module.CANONICAL_HARD_VALIDATOR_REQUIRED_CHECKS)
    )
    unsigned = {
        "schema_version": HARD_VALIDATION_SCHEMA_VERSION,
        "validator_id": CANONICAL_HARD_VALIDATOR_ID,
        "validator_fingerprint_sha256": CANONICAL_HARD_VALIDATOR_FINGERPRINT_SHA256,
        "declared_public_key_sha256": hashlib.sha256(
            _TEST_VALIDATOR_PUBLIC_KEY
        ).hexdigest(),
        "signature_algorithm": HARD_VALIDATION_SIGNATURE_ALGORITHM,
        "check_evidence": check_evidence,
        "action_sha256": action_sha256,
        "state_id": state_id,
        "state_sha256": state_sha256,
        "checkpoint_generation": checkpoint_generation,
        "checkpoint_id": checkpoint_id,
        "checkpoint_sha256": checkpoint_sha256,
        "decision_time_ms": decision_time_ms,
        "evaluated_at_ms": evaluated_at_ms,
        "validator_generated_at_ms": validator_generated_at_ms,
        "record_available_at_ms": record_available_at_ms,
        "passed": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    encoded = json.dumps(
        _json_value(unsigned),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    values = {
        **unsigned,
        "signature_hex": _TEST_VALIDATOR_PRIVATE_KEY.sign(
            HARD_VALIDATION_SIGNATURE_DOMAIN + encoded
        ).hex(),
    }
    return HardConstraintValidationReceiptV2(
        receipt_sha256=_hash(values),
        **values,
    )


def _weights(**overrides: object) -> LearnedObjectiveWeightsV2:
    parameters: dict[str, object] = {
        "schema_version": WEIGHTS_SCHEMA_VERSION,
        "expected_after_cost_return": 1.0,
        "drawdown_penalty": 1.0,
        "tail_loss_penalty": 1.0,
        "liquidation_risk_penalty": 1.0,
        "market_impact_penalty": 1.0,
        "funding_cost_penalty": 1.0,
        "turnover_penalty": 1.0,
        "concentration_penalty": 1.0,
        "information_gain_reward": 1.0,
        "unit_contract": UNIT_CONTRACT,
    }
    parameters.update(overrides)
    evidence = FittedObjectiveEvidenceV2(
        schema_version=FIT_EVIDENCE_SCHEMA_VERSION,
        optimizer_id="walk_forward_objective_optimizer_v2",
        optimizer_family="purged_walk_forward_multiobjective",
        objective_parameter_fingerprint=_hash(parameters),
        fit_receipt_sha256=_sha("1"),
        training_row_digest=_sha("2"),
        training_population_sha256=_sha("3"),
        fit_window_start_ms=100,
        fit_window_end_ms=900,
        fit_record_available_at_ms=950,
        sample_count=200,
        checkpoint_generation=3,
        checkpoint_id="checkpoint_003",
        checkpoint_sha256=_sha("4"),
        fitted=True,
        holdout_used_for_fitting=False,
        paper_only=True,
    )
    return LearnedObjectiveWeightsV2(**parameters, evidence=evidence)  # type: ignore[arg-type]


def _allocation(exploitation: float = 0.7) -> AdaptivePolicyModeAllocationV2:
    values = {
        "schema_version": MODE_ALLOCATION_SCHEMA_VERSION,
        "champion_exploitation_probability": exploitation,
        "bounded_exploration_probability": 1.0 - exploitation,
        "fit_receipt_sha256": _sha("6"),
        "optimizer_id": "adaptive_mode_allocator_v2",
        "state_id": "state_001",
        "state_sha256": _sha("5"),
        "checkpoint_generation": 3,
        "checkpoint_id": "checkpoint_003",
        "checkpoint_sha256": _sha("4"),
        "fit_window_start_ms": 100,
        "fit_window_end_ms": 900,
        "fit_record_available_at_ms": 950,
        "fit_sample_count": 200,
        "fit_row_digest": _sha("8"),
        "fit_population_sha256": _sha("9"),
        "holdout_used_for_fitting": False,
        "paper_only": True,
        "fitted": True,
        "permanent_percentage": False,
    }
    return AdaptivePolicyModeAllocationV2(
        **values,
        allocation_parameter_fingerprint=_hash(values),
    )


def _action(
    action_id: str,
    mode: str,
    **overrides: object,
) -> ActionObjectiveInputsV2:
    values: dict[str, object] = {
        "schema_version": ACTION_INPUT_SCHEMA_VERSION,
        "action_id": action_id,
        "action_sha256": _hash({"action_id": action_id}),
        "state_id": "state_001",
        "state_sha256": _sha("5"),
        "decision_time_ms": 1_000,
        "checkpoint_generation": 3,
        "checkpoint_id": "checkpoint_003",
        "checkpoint_sha256": _sha("4"),
        "selected_action": ACTION_DIRECTIONAL_TRADE,
        "policy_mode": mode,
        "expected_after_cost_return_bps": 10.0,
        "expected_drawdown_contribution_bps": 1.0,
        "expected_tail_loss_bps": 1.0,
        "liquidation_risk_probability": 0.01,
        "expected_market_impact_bps": 1.0,
        "expected_funding_cost_bps": 1.0,
        "expected_turnover_bps": 1.0,
        "expected_concentration_bps": 1.0,
        "expected_information_gain": 1.0,
        "hard_constraints_satisfied": True,
        "unit_contract": UNIT_CONTRACT,
        "paper_only": True,
    }
    values.update(overrides)
    if "hard_validation_receipt" not in values:
        if values["hard_constraints_satisfied"] is True:
            values["hard_validation_receipt"] = _signed_hard_validation_receipt(
                action_sha256=values["action_sha256"],  # type: ignore[arg-type]
                state_id=values["state_id"],  # type: ignore[arg-type]
                state_sha256=values["state_sha256"],  # type: ignore[arg-type]
                checkpoint_generation=values["checkpoint_generation"],  # type: ignore[arg-type]
                checkpoint_id=values["checkpoint_id"],  # type: ignore[arg-type]
                checkpoint_sha256=values["checkpoint_sha256"],  # type: ignore[arg-type]
                decision_time_ms=values["decision_time_ms"],  # type: ignore[arg-type]
            )
        else:
            values["hard_validation_receipt"] = None
    return ActionObjectiveInputsV2.create(**values)


def test_exact_after_cost_portfolio_utility_formula() -> None:
    score = score_action(_action("action_1", CHAMPION_EXPLOITATION), _weights())
    assert score.return_contribution == 10.0
    assert score.total_penalty == 6.01
    assert score.information_gain_contribution == 1.0
    assert score.utility == pytest.approx(4.99)
    assert score.execution_authority is False


@pytest.mark.parametrize(
    "field",
    [
        "expected_after_cost_return",
        "drawdown_penalty",
        "tail_loss_penalty",
        "liquidation_risk_penalty",
        "market_impact_penalty",
        "funding_cost_penalty",
        "turnover_penalty",
        "concentration_penalty",
        "information_gain_reward",
    ],
)
def test_no_objective_weight_can_be_a_zero_static_placeholder(field: str) -> None:
    with pytest.raises(AdaptiveObjectiveContractError, match="fitted_weight"):
        _weights(**{field: 0.0})


def test_weight_fingerprint_and_fit_evidence_are_mandatory() -> None:
    weights = _weights()
    with pytest.raises(AdaptiveObjectiveContractError, match="parameter_fingerprint"):
        dataclasses.replace(
            weights,
            evidence=dataclasses.replace(
                weights.evidence,
                objective_parameter_fingerprint=_sha("0"),
            ),
        )
    with pytest.raises(AdaptiveObjectiveContractError, match="holdout"):
        dataclasses.replace(
            weights.evidence,
            holdout_used_for_fitting=True,
        )


def test_mode_allocation_is_fitted_concurrent_and_not_permanent() -> None:
    allocation = _allocation()
    assert allocation.champion_exploitation_probability == 0.7
    assert allocation.bounded_exploration_probability == pytest.approx(0.3)
    with pytest.raises(AdaptiveObjectiveContractError, match="inside_unit_interval"):
        _allocation(1.0)
    with pytest.raises(AdaptiveObjectiveContractError, match="must_be_false"):
        dataclasses.replace(allocation, permanent_percentage=True)


def test_flat_can_win_exploitation_without_becoming_terminal_learning_state() -> None:
    flat = _action(
        "flat",
        CHAMPION_EXPLOITATION,
        selected_action=ACTION_REMAIN_FLAT,
        expected_after_cost_return_bps=0.0,
        expected_drawdown_contribution_bps=0.0,
        expected_tail_loss_bps=0.0,
        liquidation_risk_probability=0.0,
        expected_market_impact_bps=0.0,
        expected_funding_cost_bps=0.0,
        expected_turnover_bps=0.0,
        expected_concentration_bps=0.0,
        expected_information_gain=0.0,
    )
    losing = _action("losing", CHAMPION_EXPLOITATION, expected_after_cost_return_bps=-5.0)
    exploration = _action("explore", BOUNDED_EXPLORATION, expected_information_gain=5.0)
    result = evaluate_shadow_objective((flat, losing, exploration), _weights(), _allocation())
    assert result.champion_action_id == "flat"
    assert result.exploration_action_id == "explore"
    assert "POLICY_FLAT_COLLAPSE_REQUIRES_LEARNING_ESCALATION" not in result.failure_signals
    assert result.consumed_for_policy is False


def test_information_gain_can_select_exploration_but_turnover_prevents_activity_reward() -> None:
    informative = _action(
        "informative",
        BOUNDED_EXPLORATION,
        expected_after_cost_return_bps=0.0,
        expected_information_gain=10.0,
        expected_turnover_bps=1.0,
    )
    churn = _action(
        "churn",
        BOUNDED_EXPLORATION,
        expected_after_cost_return_bps=0.0,
        expected_information_gain=10.0,
        expected_turnover_bps=100.0,
    )
    flat = _action(
        "flat",
        CHAMPION_EXPLOITATION,
        selected_action=ACTION_REMAIN_FLAT,
        expected_after_cost_return_bps=0.0,
        expected_drawdown_contribution_bps=0.0,
        expected_tail_loss_bps=0.0,
        liquidation_risk_probability=0.0,
        expected_market_impact_bps=0.0,
        expected_funding_cost_bps=0.0,
        expected_turnover_bps=0.0,
        expected_concentration_bps=0.0,
        expected_information_gain=0.0,
    )
    result = evaluate_shadow_objective((informative, churn, flat), _weights(), _allocation())
    assert result.exploration_action_id == "informative"


def test_missing_flat_baseline_cannot_force_negative_exploitation_trade() -> None:
    losing = _action(
        "losing",
        CHAMPION_EXPLOITATION,
        expected_after_cost_return_bps=-100.0,
    )
    explore = _action("explore", BOUNDED_EXPLORATION)
    result = evaluate_shadow_objective((losing, explore), _weights(), _allocation())
    assert result.champion_action_id is None
    assert "MISSING_HARD_VALID_FLAT_BASELINE" in result.failure_signals
    assert "NO_HARD_VALID_CHAMPION_ACTION" in result.failure_signals


def test_flat_action_is_never_misrepresented_as_information_seeking() -> None:
    champion_flat = _action(
        "champion_flat",
        CHAMPION_EXPLOITATION,
        selected_action=ACTION_REMAIN_FLAT,
    )
    exploration_flat = _action(
        "exploration_flat",
        BOUNDED_EXPLORATION,
        selected_action=ACTION_REMAIN_FLAT,
    )
    result = evaluate_shadow_objective(
        (champion_flat, exploration_flat),
        _weights(),
        _allocation(),
    )
    assert result.exploration_action_id is None
    assert "NO_EXECUTABLE_INFORMATION_SEEKING_ACTION" in result.failure_signals


def test_all_flat_or_hard_invalid_is_a_learning_failure_not_terminal_no_edge() -> None:
    flat = _action(
        "flat",
        CHAMPION_EXPLOITATION,
        selected_action=ACTION_REMAIN_FLAT,
        expected_after_cost_return_bps=0.0,
        expected_drawdown_contribution_bps=0.0,
        expected_tail_loss_bps=0.0,
        liquidation_risk_probability=0.0,
        expected_market_impact_bps=0.0,
        expected_funding_cost_bps=0.0,
        expected_turnover_bps=0.0,
        expected_concentration_bps=0.0,
        expected_information_gain=0.0,
    )
    invalid = _action(
        "invalid_explore",
        BOUNDED_EXPLORATION,
        hard_constraints_satisfied=False,
    )
    result = evaluate_shadow_objective((flat, invalid), _weights(), _allocation())
    assert "POLICY_FLAT_COLLAPSE_REQUIRES_LEARNING_ESCALATION" in result.failure_signals
    assert "NO_EXECUTABLE_INFORMATION_SEEKING_ACTION" in result.failure_signals
    assert all("NO_EDGE" not in signal for signal in result.failure_signals)
    invalid_score = next(item for item in result.scores if item.action_id == "invalid_explore")
    assert invalid_score.eligible is False
    assert invalid_score.utility is None


def test_hard_pass_requires_receipt_and_paper_only() -> None:
    with pytest.raises(AdaptiveObjectiveContractError, match="structured_hard_validation"):
        _action("bad", CHAMPION_EXPLOITATION, hard_validation_receipt=None)
    with pytest.raises(AdaptiveObjectiveContractError, match="paper_only"):
        _action("bad", CHAMPION_EXPLOITATION, paper_only=False)


def test_action_and_objective_checkpoint_must_match() -> None:
    action = _action("bad", CHAMPION_EXPLOITATION, checkpoint_generation=2)
    with pytest.raises(AdaptiveObjectiveContractError, match="checkpoint_mismatch"):
        score_action(action, _weights())


def test_objective_input_fingerprint_rejects_scored_value_mutation() -> None:
    action = _action("bound", CHAMPION_EXPLOITATION)
    with pytest.raises(AdaptiveObjectiveContractError, match="deterministic_identity"):
        dataclasses.replace(action, expected_after_cost_return_bps=9999.0)


def test_only_canonical_phase2_actions_are_accepted() -> None:
    with pytest.raises(AdaptiveObjectiveContractError, match="adaptive_policy_action"):
        _action("banana", BOUNDED_EXPLORATION, selected_action="BANANA")


def test_allocation_identity_binds_fit_receipt_optimizer_and_checkpoint() -> None:
    allocation = _allocation()
    for changes in (
        {"fit_receipt_sha256": _sha("f")},
        {"optimizer_id": "foreign_optimizer"},
        {"checkpoint_id": "foreign_checkpoint"},
    ):
        with pytest.raises(AdaptiveObjectiveContractError, match="parameter_fingerprint"):
            dataclasses.replace(allocation, **changes)


def test_foreign_state_allocation_is_rejected() -> None:
    actions = (
        _action("a", CHAMPION_EXPLOITATION),
        _action("b", BOUNDED_EXPLORATION),
    )
    allocation = _allocation()
    values = dataclasses.asdict(allocation)
    values["state_id"] = "foreign_state"
    values["state_sha256"] = _sha("f")
    values.pop("allocation_parameter_fingerprint")
    foreign = AdaptivePolicyModeAllocationV2(
        **values,
        allocation_parameter_fingerprint=_hash(values),
    )
    with pytest.raises(AdaptiveObjectiveContractError, match="lineage_mismatch"):
        evaluate_shadow_objective(actions, _weights(), foreign)


def test_future_fit_evidence_is_rejected_at_decision_time() -> None:
    action = _action("a", CHAMPION_EXPLOITATION)
    weights = _weights()
    future_evidence = dataclasses.replace(
        weights.evidence,
        fit_window_end_ms=1_100,
        fit_record_available_at_ms=1_200,
    )
    future_weights = dataclasses.replace(weights, evidence=future_evidence)
    with pytest.raises(AdaptiveObjectiveContractError, match="future_leakage"):
        score_action(action, future_weights)
    allocation_values = dataclasses.asdict(_allocation())
    allocation_values["fit_record_available_at_ms"] = 1_200
    allocation_values.pop("allocation_parameter_fingerprint")
    future_allocation = AdaptivePolicyModeAllocationV2(
        **allocation_values,
        allocation_parameter_fingerprint=_hash(allocation_values),
    )
    with pytest.raises(AdaptiveObjectiveContractError, match="future_leakage"):
        evaluate_shadow_objective(
            (action, _action("b", BOUNDED_EXPLORATION)),
            weights,
            future_allocation,
        )


def test_same_semantic_action_cannot_occupy_both_modes() -> None:
    first = _action("a", CHAMPION_EXPLOITATION)
    alias = _action("b", BOUNDED_EXPLORATION, action_sha256=first.action_sha256)
    with pytest.raises(AdaptiveObjectiveContractError, match="action_sha256s_must_be_unique"):
        evaluate_shadow_objective((first, alias), _weights(), _allocation())


def test_hard_validation_receipt_cannot_replay_across_actions() -> None:
    first = _action("a", CHAMPION_EXPLOITATION)
    with pytest.raises(AdaptiveObjectiveContractError, match="lineage_mismatch"):
        _action(
            "b",
            BOUNDED_EXPLORATION,
            hard_validation_receipt=first.hard_validation_receipt,
        )


def test_signed_hard_validation_receipt_cannot_replay_at_later_decision() -> None:
    first = _action("a", CHAMPION_EXPLOITATION)
    with pytest.raises(AdaptiveObjectiveContractError, match="lineage_mismatch"):
        _action(
            "a_later",
            CHAMPION_EXPLOITATION,
            action_sha256=first.action_sha256,
            decision_time_ms=1_000_000,
            hard_validation_receipt=first.hard_validation_receipt,
        )


def test_hard_validation_receipt_must_precede_decision_and_bind_its_identity() -> None:
    action = _action("a", CHAMPION_EXPLOITATION)
    assert action.hard_validation_receipt is not None
    with pytest.raises(AdaptiveObjectiveContractError, match="signature_verification"):
        dataclasses.replace(action.hard_validation_receipt, evaluated_at_ms=979)
    with pytest.raises(AdaptiveObjectiveContractError, match="clock_order_invalid"):
        _signed_hard_validation_receipt(
            action_sha256=action.action_sha256,
            state_id=action.state_id,
            state_sha256=action.state_sha256,
            checkpoint_generation=action.checkpoint_generation,
            checkpoint_id=action.checkpoint_id,
            checkpoint_sha256=action.checkpoint_sha256,
            decision_time_ms=action.decision_time_ms,
            record_available_at_ms=action.decision_time_ms + 1,
        )


def test_hard_validation_receipt_clock_order_is_explicit() -> None:
    action = _action("a", CHAMPION_EXPLOITATION)
    assert action.hard_validation_receipt is not None
    with pytest.raises(AdaptiveObjectiveContractError, match="clock_order_invalid"):
        _signed_hard_validation_receipt(
            action_sha256=action.action_sha256,
            state_id=action.state_id,
            state_sha256=action.state_sha256,
            checkpoint_generation=action.checkpoint_generation,
            checkpoint_id=action.checkpoint_id,
            checkpoint_sha256=action.checkpoint_sha256,
            decision_time_ms=action.decision_time_ms,
            evaluated_at_ms=980,
            validator_generated_at_ms=979,
        )


@pytest.mark.parametrize(
    "changes, expected_error",
    [
        ({"validator_id": "untrusted_self_issuer"}, "untrusted_validator_id"),
        ({"validator_fingerprint_sha256": _sha("0")}, "untrusted_validator_fingerprint"),
    ],
)
def test_self_asserted_hard_validator_is_rejected(
    changes: dict[str, object],
    expected_error: str,
) -> None:
    action = _action("a", CHAMPION_EXPLOITATION)
    assert action.hard_validation_receipt is not None
    values = {
        field.name: getattr(action.hard_validation_receipt, field.name)
        for field in dataclasses.fields(action.hard_validation_receipt)
    }
    values.pop("receipt_sha256")
    values.update(changes)
    with pytest.raises(AdaptiveObjectiveContractError, match=expected_error):
        HardConstraintValidationReceiptV2(
            receipt_sha256=_hash(values),
            **values,
        )


def test_canonical_label_cannot_self_mint_without_validator_private_key() -> None:
    action = _action("a", CHAMPION_EXPLOITATION)
    assert action.hard_validation_receipt is not None
    values = {
        field.name: getattr(action.hard_validation_receipt, field.name)
        for field in dataclasses.fields(action.hard_validation_receipt)
    }
    values.pop("receipt_sha256")
    values["signature_hex"] = "00" * 64
    with pytest.raises(AdaptiveObjectiveContractError, match="signature_verification"):
        HardConstraintValidationReceiptV2(
            receipt_sha256=_hash(values),
            **values,
        )


def test_signed_receipt_requires_complete_evidence_for_every_canonical_check() -> None:
    action = _action("a", CHAMPION_EXPLOITATION)
    assert action.hard_validation_receipt is not None
    values = {
        field.name: getattr(action.hard_validation_receipt, field.name)
        for field in dataclasses.fields(action.hard_validation_receipt)
    }
    values.pop("receipt_sha256")
    values["check_evidence"] = values["check_evidence"][:-1]
    with pytest.raises(AdaptiveObjectiveContractError, match="complete_canonical"):
        HardConstraintValidationReceiptV2(
            receipt_sha256=_hash(values),
            **values,
        )


def test_scores_bind_exact_objective_evidence_and_weights() -> None:
    action = _action("a", CHAMPION_EXPLOITATION)
    score = score_action(action, _weights())
    with pytest.raises(AdaptiveObjectiveContractError, match="objective_projection"):
        dataclasses.replace(score, objective_parameter_fingerprint=_sha("f"))
    second = score_action(action, _weights(expected_after_cost_return=2.0))
    assert score.score_fingerprint != second.score_fingerprint
    assert (
        score.objective_parameter_fingerprint
        != second.objective_parameter_fingerprint
    )


def test_float_subclasses_cannot_override_objective_arithmetic() -> None:
    class EvilFloat(float):
        def __mul__(self, other: object) -> float:
            del other
            return 1_000_000.0

    with pytest.raises(AdaptiveObjectiveContractError, match="finite_float"):
        _weights(expected_after_cost_return=EvilFloat(1.0))
    with pytest.raises(AdaptiveObjectiveContractError, match="finite_float"):
        _action(
            "evil",
            CHAMPION_EXPLOITATION,
            expected_after_cost_return_bps=EvilFloat(1.0),
        )


def test_public_score_construction_cannot_relabel_hard_invalid_action() -> None:
    invalid = _action(
        "hard_invalid",
        BOUNDED_EXPLORATION,
        hard_constraints_satisfied=False,
    )
    score = score_action(invalid, _weights())
    assert score.eligible is False
    with pytest.raises(AdaptiveObjectiveContractError, match="recomputed_objective"):
        _forged_score(
            score,
            eligible=True,
            utility=999.0,
            return_contribution=999.0,
            total_penalty=0.0,
            information_gain_contribution=0.0,
        )


def test_public_score_construction_cannot_forge_objective_arithmetic() -> None:
    score = score_action(_action("a", CHAMPION_EXPLOITATION), _weights())
    with pytest.raises(AdaptiveObjectiveContractError, match="recomputed_objective"):
        _forged_score(score, utility=1_000_000.0)


def test_zero_information_negative_utility_churn_is_not_exploration() -> None:
    flat = _action(
        "flat",
        CHAMPION_EXPLOITATION,
        selected_action=ACTION_REMAIN_FLAT,
        expected_after_cost_return_bps=0.0,
        expected_drawdown_contribution_bps=0.0,
        expected_tail_loss_bps=0.0,
        liquidation_risk_probability=0.0,
        expected_market_impact_bps=0.0,
        expected_funding_cost_bps=0.0,
        expected_turnover_bps=0.0,
        expected_concentration_bps=0.0,
        expected_information_gain=0.0,
    )
    churn = _action(
        "churn",
        BOUNDED_EXPLORATION,
        expected_after_cost_return_bps=-100.0,
        expected_turnover_bps=10_000.0,
        expected_information_gain=0.0,
    )
    result = evaluate_shadow_objective((flat, churn), _weights(), _allocation())
    assert result.exploration_action_id is None
    assert "NO_EXECUTABLE_INFORMATION_SEEKING_ACTION" in result.failure_signals


@pytest.mark.parametrize("invalid", [None, object(), "not-an-allocation"])
def test_evaluator_rejects_invalid_allocation_without_attribute_error(invalid: object) -> None:
    with pytest.raises(AdaptiveObjectiveContractError, match="invalid_mode_allocation"):
        evaluate_shadow_objective(
            (_action("a", CHAMPION_EXPLOITATION),),
            _weights(),
            invalid,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _action("bool", CHAMPION_EXPLOITATION, checkpoint_generation=True),
        lambda: dataclasses.replace(_allocation(), checkpoint_generation=True),
    ],
)
def test_boolean_checkpoint_generation_is_rejected(factory: object) -> None:
    with pytest.raises(AdaptiveObjectiveContractError, match="positive_int"):
        factory()  # type: ignore[operator]


def test_unit_contract_is_exact_and_identity_bound() -> None:
    with pytest.raises(AdaptiveObjectiveContractError, match="unit_contract"):
        _action("bad_units", CHAMPION_EXPLOITATION, unit_contract="MIXED_UNITS")
    weights = _weights()
    with pytest.raises(AdaptiveObjectiveContractError, match="unit_contract"):
        dataclasses.replace(
            weights,
            unit_contract="MIXED_UNITS",
            evidence=dataclasses.replace(
                weights.evidence,
                objective_parameter_fingerprint=_sha("0"),
            ),
        )


def test_every_persistable_record_is_schema_version_bound() -> None:
    action = _action("a", CHAMPION_EXPLOITATION)
    weights = _weights()
    allocation = _allocation()
    score = score_action(action, weights)
    result = evaluate_shadow_objective(
        (action, _action("b", BOUNDED_EXPLORATION)),
        weights,
        allocation,
    )
    records = (
        (action, ACTION_INPUT_SCHEMA_VERSION),
        (action.hard_validation_receipt, HARD_VALIDATION_SCHEMA_VERSION),
        (weights, WEIGHTS_SCHEMA_VERSION),
        (weights.evidence, FIT_EVIDENCE_SCHEMA_VERSION),
        (allocation, MODE_ALLOCATION_SCHEMA_VERSION),
        (score, ACTION_SCORE_SCHEMA_VERSION),
        (result, SCHEMA_VERSION),
    )
    for record, expected_schema_version in records:
        assert record is not None
        assert record.schema_version == expected_schema_version
        with pytest.raises(AdaptiveObjectiveContractError, match="schema_version"):
            dataclasses.replace(record, schema_version="wrong_schema")


def test_evaluation_is_deterministic_and_context_bound() -> None:
    actions = (
        _action("a", CHAMPION_EXPLOITATION),
        _action("b", BOUNDED_EXPLORATION),
    )
    first = evaluate_shadow_objective(actions, _weights(), _allocation())
    second = evaluate_shadow_objective(tuple(reversed(actions)), _weights(), _allocation())
    assert first == second
    changed = evaluate_shadow_objective(actions, _weights(), _allocation(0.6))
    assert first.evaluation_id != changed.evaluation_id
    with pytest.raises(AdaptiveObjectiveContractError, match="best_eligible"):
        dataclasses.replace(first, champion_action_id="b")
    with pytest.raises(AdaptiveObjectiveContractError, match="failure_signals"):
        dataclasses.replace(first, failure_signals=("FORGED",))


def test_module_has_no_io_or_runtime_dependency() -> None:
    module = importlib.import_module(
        "v2.backend.app.services.adaptive_system.adaptive_objective_v2"
    )
    tree = ast.parse(inspect.getsource(module))
    forbidden_calls = {"connect", "getenv", "open", "publish", "request", "send", "system"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_calls
