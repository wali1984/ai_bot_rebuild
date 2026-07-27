from __future__ import annotations

import ast
import dataclasses
import hashlib
import importlib
import inspect
import json

import pytest

from v2.backend.app.services.adaptive_system.adaptive_objective_v2 import (
    BOUNDED_EXPLORATION,
    CHAMPION_EXPLOITATION,
    ActionObjectiveInputsV2,
    AdaptiveObjectiveContractError,
    AdaptivePolicyModeAllocationV2,
    FittedObjectiveEvidenceV2,
    LearnedObjectiveWeightsV2,
    evaluate_shadow_objective,
    score_action,
)


def _sha(character: str) -> str:
    return character * 64


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _weights(**overrides: object) -> LearnedObjectiveWeightsV2:
    parameters: dict[str, object] = {
        "expected_after_cost_return": 1.0,
        "drawdown_penalty": 1.0,
        "tail_loss_penalty": 1.0,
        "liquidation_risk_penalty": 1.0,
        "market_impact_penalty": 1.0,
        "funding_cost_penalty": 1.0,
        "turnover_penalty": 1.0,
        "concentration_penalty": 1.0,
        "information_gain_reward": 1.0,
    }
    parameters.update(overrides)
    evidence = FittedObjectiveEvidenceV2(
        optimizer_id="walk_forward_objective_optimizer_v2",
        optimizer_family="purged_walk_forward_multiobjective",
        objective_parameter_fingerprint=_hash(parameters),
        fit_receipt_sha256=_sha("1"),
        training_row_digest=_sha("2"),
        training_population_sha256=_sha("3"),
        fit_window_start_ms=100,
        fit_window_end_ms=900,
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
    parameters = {
        "champion_exploitation_probability": exploitation,
        "bounded_exploration_probability": 1.0 - exploitation,
        "state_sha256": _sha("5"),
        "checkpoint_generation": 3,
    }
    return AdaptivePolicyModeAllocationV2(
        **parameters,
        allocation_parameter_fingerprint=_hash(parameters),
        fit_receipt_sha256=_sha("6"),
        optimizer_id="adaptive_mode_allocator_v2",
        fitted=True,
        permanent_percentage=False,
    )


def _action(
    action_id: str,
    mode: str,
    **overrides: object,
) -> ActionObjectiveInputsV2:
    values: dict[str, object] = {
        "action_id": action_id,
        "action_sha256": _hash({"action_id": action_id}),
        "checkpoint_generation": 3,
        "checkpoint_id": "checkpoint_003",
        "checkpoint_sha256": _sha("4"),
        "selected_action": "DIRECTIONAL_TRADE",
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
        "hard_validator_receipt_sha256": _sha("7"),
        "paper_only": True,
    }
    values.update(overrides)
    return ActionObjectiveInputsV2(**values)  # type: ignore[arg-type]


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
        selected_action="REMAIN_FLAT",
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
        selected_action="REMAIN_FLAT",
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


def test_all_flat_or_hard_invalid_is_a_learning_failure_not_terminal_no_edge() -> None:
    flat = _action(
        "flat",
        CHAMPION_EXPLOITATION,
        selected_action="REMAIN_FLAT",
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
        hard_validator_receipt_sha256=None,
    )
    result = evaluate_shadow_objective((flat, invalid), _weights(), _allocation())
    assert "POLICY_FLAT_COLLAPSE_REQUIRES_LEARNING_ESCALATION" in result.failure_signals
    assert "NO_EXECUTABLE_INFORMATION_SEEKING_ACTION" in result.failure_signals
    assert all("NO_EDGE" not in signal for signal in result.failure_signals)
    invalid_score = next(item for item in result.scores if item.action_id == "invalid_explore")
    assert invalid_score.eligible is False
    assert invalid_score.utility is None


def test_hard_pass_requires_receipt_and_paper_only() -> None:
    with pytest.raises(AdaptiveObjectiveContractError, match="lowercase_sha256"):
        _action("bad", CHAMPION_EXPLOITATION, hard_validator_receipt_sha256=None)
    with pytest.raises(AdaptiveObjectiveContractError, match="paper_only"):
        _action("bad", CHAMPION_EXPLOITATION, paper_only=False)


def test_action_and_objective_checkpoint_must_match() -> None:
    action = _action("bad", CHAMPION_EXPLOITATION, checkpoint_generation=2)
    with pytest.raises(AdaptiveObjectiveContractError, match="checkpoint_mismatch"):
        score_action(action, _weights())


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
