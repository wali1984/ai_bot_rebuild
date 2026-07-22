from __future__ import annotations

import copy
import json
import os
import pickle
import random
import subprocess
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import torch

from v2.backend.app.services.native_trainer import (
    authenticated_profiled_supervised_optimizer_execution_v1 as execution_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_supervised_checkpoint_inventory_v1 as checkpoint_module,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_corpus_v1 import (
    build_authenticated_profiled_optimizer_corpus_v1,
    validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1,
)
from v2.backend.app.services.native_trainer.checkpoint_feature_abi_binding_v4 import (
    deployed_checkpoint_feature_abi_binding_v4,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    model_parameter_fingerprint,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    V2HybridPPOTrainer,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    LOGICAL_MODEL_INPUT_COUNT,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_authenticated_profiled_optimizer_admission_v1 as admission_support,
)

adapter_evidence = admission_support.adapter_evidence

_INPUT_BUDGET = 8 * 1024 * 1024
_STATE_BUDGET = 64 * 1024 * 1024
_CHECKPOINT_BUDGET = 128 * 1024 * 1024


def _parse_clock(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _configure_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0.10")
    monkeypatch.setenv("V2_TRAINER_CPU_THREADS", "1")
    monkeypatch.setenv("V2_TRAINER_FAST_STEP_METRICS", "1")
    monkeypatch.setenv("V2_TRAINER_TAIL_CVAR_WEIGHT", "0")
    monkeypatch.setenv("V2_TRAINER_TAIL_CVAR_ALPHA", "0.1")
    monkeypatch.setenv("AI_BOT_CODE_SHA", "a" * 40)
    def verified_test_release() -> str:
        value = os.environ.get("AI_BOT_CODE_SHA", "")
        if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
            execution_module._fail(
                "PROFILED_SUPERVISED_EXECUTION_PINNED_CODE_RELEASE_REQUIRED"
            )
        return value

    monkeypatch.setattr(execution_module, "_code_release_sha", verified_test_release)
    monkeypatch.delenv("V2_TRAINER_ATTENTION_ENCODER", raising=False)
    monkeypatch.delenv("V2_TRAINER_TEMPORAL_ENCODER", raising=False)


def _training_observed_at(before_corpus: Any) -> datetime:
    return max(
        _parse_clock(before_corpus.witness_accepted_at),
        _parse_clock(before_corpus.causal_clock_range.latest_label_available_at),
    ) + timedelta(seconds=1)


def _strict_stage_clock(training_observed_at: datetime) -> Callable[[], datetime]:
    values = iter(training_observed_at + timedelta(seconds=offset) for offset in range(1, 8))
    return lambda: next(values)


def _runtime(
    *,
    before_corpus: Any,
    bind_feature_abi: bool = True,
) -> tuple[V2HybridPolicyModel, V2HybridPPOTrainer]:
    model = V2HybridPolicyModel(
        input_dim=LOGICAL_MODEL_INPUT_COUNT,
        checkpoint_feature_abi_binding=(
            deployed_checkpoint_feature_abi_binding_v4() if bind_feature_abi else None
        ),
    )
    trainer = V2HybridPPOTrainer(
        model=model,
        learning_rate=1e-4,
        weight_decay=0.0,
        entropy_coefficient=0.0,
        supervised_entropy_bonus=0.0,
        training_observed_at=_training_observed_at(before_corpus),
    )
    return model, trainer


def _execution_inputs(
    corpus_bundle: dict[str, Any],
    *,
    model: V2HybridPolicyModel,
    trainer: V2HybridPPOTrainer,
) -> dict[str, Any]:
    return {
        "before_corpus": corpus_bundle["before"],
        "after_corpus": corpus_bundle["after"],
        "execution_authorization": corpus_bundle["authorization"],
        "base_model": model,
        "trainer": trainer,
        "validation_fraction": 0.2,
        "optimizer_input_byte_budget": _INPUT_BUDGET,
        "state_resource_budget_bytes": _STATE_BUDGET,
        "checkpoint_serialization_byte_budget": _CHECKPOINT_BUDGET,
        "clock": _strict_stage_clock(trainer.training_observed_at),
    }


@pytest.fixture(scope="module")
def corpus_bundle(adapter_evidence: dict[str, Any]) -> dict[str, Any]:
    admitted = admission_support._admit(adapter_evidence)
    before = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    after = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    authorization = validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1(
        before=before,
        after=after,
    )
    return {
        "admitted": admitted,
        "before": before,
        "after": after,
        "authorization": authorization,
    }


@pytest.fixture(scope="module")
def completed_execution(corpus_bundle: dict[str, Any]) -> dict[str, Any]:
    monkeypatch = pytest.MonkeyPatch()
    _configure_cpu(monkeypatch)
    monkeypatch.setenv("V2_TRAINER_UNRELATED_SECRET", "must-not-enter-artifact")
    try:
        model, trainer = _runtime(before_corpus=corpus_bundle["before"])
        base_fingerprint = model_parameter_fingerprint(model)
        python_rng_state = random.getstate()
        torch_rng_state = torch.random.get_rng_state().clone()
        result = execution_module.execute_authenticated_profiled_supervised_optimizer_v1(
            **_execution_inputs(corpus_bundle, model=model, trainer=trainer)
        )
        assert model_parameter_fingerprint(model) == base_fingerprint
        assert random.getstate() == python_rng_state
        assert torch.equal(torch.random.get_rng_state(), torch_rng_state)
        yield {
            "base_model": model,
            "candidate_model": result.candidate_model,
            "trainer": trainer,
            "result": result,
        }
    finally:
        monkeypatch.undo()


def test_executes_exactly_one_authenticated_outcome_supervised_step(
    completed_execution: dict[str, Any],
) -> None:
    result = completed_execution["result"]
    base_model = completed_execution["base_model"]
    candidate_model = completed_execution["candidate_model"]
    training_artifact = json.loads(result.training_result_artifact_json_bytes)

    assert result.status == (
        execution_module.AUTHENTICATED_PROFILED_SUPERVISED_OPTIMIZER_EXECUTION_V1_STATUS
    )
    assert result.admitted_example_count == 1
    assert result.optimizer_training_row_count == 1
    assert result.validation_row_count == 0
    assert result.optimizer_steps_requested == result.optimizer_steps_completed == 1
    assert result.learning_mode == "outcome_supervised"
    assert result.base_model_parameter_fingerprint == model_parameter_fingerprint(base_model)
    assert result.base_model_parameter_fingerprint != result.candidate_model_parameter_fingerprint
    assert result.candidate_model_parameter_fingerprint == model_parameter_fingerprint(
        candidate_model
    )
    assert result.isolated_candidate_model_created is True
    assert result.base_model_unchanged is True
    assert result.process_rng_state_restored is True
    assert result.public_authenticated_trainer_boundary_used is True
    assert training_artifact["learning_update_lane"] == "outcome_supervised"
    assert training_artifact["ppo_objective_used"] is False
    assert training_artifact["outcome_supervised_update_used"] is True
    assert training_artifact["ppo_clipped_surrogate_rows"] == 0
    assert training_artifact["outcome_supervised_batch_rows"] == 1
    assert training_artifact["optimizer_steps_this_cycle"] == 1
    assert training_artifact["tensor_nan_inf_count"] == 0
    assert type(training_artifact["feedback_head_nudge_applied"]) is bool
    assert type(training_artifact["expected_move_head_saturation_recovery_applied"]) is bool
    assert training_artifact["confidence_calibration_checkpoint_bound"] is True
    execution_module.validate_authenticated_profiled_supervised_optimizer_execution_owner_v1(
        execution=result,
        candidate_model=candidate_model,
    )


def test_candidate_contains_exact_model_state_but_no_optimizer_or_downstream_authority(
    completed_execution: dict[str, Any],
) -> None:
    result = completed_execution["result"]
    candidate = result.checkpoint_candidate
    configuration = json.loads(candidate.optimizer_configuration_artifact_json_bytes)
    environment = json.loads(candidate.execution_environment_artifact_json_bytes)
    implementation = json.loads(candidate.optimizer_implementation_artifact_bytes)
    candidate_nonparameter_state = json.loads(
        result.candidate_nonparameter_model_state_artifact_json_bytes
    )

    assert candidate.before_state.model_tensor_count > 0
    assert candidate.after_state.model_tensor_count == candidate.before_state.model_tensor_count
    assert candidate.before_state.optimizer_tensor_count == 0
    assert candidate.after_state.optimizer_tensor_count == 0
    assert configuration["optimizer_state_persisted"] is False
    assert configuration["adamw_optimizer_steps"] == 1
    assert configuration["chronological_label_purged_validation_performed"] is False
    assert result.base_checkpoint_id is None
    assert result.base_checkpoint_weight_sha256 is None
    assert result.base_checkpoint_lineage_deferred is True
    assert environment["candidate_nonparameter_model_state"] == (candidate_nonparameter_state)
    source_paths = {
        item["relative_path"] for item in implementation["ordered_source_files"]
    }
    assert implementation["closure_scope"] == "ALL_PYTHON_SOURCE_UNDER_V2_BACKEND_APP"
    assert implementation["source_file_count"] == len(source_paths)
    expected_source_count = len(
        tuple((execution_module._project_root() / "v2/backend/app").rglob("*.py"))
    )
    assert implementation["source_file_count"] == expected_source_count
    assert (
        "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/"
        "on_policy_behavior.py"
    ) in source_paths
    assert all(
        getattr(result, field_name) is False for field_name in execution_module._AUTHORITY_FALSE
    )
    assert all(
        getattr(candidate, field_name) is False for field_name in checkpoint_module._AUTHORITY_FALSE
    )


def test_same_base_corpus_and_release_replay_to_identical_candidate(
    completed_execution: dict[str, Any],
    corpus_bundle: dict[str, Any],
) -> None:
    first = completed_execution["result"]
    base_model = completed_execution["base_model"]
    trainer = completed_execution["trainer"]
    base_fingerprint = model_parameter_fingerprint(base_model)

    second = execution_module.execute_authenticated_profiled_supervised_optimizer_v1(
        **_execution_inputs(corpus_bundle, model=base_model, trainer=trainer)
    )

    assert model_parameter_fingerprint(base_model) == base_fingerprint
    assert second.execution_idempotency_key == first.execution_idempotency_key
    assert (
        second.candidate_model_parameter_fingerprint == first.candidate_model_parameter_fingerprint
    )
    assert second.checkpoint_bytes_sha256 == first.checkpoint_bytes_sha256
    assert second.checkpoint_candidate.checkpoint_bytes == (
        first.checkpoint_candidate.checkpoint_bytes
    )


def test_environment_artifact_captures_only_explicit_nonsecret_allowlist(
    completed_execution: dict[str, Any],
) -> None:
    candidate = completed_execution["result"].checkpoint_candidate
    environment = json.loads(candidate.execution_environment_artifact_json_bytes)

    assert environment["trainer_environment_overrides"]["V2_TRAINER_HIDDEN_SIZE"] == "128"
    assert "V2_TRAINER_UNRELATED_SECRET" not in environment["trainer_environment_overrides"]
    assert (
        "must-not-enter-artifact"
        not in candidate.execution_environment_artifact_json_bytes.decode("ascii")
    )


def test_result_is_process_private_and_tamper_evident(
    completed_execution: dict[str, Any],
) -> None:
    result = completed_execution["result"]

    with pytest.raises(
        execution_module.AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
        match="PROFILED_SUPERVISED_EXECUTION_PICKLE_OR_COPY_FORBIDDEN",
    ):
        copy.copy(result)
    with pytest.raises(
        execution_module.AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
        match="PROFILED_SUPERVISED_EXECUTION_PICKLE_OR_COPY_FORBIDDEN",
    ):
        pickle.dumps(result)
    with pytest.raises(
        execution_module.AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
        match="PROFILED_SUPERVISED_EXECUTION_RESULT_INVALID",
    ):
        replace(result, status="FORGED")


def test_owner_validator_rejects_equivalent_but_distinct_model(
    completed_execution: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cpu(monkeypatch)
    other_model = V2HybridPolicyModel(
        input_dim=LOGICAL_MODEL_INPUT_COUNT,
        checkpoint_feature_abi_binding=deployed_checkpoint_feature_abi_binding_v4(),
    )

    with pytest.raises(
        execution_module.AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
        match="PROFILED_SUPERVISED_EXECUTION_CANDIDATE_MODEL_OWNER_MISMATCH",
    ):
        execution_module.validate_authenticated_profiled_supervised_optimizer_execution_owner_v1(
            execution=completed_execution["result"],
            candidate_model=other_model,
        )


@pytest.mark.parametrize(
    ("bind_feature_abi", "input_budget", "state_budget", "expected_reason"),
    (
        (
            False,
            _INPUT_BUDGET,
            _STATE_BUDGET,
            "PROFILED_SUPERVISED_EXECUTION_FEATURE_ABI_BINDING_REQUIRED",
        ),
        (
            True,
            1,
            _STATE_BUDGET,
            "PROFILED_SUPERVISED_EXECUTION_INPUT_BUDGET_EXCEEDED",
        ),
        (
            True,
            _INPUT_BUDGET,
            1,
            "PROFILED_SUPERVISED_EXECUTION_STATE_BUDGET_EXCEEDED",
        ),
    ),
)
def test_preconditions_fail_closed_without_model_mutation(
    corpus_bundle: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    bind_feature_abi: bool,
    input_budget: int,
    state_budget: int,
    expected_reason: str,
) -> None:
    _configure_cpu(monkeypatch)
    model, trainer = _runtime(
        before_corpus=corpus_bundle["before"],
        bind_feature_abi=bind_feature_abi,
    )
    fingerprint_before = model_parameter_fingerprint(model)
    inputs = _execution_inputs(corpus_bundle, model=model, trainer=trainer)
    inputs["optimizer_input_byte_budget"] = input_budget
    inputs["state_resource_budget_bytes"] = state_budget

    with pytest.raises(
        execution_module.AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
        match=expected_reason,
    ):
        execution_module.execute_authenticated_profiled_supervised_optimizer_v1(**inputs)

    assert model_parameter_fingerprint(model) == fingerprint_before


def test_unpinned_code_release_fails_before_candidate_creation(
    corpus_bundle: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cpu(monkeypatch)
    model, trainer = _runtime(before_corpus=corpus_bundle["before"])
    fingerprint_before = model_parameter_fingerprint(model)
    monkeypatch.delenv("AI_BOT_CODE_SHA")

    with pytest.raises(
        execution_module.AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
        match="PROFILED_SUPERVISED_EXECUTION_PINNED_CODE_RELEASE_REQUIRED",
    ):
        execution_module.execute_authenticated_profiled_supervised_optimizer_v1(
            **_execution_inputs(corpus_bundle, model=model, trainer=trainer)
        )

    assert model_parameter_fingerprint(model) == fingerprint_before


def test_git_release_verifier_requires_exact_clean_application_tree(tmp_path: Path) -> None:
    app_root = tmp_path / "v2/backend/app"
    app_root.mkdir(parents=True)
    source = app_root / "runtime.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    def git(*arguments: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # noqa: S603
            ("/usr/bin/git", "-C", str(tmp_path), *arguments),
            check=True,
            capture_output=True,
        )

    git("init", "--quiet")
    git("config", "user.email", "trainer-test@example.invalid")
    git("config", "user.name", "Trainer Test")
    git("add", "v2/backend/app/runtime.py")
    git("commit", "--quiet", "-m", "test release")
    release_sha = git("rev-parse", "HEAD").stdout.decode("ascii").strip()

    assert execution_module._verify_git_release_at_root(
        project_root=tmp_path,
        expected_sha=release_sha,
    ) == release_sha

    source.write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(
        execution_module.AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
        match="PROFILED_SUPERVISED_EXECUTION_DEPLOYED_APPLICATION_TREE_DIRTY",
    ):
        execution_module._verify_git_release_at_root(
            project_root=tmp_path,
            expected_sha=release_sha,
        )
    git("checkout", "--", "v2/backend/app/runtime.py")

    (app_root / "untracked.py").write_text("VALUE = 3\n", encoding="utf-8")
    with pytest.raises(
        execution_module.AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
        match="PROFILED_SUPERVISED_EXECUTION_DEPLOYED_APPLICATION_TREE_DIRTY",
    ):
        execution_module._verify_git_release_at_root(
            project_root=tmp_path,
            expected_sha=release_sha,
        )
    (app_root / "untracked.py").unlink()

    with pytest.raises(
        execution_module.AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
        match="PROFILED_SUPERVISED_EXECUTION_PINNED_CODE_RELEASE_MISMATCH",
    ):
        execution_module._verify_git_release_at_root(
            project_root=tmp_path,
            expected_sha="0" * 40,
        )


def test_execution_authorization_cannot_be_rebound_to_equivalent_corpus_objects(
    corpus_bundle: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cpu(monkeypatch)
    unrelated_before = build_authenticated_profiled_optimizer_corpus_v1(
        (corpus_bundle["admitted"],)
    )
    unrelated_after = build_authenticated_profiled_optimizer_corpus_v1((corpus_bundle["admitted"],))
    rebound = {
        **corpus_bundle,
        "before": unrelated_before,
        "after": unrelated_after,
    }
    model, trainer = _runtime(before_corpus=unrelated_before)
    fingerprint_before = model_parameter_fingerprint(model)

    with pytest.raises(
        execution_module.AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
        match="PROFILED_SUPERVISED_EXECUTION_AUTHORIZATION_REVALIDATION_FAILED",
    ):
        execution_module.execute_authenticated_profiled_supervised_optimizer_v1(
            **_execution_inputs(rebound, model=model, trainer=trainer)
        )

    assert model_parameter_fingerprint(model) == fingerprint_before


def test_exception_after_model_mutation_restores_exact_candidate_state(
    corpus_bundle: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cpu(monkeypatch)
    model, trainer = _runtime(before_corpus=corpus_bundle["before"])
    fingerprint_before = model_parameter_fingerprint(model)
    calibration_before = model.confidence_calibration_state
    training_mode_before = bool(model.net.training)

    def mutate_then_raise(self: V2HybridPPOTrainer, *_args: Any, **_kwargs: Any) -> Any:
        assert self.model.net is not None
        assert self.model.torch is not None
        with self.model.torch.no_grad():
            next(self.model.net.parameters()).add_(1.0)
        raise RuntimeError("unit execution failure after mutation")

    monkeypatch.setattr(
        V2HybridPPOTrainer,
        "train_authenticated_profiled_outcome_supervised",
        mutate_then_raise,
    )

    with pytest.raises(
        execution_module.AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
        match="PROFILED_SUPERVISED_EXECUTION_FAILED:RuntimeError",
    ):
        execution_module.execute_authenticated_profiled_supervised_optimizer_v1(
            **_execution_inputs(corpus_bundle, model=model, trainer=trainer)
        )

    assert model_parameter_fingerprint(model) == fingerprint_before
    assert model.confidence_calibration_state == calibration_before
    assert bool(model.net.training) is training_mode_before


def test_nonmonotonic_stage_clock_fails_closed_and_rolls_back(
    corpus_bundle: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_cpu(monkeypatch)
    model, trainer = _runtime(before_corpus=corpus_bundle["before"])
    fingerprint_before = model_parameter_fingerprint(model)
    first = trainer.training_observed_at + timedelta(seconds=1)
    values = iter((first, first))
    inputs = _execution_inputs(corpus_bundle, model=model, trainer=trainer)
    inputs["clock"] = lambda: next(values)

    with pytest.raises(
        execution_module.AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
        match="PROFILED_SUPERVISED_EXECUTION_BEFORE_STATE_CLOCK_INVALID",
    ):
        execution_module.execute_authenticated_profiled_supervised_optimizer_v1(**inputs)

    assert model_parameter_fingerprint(model) == fingerprint_before
