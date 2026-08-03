from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, BinaryIO

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    checkpoint as checkpoint_module,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (
    NON_SERVING_CANDIDATE_LINEAGE,
    OPTIMIZER_ANOMALY_COUNTER_FIELDS,
    VERIFIED_SERVING_LINEAGE,
    checkpoint_evidence,
    serving_promotion_decision,
    verified_candidate_checkpoint_evidence,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    CONFIDENCE_UNCERTAINTY_EVIDENCE_FIELDS,
    CONFIDENCE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION,
    CONFIDENCE_UNCERTAINTY_METHOD,
    confidence_uncertainty_evidence_digest,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    model_parameter_fingerprint,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.runtime import (
    _verified_serving_checkpoint_evidence,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.training_state import (
    candidate_progress_decision,
    confidence_promotion_decision,
    training_partition_digest,
)


def _calibration_state(fingerprint: str) -> dict[str, object]:
    return {
        "schema_version": "v2_profitability_confidence_calibration_v2",
        "fitted": True,
        "reason": None,
        "temperature": 1.2,
        "sample": 4,
        "positive_outcomes": 2,
        "negative_outcomes": 2,
        "fit_partition": "PURGED_TRAIN_ONLY",
        "validation_rows_used": 0,
        "label_semantics": (
            "P_SELECTED_DIRECTIONAL_ACTION_RECOMPUTED_NET_PNL_AFTER_EXPLICIT_COSTS_GT_ZERO_V2"
        ),
        "confidence_head_schema_version": (
            "v2_per_directional_action_profitability_head_v1"
        ),
        "confidence_head_actions": ["long", "short"],
        "action_counts": {"long": 2, "short": 2},
        "model_parameter_fingerprint": fingerprint,
        "row_digest": "1" * 64,
    }


def _promotion_metrics(
    fingerprint: str,
    *,
    parent_fingerprint: str = "a" * 64,
) -> dict[str, object]:
    metrics: dict[str, object] = {
        "validation_split_pit_safe": True,
        "validation_split_temporal_overlap": False,
        "validation_split_label_overlap": False,
        "validation_split_actual_training_rows": 4,
        "validation_split_actual_validation_rows": 4,
        "validation_split_training_end_decision_time": "2026-01-01T00:00:00Z",
        "validation_split_training_label_available_at_max": "2026-01-01T00:00:30Z",
        "validation_split_validation_start_decision_time": "2026-01-01T00:01:00Z",
        "validation_rows": 4,
        "validation_rows_evaluated": 4,
        "optimizer_steps_this_cycle": 1,
        "parameter_hash_before": parent_fingerprint,
        "parameter_hash_after": fingerprint,
        "actual_training_parent_policy_fingerprint": parent_fingerprint,
        "actual_candidate_policy_fingerprint": fingerprint,
        "optimizer_parameter_fingerprints_bound": True,
        "optimizer_anomaly_counters_complete": True,
        "anomaly_free_optimizer_cycle": True,
        "training_cycle_rolled_back": False,
        "weight_delta_norm": 0.1,
        "validation_supervised_loss_before": 2.0,
        "validation_supervised_loss": 1.5,
        "validation_policy_edge_before_lower_confidence_bound_bps": 1.0,
        "validation_policy_edge_status": "VALID",
        "validation_policy_edge_evidence_valid": True,
        "validation_policy_edge_after_cost_bps": 2.0,
        "validation_policy_edge_standard_error_bps": 0.5,
        "validation_policy_edge_lower_confidence_bound_bps": 1.5,
        "validation_policy_edge_uncertainty_method": (
            "sample_mean_minus_one_standard_error"
        ),
        "validation_policy_edge_uncertainty_multiplier": 1.0,
        "validation_policy_edge_rows_evaluated": 4,
        "learning_update_lane": "outcome_supervised",
        "ppo_consumed_update_keys": [],
        "ppo_consumed_update_keys_complete": True,
        "ppo_consumed_update_keys_ordered": True,
        "ppo_consumed_update_keys_unique": True,
        "confidence_calibration_fitted": True,
        "confidence_calibration_fit_partition": "PURGED_TRAIN_ONLY",
        "confidence_calibration_validation_rows_used": 0,
        "confidence_calibration_label_semantics": (
            "P_SELECTED_DIRECTIONAL_ACTION_RECOMPUTED_NET_PNL_AFTER_EXPLICIT_COSTS_GT_ZERO_V2"
        ),
        "confidence_calibration_model_parameter_fingerprint": fingerprint,
        "validation_confidence_status": (
            "EVALUATED_UNTOUCHED_FORWARD_PARTITION"
        ),
        "validation_confidence_partition_untouched": True,
        "validation_confidence_fit_validation_digest_disjoint": True,
        "validation_confidence_rows_used_for_fit": 0,
        "validation_confidence_label_semantics": (
            "P_SELECTED_DIRECTIONAL_ACTION_RECOMPUTED_NET_PNL_AFTER_EXPLICIT_COSTS_GT_ZERO_V2"
        ),
        "validation_confidence_fit_row_digest": "1" * 64,
        "validation_confidence_eligible_row_digest": "2" * 64,
        "validation_confidence_rows_evaluated": 4,
        "validation_confidence_long_rows": 2,
        "validation_confidence_short_rows": 2,
        "validation_confidence_raw_brier": 0.24,
        "validation_confidence_calibrated_brier": 0.22,
        "validation_confidence_raw_ece": 0.18,
        "validation_confidence_calibrated_ece": 0.16,
    }
    metrics.update(
        {field_name: 0 for field_name in OPTIMIZER_ANOMALY_COUNTER_FIELDS}
    )
    for action in ("long", "short"):
        metrics[f"validation_confidence_{action}_raw_brier"] = 0.25
        metrics[f"validation_confidence_{action}_calibrated_brier"] = 0.23
        metrics[f"validation_confidence_{action}_raw_ece"] = 0.2
        metrics[f"validation_confidence_{action}_calibrated_ece"] = 0.19
    for scope, count, brier_delta, ece_delta in (
        ("", 4, -0.02, -0.02),
        ("long_", 2, -0.02, -0.01),
        ("short_", 2, -0.02, -0.01),
    ):
        prefix = f"validation_confidence_{scope}"
        metrics[f"{prefix}paired_brier_delta_per_row"] = [brier_delta] * count
        metrics[f"{prefix}paired_brier_delta_mean"] = brier_delta
        metrics[f"{prefix}paired_brier_delta_standard_error"] = 0.0
        metrics[
            f"{prefix}paired_brier_delta_one_standard_error_upper_bound"
        ] = brier_delta
        metrics[f"{prefix}paired_brier_uncertainty_available"] = True
        metrics[f"{prefix}paired_brier_non_regression_proven"] = True
        metrics[f"{prefix}ece_delta"] = ece_delta
        metrics[f"{prefix}ece_leave_one_out_delta"] = [ece_delta] * count
        metrics[f"{prefix}ece_jackknife_standard_error"] = 0.0
        metrics[f"{prefix}ece_one_standard_error_upper_bound"] = ece_delta
        metrics[f"{prefix}ece_uncertainty_available"] = True
        metrics[f"{prefix}ece_non_regression_proven"] = True
        metrics[f"{prefix}uncertainty_row_count"] = count
        metrics[f"{prefix}uncertainty_minimum_not_configured"] = True
        metrics[f"{prefix}uncertainty_mathematical_minimum_rows"] = 2
        scope_name = scope.rstrip("_").upper() if scope else "GLOBAL"
        metrics[f"{prefix}uncertainty_evidence_schema_version"] = (
            CONFIDENCE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION
        )
        metrics[f"{prefix}uncertainty_scope"] = scope_name
        metrics[f"{prefix}uncertainty_method"] = CONFIDENCE_UNCERTAINTY_METHOD
        metrics[f"{prefix}uncertainty_evidence_digest"] = (
            confidence_uncertainty_evidence_digest(
                scope=scope_name,
                evidence={
                    field_name: metrics[f"{prefix}{field_name}"]
                    for field_name in CONFIDENCE_UNCERTAINTY_EVIDENCE_FIELDS
                },
            )
        )
    return metrics


def _write_bootstrap_serving_checkpoint(
    model_dir: Path,
    *,
    forge_candidate_decision: bool = False,
) -> tuple[V2HybridCheckpointManager, object]:
    manager = V2HybridCheckpointManager(model_dir)
    model = V2HybridPolicyModel(input_dim=4, seed=101)
    if not model.torch_available:
        pytest.skip("checkpoint-bound confidence requires the torch model")
    parent_fingerprint = model_parameter_fingerprint(model)
    assert model.torch is not None and model.net is not None
    with model.torch.no_grad():
        next(model.net.parameters()).view(-1)[0].add_(0.001)
    candidate_fingerprint = model_parameter_fingerprint(model)
    model.set_confidence_calibration_state(
        _calibration_state(candidate_fingerprint)
    )
    metrics = _promotion_metrics(
        candidate_fingerprint,
        parent_fingerprint=parent_fingerprint,
    )
    candidate = candidate_progress_decision(metrics)
    if forge_candidate_decision:
        candidate = {**candidate, "validation_loss_non_regression": False}
    confidence = confidence_promotion_decision(
        training_metrics=metrics,
        calibration_state=model.confidence_calibration_state,
        candidate_policy_fingerprint=candidate_fingerprint,
    )
    serving = serving_promotion_decision(
        training_metrics=metrics,
        candidate_decision=candidate,
        confidence_decision=confidence,
        prior_verified_serving_exists=False,
        training_parent_is_verified_serving=False,
    )
    assert serving["checkpoint_promotion_allowed"] is True
    evidence = checkpoint_evidence(
        checkpoint_role=VERIFIED_SERVING_LINEAGE,
        ledger_disposition="SERVING_PROMOTED",
        candidate_decision=candidate,
        confidence_decision=confidence,
        serving_decision=serving,
        training_metrics=metrics,
        ordered_update_keys=[],
    )
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind=VERIFIED_SERVING_LINEAGE,
        parent_checkpoint_id=None,
        parent_policy_fingerprint=parent_fingerprint,
        consumed_ppo_update_keys=(),
        training_partition_digest=training_partition_digest([]),
        checkpoint_evidence=evidence,
    )
    return manager, manifest


def test_checkpoint_evidence_persists_exact_optimizer_readiness_contract() -> None:
    update_key = "1" * 64
    evidence = checkpoint_evidence(
        checkpoint_role=VERIFIED_SERVING_LINEAGE,
        ledger_disposition="SERVING_PROMOTED",
        candidate_decision={"candidate_progress_allowed": True},
        confidence_decision={"confidence_promotion_gate_passed": True},
        serving_decision={"checkpoint_promotion_allowed": True},
        training_metrics={
            "exact_optimizer_contract_valid": True,
            "ppo_objective_used": True,
            "optimizer_parameter_fingerprints_bound": True,
            "ppo_rows_consumed": 1,
            "ppo_clipped_surrogate_rows": 1,
            "ppo_rows_available_but_optimizer_unavailable": 0,
        },
        ordered_update_keys=[update_key],
    )

    optimizer = evidence["optimizer_evidence"]
    assert optimizer["exact_optimizer_contract_valid"] is True
    assert optimizer["ppo_objective_used"] is True
    assert optimizer["optimizer_parameter_fingerprints_bound"] is True
    assert optimizer["ppo_rows_consumed"] == 1
    assert optimizer["ppo_clipped_surrogate_rows"] == 1
    assert optimizer["ppo_rows_available_but_optimizer_unavailable"] == 0
    assert optimizer["ppo_consumed_update_keys"] == [update_key]


def test_cold_bootstrap_serving_checkpoint_rederives_complete_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    manager, manifest = _write_bootstrap_serving_checkpoint(
        tmp_path / ".local_models" / "serving"
    )
    restored = V2HybridPolicyModel(input_dim=4, seed=101)
    load = manager.load_latest_weights(
        restored,
        allowed_lineage_kinds=frozenset({VERIFIED_SERVING_LINEAGE}),
    )

    complete, reasons = _verified_serving_checkpoint_evidence(
        load,
        expected_checkpoint_id=manifest.checkpoint_id,
    )

    assert complete is True
    assert reasons == ()


def test_digest_valid_but_semantically_forged_decision_cannot_serve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    manager, manifest = _write_bootstrap_serving_checkpoint(
        tmp_path / ".local_models" / "forged",
        forge_candidate_decision=True,
    )
    load = manager.load_latest_weights(
        V2HybridPolicyModel(input_dim=4, seed=101),
        allowed_lineage_kinds=frozenset({VERIFIED_SERVING_LINEAGE}),
    )

    complete, reasons = _verified_serving_checkpoint_evidence(
        load,
        expected_checkpoint_id=manifest.checkpoint_id,
    )

    assert complete is False
    assert "serving_checkpoint_candidate_decision_not_rederived" in reasons


def test_serving_promotion_rejects_reported_mutation_not_bound_to_actual_weights() -> None:
    actual_fingerprint = "c" * 64
    metrics = _promotion_metrics(
        "b" * 64,
        parent_fingerprint="a" * 64,
    )
    metrics.update(
        {
            "actual_training_parent_policy_fingerprint": actual_fingerprint,
            "actual_candidate_policy_fingerprint": actual_fingerprint,
            # A producer assertion is not proof; the hashes must rederive it.
            "optimizer_parameter_fingerprints_bound": True,
        }
    )
    decision = serving_promotion_decision(
        training_metrics=metrics,
        candidate_decision=candidate_progress_decision(metrics),
        confidence_decision={"confidence_promotion_gate_passed": True},
        prior_verified_serving_exists=False,
        training_parent_is_verified_serving=False,
    )

    assert decision["checkpoint_promotion_allowed"] is False
    assert "SERVING_OPTIMIZER_FINGERPRINT_BINDING_NOT_PROVEN" in decision[
        "checkpoint_promotion_rejection_reasons"
    ]


@pytest.mark.parametrize("counter_field", OPTIMIZER_ANOMALY_COUNTER_FIELDS)
def test_serving_promotion_rejects_every_nonzero_optimizer_anomaly_counter(
    counter_field: str,
) -> None:
    metrics = _promotion_metrics("b" * 64)
    metrics[counter_field] = 1

    decision = serving_promotion_decision(
        training_metrics=metrics,
        candidate_decision=candidate_progress_decision(metrics),
        confidence_decision={"confidence_promotion_gate_passed": True},
        prior_verified_serving_exists=False,
        training_parent_is_verified_serving=False,
    )

    assert decision["checkpoint_promotion_allowed"] is False
    assert (
        f"SERVING_OPTIMIZER_{counter_field.upper()}_NONZERO"
        in decision["checkpoint_promotion_rejection_reasons"]
    )


def test_serving_promotion_rejects_missing_optimizer_anomaly_attestation() -> None:
    metrics = _promotion_metrics("b" * 64)
    metrics.pop("non_finite_gradient_value_count")
    metrics["optimizer_anomaly_counters_complete"] = False

    decision = serving_promotion_decision(
        training_metrics=metrics,
        candidate_decision=candidate_progress_decision(metrics),
        confidence_decision={"confidence_promotion_gate_passed": True},
        prior_verified_serving_exists=False,
        training_parent_is_verified_serving=False,
    )

    assert decision["checkpoint_promotion_allowed"] is False
    assert "SERVING_OPTIMIZER_ANOMALY_COUNTERS_INCOMPLETE" in decision[
        "checkpoint_promotion_rejection_reasons"
    ]
    assert (
        "SERVING_OPTIMIZER_NON_FINITE_GRADIENT_VALUE_COUNT_MISSING_OR_INVALID"
        in decision["checkpoint_promotion_rejection_reasons"]
    )


def test_forged_noop_checkpoint_cannot_serve_or_resume_as_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    model = V2HybridPolicyModel(input_dim=4, seed=109)
    if not model.torch_available:
        pytest.skip("checkpoint-bound confidence requires the torch model")
    actual_fingerprint = model_parameter_fingerprint(model)
    model.set_confidence_calibration_state(
        _calibration_state(actual_fingerprint)
    )
    metrics = _promotion_metrics(
        actual_fingerprint,
        parent_fingerprint=actual_fingerprint,
    )
    # Claim a mutation that never occurred while keeping the real artifact
    # fingerprints explicit. Old verification accepted this mismatch.
    metrics.update(
        {
            "parameter_hash_before": "a" * 64,
            "parameter_hash_after": "b" * 64,
            "optimizer_parameter_fingerprints_bound": True,
        }
    )
    candidate = candidate_progress_decision(metrics)
    assert candidate["candidate_progress_allowed"] is True
    confidence = confidence_promotion_decision(
        training_metrics=metrics,
        calibration_state=model.confidence_calibration_state,
        candidate_policy_fingerprint=actual_fingerprint,
    )
    rejected_serving = serving_promotion_decision(
        training_metrics=metrics,
        candidate_decision=candidate,
        confidence_decision=confidence,
        prior_verified_serving_exists=False,
        training_parent_is_verified_serving=False,
    )
    forged_serving = {
        **rejected_serving,
        "checkpoint_promotion_allowed": True,
        "checkpoint_promotion_rejected": False,
        "checkpoint_promotion_reason": (
            "PIT_EDGE_CONFIDENCE_PARETO_SERVING_PROMOTION_PASS"
        ),
        "checkpoint_promotion_rejection_reasons": [],
        "optimizer_parameter_fingerprints_bound": True,
    }

    serving_manager = V2HybridCheckpointManager(
        tmp_path / ".local_models" / "forged_noop_serving"
    )
    serving_manifest = serving_manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind=VERIFIED_SERVING_LINEAGE,
        parent_checkpoint_id=None,
        parent_policy_fingerprint=actual_fingerprint,
        consumed_ppo_update_keys=(),
        training_partition_digest=training_partition_digest([]),
        checkpoint_evidence=checkpoint_evidence(
            checkpoint_role=VERIFIED_SERVING_LINEAGE,
            ledger_disposition="SERVING_PROMOTED",
            candidate_decision=candidate,
            confidence_decision=confidence,
            serving_decision=forged_serving,
            training_metrics=metrics,
            ordered_update_keys=[],
        ),
    )
    serving_load = serving_manager.load_latest_weights(
        V2HybridPolicyModel(input_dim=4, seed=109),
        allowed_lineage_kinds=frozenset({VERIFIED_SERVING_LINEAGE}),
    )
    serving_complete, serving_reasons = _verified_serving_checkpoint_evidence(
        serving_load,
        expected_checkpoint_id=serving_manifest.checkpoint_id,
    )
    assert serving_load["load_status"] == "LOADED"
    assert serving_complete is False
    assert "serving_checkpoint_optimizer_parent_fingerprint_mismatch" in (
        serving_reasons
    )
    assert "serving_checkpoint_optimizer_artifact_fingerprint_mismatch" in (
        serving_reasons
    )

    candidate_manager = V2HybridCheckpointManager(
        tmp_path / ".local_models" / "forged_noop_candidate"
    )
    candidate_manifest = candidate_manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind=NON_SERVING_CANDIDATE_LINEAGE,
        parent_checkpoint_id=None,
        parent_policy_fingerprint=actual_fingerprint,
        consumed_ppo_update_keys=(),
        training_partition_digest=training_partition_digest([]),
        checkpoint_evidence=checkpoint_evidence(
            checkpoint_role=NON_SERVING_CANDIDATE_LINEAGE,
            ledger_disposition="NON_SERVING_CANDIDATE_PERSISTED",
            candidate_decision=candidate,
            confidence_decision=confidence,
            serving_decision=rejected_serving,
            training_metrics=metrics,
            ordered_update_keys=[],
        ),
    )
    candidate_load = candidate_manager.load_latest_weights(
        V2HybridPolicyModel(input_dim=4, seed=109),
        allowed_lineage_kinds=frozenset({NON_SERVING_CANDIDATE_LINEAGE}),
    )
    candidate_complete, candidate_reasons = (
        verified_candidate_checkpoint_evidence(candidate_load)
    )
    assert candidate_load["checkpoint_id"] == candidate_manifest.checkpoint_id
    assert candidate_complete is False
    assert "CANDIDATE_OPTIMIZER_PARENT_FINGERPRINT_MISMATCH" in (
        candidate_reasons
    )
    assert "CANDIDATE_OPTIMIZER_ARTIFACT_FINGERPRINT_MISMATCH" in (
        candidate_reasons
    )


def test_existing_incumbent_requires_same_partition_parent() -> None:
    metrics = _promotion_metrics("b" * 64)
    candidate = candidate_progress_decision(metrics)
    confidence = {"confidence_promotion_gate_passed": True}

    rejected = serving_promotion_decision(
        training_metrics=metrics,
        candidate_decision=candidate,
        confidence_decision=confidence,
        prior_verified_serving_exists=True,
        training_parent_is_verified_serving=False,
    )

    assert rejected["checkpoint_promotion_allowed"] is False
    assert "SERVING_SAME_PARTITION_INCUMBENT_COMPARISON_NOT_PROVEN" in rejected[
        "checkpoint_promotion_rejection_reasons"
    ]


def test_no_incumbent_candidate_parent_is_distinct_from_fresh_bootstrap() -> None:
    metrics = _promotion_metrics("b" * 64)
    decision = serving_promotion_decision(
        training_metrics=metrics,
        candidate_decision=candidate_progress_decision(metrics),
        confidence_decision={"confidence_promotion_gate_passed": True},
        prior_verified_serving_exists=False,
        training_parent_is_verified_serving=False,
        training_parent_is_non_serving_candidate=True,
    )

    assert decision["checkpoint_promotion_allowed"] is True
    assert decision["same_partition_incumbent_comparison_status"] == (
        "NO_INCUMBENT_VERIFIED_NON_SERVING_CANDIDATE_PARENT"
    )
    assert decision["training_parent_is_non_serving_candidate"] is True


def test_latest_checkpoint_uses_semantic_generation_not_filesystem_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    generated = iter(
        ("2026-07-18T01:00:00Z", "2026-07-18T02:00:00Z")
    )
    monkeypatch.setattr(checkpoint_module, "_utc_iso", lambda: next(generated))
    manager = V2HybridCheckpointManager(tmp_path / ".local_models" / "ordering")
    model = V2HybridPolicyModel(input_dim=4, seed=201)
    older = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device="cpu",
        cuda_active=False,
    )
    older_fingerprint = model_parameter_fingerprint(model)
    if model.torch_available:
        assert model.torch is not None and model.net is not None
        with model.torch.no_grad():
            next(model.net.parameters()).view(-1)[0].add_(0.001)
    else:
        model._fallback_weights[0] += 0.001  # noqa: SLF001
    newer = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device="cpu",
        cuda_active=False,
    )
    # Simulate a backup/scanner touching the old manifest after the new one.
    os.utime(older.path, (2_000_000_000, 2_000_000_000))

    selected = manager.latest_manifest(input_dim=4)
    loaded = manager.load_latest_weights(
        V2HybridPolicyModel(input_dim=4, seed=201)
    )
    manifest_bound_model = V2HybridPolicyModel(input_dim=4, seed=201)
    manifest_bound_load = manager.load_latest_weights(
        manifest_bound_model,
        expected_checkpoint_id=older.checkpoint_id,
    )

    assert selected is not None
    assert selected.checkpoint_id == newer.checkpoint_id
    assert loaded["checkpoint_id"] == newer.checkpoint_id
    assert loaded["load_status"] == "LOADED"
    assert manifest_bound_load["checkpoint_id"] == older.checkpoint_id
    assert manifest_bound_load["load_status"] == "LOADED"
    assert model_parameter_fingerprint(manifest_bound_model) == older_fingerprint


def test_checkpoint_source_replacement_after_verification_cannot_change_loaded_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    manager = V2HybridCheckpointManager(
        tmp_path / ".local_models" / "immutable_load_copy"
    )
    admitted_model = V2HybridPolicyModel(input_dim=4, seed=211)
    manifest = manager.write_checkpoint(
        model=admitted_model,
        input_dim=4,
        device=admitted_model.device,
        cuda_active=admitted_model.cuda_active,
    )
    admitted_fingerprint = str(manifest.model_parameter_fingerprint)
    weight_path = Path(str(manifest.weight_file_path))

    replacement_model = V2HybridPolicyModel(input_dim=4, seed=211)
    if replacement_model.torch_available:
        assert replacement_model.torch is not None
        assert replacement_model.net is not None
        with replacement_model.torch.no_grad():
            next(replacement_model.net.parameters()).view(-1)[0].add_(0.5)
    else:
        replacement_model._fallback_weights[0] += 0.5  # noqa: SLF001
    replacement_fingerprint = model_parameter_fingerprint(replacement_model)
    assert replacement_fingerprint != admitted_fingerprint
    replacement_path = weight_path.with_name("replacement.weights.npz")
    replacement_model.save_weight_blob(replacement_path)
    replacement_sha256 = hashlib.sha256(replacement_path.read_bytes()).hexdigest()
    assert replacement_sha256 != manifest.weight_file_sha256

    original_semantics = checkpoint_module._safe_npz_semantics
    replacement_performed = False

    def replace_source_after_private_verification(
        source: Path | BinaryIO,
        *,
        model_id: str,
    ) -> dict[str, Any]:
        nonlocal replacement_performed
        semantics = original_semantics(source, model_id=model_id)
        if not isinstance(source, Path) and not replacement_performed:
            replacement_path.replace(weight_path)
            replacement_performed = True
        return semantics

    monkeypatch.setattr(
        checkpoint_module,
        "_safe_npz_semantics",
        replace_source_after_private_verification,
    )
    restored = V2HybridPolicyModel(input_dim=4, seed=211)
    loaded = manager.load_latest_weights(restored)

    assert replacement_performed is True
    assert hashlib.sha256(weight_path.read_bytes()).hexdigest() == replacement_sha256
    assert loaded["load_status"] == "LOADED"
    assert loaded["private_checkpoint_copy_verified"] is True
    assert loaded["private_checkpoint_source_open_count"] == 1
    assert loaded["private_checkpoint_copy_sha256"] == manifest.weight_file_sha256
    assert model_parameter_fingerprint(restored) == admitted_fingerprint
    assert model_parameter_fingerprint(restored) != replacement_fingerprint
