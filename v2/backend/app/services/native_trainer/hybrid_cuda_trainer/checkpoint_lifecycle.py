"""Crash-safe candidate, serving, and exact-PPO checkpoint lifecycle."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .checkpoint import V2HybridCheckpointManager
from .training_state import PPOConsumptionLedger, candidate_progress_decision

NON_SERVING_CANDIDATE_LINEAGE = "NON_SERVING_TRAINING_CANDIDATE"
REJECTED_ATTEMPT_LINEAGE = "REJECTED_TRAINING_ATTEMPT"
VERIFIED_SERVING_LINEAGE = "VERIFIED_SERVING_POLICY"

OPTIMIZER_ANOMALY_COUNTER_FIELDS = (
    "non_finite_feature_count",
    "non_finite_expected_label_count",
    "non_finite_loss_steps",
    "non_finite_gradient_steps",
    "non_finite_gradient_value_count",
    "sanitized_gradient_steps",
    "sanitized_gradient_value_count",
    "advantage_anomaly_steps",
    "tensor_nan_inf_count",
    "non_finite_model_output_value_count",
    "non_finite_model_output_events",
    "non_finite_optimizer_ratio_value_count",
    "non_finite_optimizer_ratio_events",
    "non_finite_parameter_value_count_detected",
    "non_finite_parameter_value_count_sanitized",
    "non_finite_parameter_sanitization_events",
)


def _finite(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _sha256_hex(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    )


def _positive_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(numeric) or numeric != float(parsed) or parsed <= 0:
        return None
    return parsed


def _nonnegative_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(numeric) or numeric != float(parsed) or parsed < 0:
        return None
    return parsed


def _optimizer_anomaly_rejection_reasons(
    metrics: Mapping[str, Any],
    *,
    prefix: str,
) -> list[str]:
    reasons: list[str] = []
    if metrics.get("optimizer_anomaly_counters_complete") is not True:
        reasons.append(f"{prefix}_ANOMALY_COUNTERS_INCOMPLETE")
    for field_name in OPTIMIZER_ANOMALY_COUNTER_FIELDS:
        value = _nonnegative_int(metrics.get(field_name))
        if value is None:
            reasons.append(f"{prefix}_{field_name.upper()}_MISSING_OR_INVALID")
        elif value != 0:
            reasons.append(f"{prefix}_{field_name.upper()}_NONZERO")
    if metrics.get("anomaly_free_optimizer_cycle") is not True:
        reasons.append(f"{prefix}_OPTIMIZER_CYCLE_NOT_ANOMALY_FREE")
    if metrics.get("training_cycle_rolled_back") is not False:
        reasons.append(f"{prefix}_TRAINING_CYCLE_ROLLBACK_STATE_INVALID")
    return reasons


@dataclass(frozen=True)
class TrainerCheckpointStores:
    serving: V2HybridCheckpointManager
    candidate: V2HybridCheckpointManager
    rejected_attempt: V2HybridCheckpointManager
    ledger: PPOConsumptionLedger


def checkpoint_stores(model_dir: Path) -> TrainerCheckpointStores:
    root = Path(model_dir)
    candidate_dir = root / "non_serving_training_candidates"
    rejected_dir = root / "rejected_optimizer_attempts"
    return TrainerCheckpointStores(
        serving=V2HybridCheckpointManager(root),
        candidate=V2HybridCheckpointManager(candidate_dir),
        rejected_attempt=V2HybridCheckpointManager(rejected_dir),
        ledger=PPOConsumptionLedger(candidate_dir / "ppo_consumption.sqlite3"),
    )


def reconcile_checkpoint_consumption(
    stores: TrainerCheckpointStores,
    *,
    serving_evidence_verifier: Callable[
        [Mapping[str, Any], str], tuple[bool, tuple[str, ...]]
    ]
    | None = None,
) -> dict[str, Any]:
    """Reconcile every verified artifact before releasing any dead claim."""
    reconciled: list[dict[str, Any]] = []
    sources = (
        (
            stores.serving,
            frozenset({VERIFIED_SERVING_LINEAGE}),
            "SERVING_PROMOTED",
        ),
        (
            stores.candidate,
            frozenset({NON_SERVING_CANDIDATE_LINEAGE}),
            "NON_SERVING_CANDIDATE_PERSISTED",
        ),
        (
            stores.rejected_attempt,
            frozenset({REJECTED_ATTEMPT_LINEAGE}),
            "REJECTED_TRAINING_ATTEMPT_PERSISTED",
        ),
    )
    for manager, lineages, expected_disposition in sources:
        manifests = manager.manifests(
            allowed_lineage_kinds=lineages,
            require_weight_blob=True,
        )
        for manifest in manifests:
            if not manifest.consumed_ppo_update_keys:
                continue
            claims = stores.ledger.claims_for_update_keys(
                manifest.consumed_ppo_update_keys
            )
            if not claims:
                continue
            evidence_disposition = str(
                manifest.checkpoint_evidence.get("ledger_disposition") or ""
            )
            if evidence_disposition != expected_disposition:
                raise RuntimeError(
                    "checkpoint_reconciliation_ledger_disposition_mismatch"
                )
            verified = manager.verify_manifest_artifact(manifest)
            if verified.get("checkpoint_artifact_verified") is not True:
                raise RuntimeError("checkpoint_reconciliation_artifact_invalid")
            if manifest.lineage_kind == VERIFIED_SERVING_LINEAGE:
                if serving_evidence_verifier is None:
                    raise RuntimeError(
                        "checkpoint_reconciliation_serving_semantic_verifier_missing"
                    )
                semantic_valid, semantic_reasons = serving_evidence_verifier(
                    verified,
                    manifest.checkpoint_id,
                )
            elif manifest.lineage_kind == NON_SERVING_CANDIDATE_LINEAGE:
                semantic_valid, semantic_reasons = (
                    verified_candidate_checkpoint_evidence(verified)
                )
            else:
                evidence = verified.get("checkpoint_evidence")
                semantic_valid = bool(
                    isinstance(evidence, Mapping)
                    and evidence.get("checkpoint_role")
                    == REJECTED_ATTEMPT_LINEAGE
                    and evidence.get("ledger_disposition")
                    == "REJECTED_TRAINING_ATTEMPT_PERSISTED"
                    and isinstance(
                        evidence.get("candidate_progress_decision"), Mapping
                    )
                    and evidence["candidate_progress_decision"].get(
                        "candidate_progress_allowed"
                    )
                    is False
                    and isinstance(
                        evidence.get("serving_promotion_decision"), Mapping
                    )
                    and evidence["serving_promotion_decision"].get(
                        "checkpoint_promotion_allowed"
                    )
                    is False
                )
                semantic_reasons = (
                    ()
                    if semantic_valid
                    else ("REJECTED_ATTEMPT_SEMANTIC_EVIDENCE_INVALID",)
                )
            if not semantic_valid:
                raise RuntimeError(
                    "checkpoint_reconciliation_role_semantics_invalid:"
                    + ",".join(semantic_reasons)
                )
            result = stores.ledger.reconcile_verified_checkpoint_attempts(
                checkpoint_load=verified,
                disposition=expected_disposition,
            )
            reconciled.append(
                {
                    "checkpoint_id": manifest.checkpoint_id,
                    "lineage_kind": manifest.lineage_kind,
                    "disposition": expected_disposition,
                    **result,
                }
            )
    ambiguous = stores.ledger.record_ambiguous_dead_optimizer_attempts()
    orphan_recovery = stores.ledger.recover_orphaned_claims()
    return {
        "verified_checkpoint_reconciliations": reconciled,
        "verified_checkpoint_reconciled_attempts": sum(
            int(row.get("reconciled_update_keys") or 0) for row in reconciled
        ),
        **ambiguous,
        **orphan_recovery,
        "ledger_integrity": stores.ledger.verify_integrity(),
    }


def verified_candidate_checkpoint_evidence(
    checkpoint_load: dict[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    """Require rederived Pareto progress before resuming a candidate model."""
    load = dict(checkpoint_load)
    reasons: list[str] = []
    for field_name in (
        "latest_checkpoint_loadable",
        "model_state_restored",
        "weight_file_sha256_verified",
        "model_parameter_fingerprint_verified",
        "checkpoint_evidence_verified",
        "checkpoint_identity_verified",
    ):
        if load.get(field_name) is not True:
            reasons.append(f"CANDIDATE_{field_name.upper()}_FALSE")
    if load.get("lineage_kind") != NON_SERVING_CANDIDATE_LINEAGE:
        reasons.append("CANDIDATE_LINEAGE_INVALID")
    evidence = load.get("checkpoint_evidence")
    if not isinstance(evidence, dict):
        reasons.append("CANDIDATE_EVIDENCE_MISSING")
        evidence = {}
    if evidence.get("checkpoint_role") != NON_SERVING_CANDIDATE_LINEAGE:
        reasons.append("CANDIDATE_ROLE_INVALID")
    if evidence.get("ledger_disposition") != (
        "NON_SERVING_CANDIDATE_PERSISTED"
    ):
        reasons.append("CANDIDATE_LEDGER_DISPOSITION_INVALID")
    optimizer = evidence.get("optimizer_evidence")
    validation = evidence.get("validation_evidence")
    decision = evidence.get("candidate_progress_decision")
    if not isinstance(optimizer, dict) or not isinstance(validation, dict):
        reasons.append("CANDIDATE_RAW_DECISION_EVIDENCE_MISSING")
        optimizer = {}
        validation = {}
    parameter_before = str(optimizer.get("parameter_hash_before") or "")
    parameter_after = str(optimizer.get("parameter_hash_after") or "")
    parent_fingerprint = str(load.get("parent_policy_fingerprint") or "")
    candidate_fingerprint = str(load.get("model_parameter_fingerprint") or "")
    if not _sha256_hex(parameter_before) or not _sha256_hex(parameter_after):
        reasons.append("CANDIDATE_OPTIMIZER_PARAMETER_HASH_INVALID")
    if parameter_before != parent_fingerprint:
        reasons.append("CANDIDATE_OPTIMIZER_PARENT_FINGERPRINT_MISMATCH")
    if parameter_after != candidate_fingerprint:
        reasons.append("CANDIDATE_OPTIMIZER_ARTIFACT_FINGERPRINT_MISMATCH")
    if optimizer.get("actual_training_parent_policy_fingerprint") != (
        parent_fingerprint
    ):
        reasons.append("CANDIDATE_ACTUAL_PARENT_FINGERPRINT_BINDING_MISMATCH")
    if optimizer.get("actual_candidate_policy_fingerprint") != (
        candidate_fingerprint
    ):
        reasons.append("CANDIDATE_ACTUAL_ARTIFACT_FINGERPRINT_BINDING_MISMATCH")
    if optimizer.get("optimizer_parameter_fingerprints_bound") is not True:
        reasons.append("CANDIDATE_OPTIMIZER_FINGERPRINT_BINDING_NOT_PROVEN")
    reasons.extend(
        _optimizer_anomaly_rejection_reasons(
            optimizer,
            prefix="CANDIDATE_OPTIMIZER",
        )
    )
    try:
        rederived = candidate_progress_decision({**validation, **optimizer})
    except Exception as exc:  # noqa: BLE001 - malformed candidate fails closed
        rederived = {}
        reasons.append(f"CANDIDATE_DECISION_RECOMPUTE_FAILED:{type(exc).__name__}")
    if not isinstance(decision, dict) or decision != rederived:
        reasons.append("CANDIDATE_DECISION_NOT_REDERIVED")
    if rederived.get("candidate_progress_allowed") is not True:
        reasons.append("CANDIDATE_PROGRESS_NOT_ALLOWED")
    return not reasons, tuple(sorted(set(reasons)))


def serving_promotion_decision(
    *,
    training_metrics: dict[str, Any],
    candidate_decision: dict[str, Any],
    confidence_decision: dict[str, Any],
    prior_verified_serving_exists: bool,
    training_parent_is_verified_serving: bool,
    training_parent_is_non_serving_candidate: bool = False,
) -> dict[str, Any]:
    """Authorize serving only from recomputed PIT-safe Pareto evidence."""
    metrics = dict(training_metrics)
    reasons: list[str] = []
    if candidate_decision.get("candidate_progress_allowed") is not True:
        reasons.append("SERVING_CANDIDATE_PROGRESS_GATE_FAILED")
    if confidence_decision.get("confidence_promotion_gate_passed") is not True:
        reasons.append("SERVING_CONFIDENCE_PROMOTION_GATE_FAILED")
    optimizer_steps = _positive_int(metrics.get("optimizer_steps_this_cycle"))
    before_hash = str(metrics.get("parameter_hash_before") or "")
    after_hash = str(metrics.get("parameter_hash_after") or "")
    actual_parent_hash = str(
        metrics.get("actual_training_parent_policy_fingerprint") or ""
    )
    actual_candidate_hash = str(
        metrics.get("actual_candidate_policy_fingerprint") or ""
    )
    if optimizer_steps is None:
        reasons.append("SERVING_OPTIMIZER_STEP_NOT_PROVEN")
    if (
        not _sha256_hex(before_hash)
        or not _sha256_hex(after_hash)
        or before_hash == after_hash
    ):
        reasons.append("SERVING_PARAMETER_MUTATION_NOT_PROVEN")
    parameter_fingerprints_bound = bool(
        _sha256_hex(actual_parent_hash)
        and _sha256_hex(actual_candidate_hash)
        and before_hash == actual_parent_hash
        and after_hash == actual_candidate_hash
        and actual_parent_hash != actual_candidate_hash
        and metrics.get("optimizer_parameter_fingerprints_bound") is True
    )
    if not parameter_fingerprints_bound:
        reasons.append("SERVING_OPTIMIZER_FINGERPRINT_BINDING_NOT_PROVEN")
    reasons.extend(
        _optimizer_anomaly_rejection_reasons(
            metrics,
            prefix="SERVING_OPTIMIZER",
        )
    )
    if metrics.get("validation_split_pit_safe") is not True:
        reasons.append("SERVING_VALIDATION_SPLIT_PIT_UNSAFE")
    if metrics.get("validation_split_temporal_overlap") is not False:
        reasons.append("SERVING_VALIDATION_TEMPORAL_OVERLAP_NOT_FALSE")
    if metrics.get("validation_split_label_overlap") is not False:
        reasons.append("SERVING_VALIDATION_LABEL_OVERLAP_NOT_FALSE")
    train_rows = _positive_int(
        metrics.get("validation_split_actual_training_rows")
    )
    validation_rows = _positive_int(
        metrics.get("validation_split_actual_validation_rows")
    )
    edge_rows = _positive_int(metrics.get("validation_policy_edge_rows_evaluated"))
    if train_rows is None or validation_rows is None or edge_rows != validation_rows:
        reasons.append("SERVING_VALIDATION_ROW_COUNTS_INVALID")
    if (
        metrics.get("validation_policy_edge_evidence_valid") is not True
        or metrics.get("validation_policy_edge_status") != "VALID"
    ):
        reasons.append("SERVING_VALIDATION_EDGE_EVIDENCE_INVALID")
    edge_mean = _finite(metrics.get("validation_policy_edge_after_cost_bps"))
    edge_se = _finite(metrics.get("validation_policy_edge_standard_error_bps"))
    edge_lcb = _finite(
        metrics.get("validation_policy_edge_lower_confidence_bound_bps")
    )
    uncertainty_multiplier = _finite(
        metrics.get("validation_policy_edge_uncertainty_multiplier")
    )
    if uncertainty_multiplier is None:
        if metrics.get("validation_policy_edge_uncertainty_method") == (
            "sample_mean_minus_one_standard_error"
        ):
            uncertainty_multiplier = 1.0
        else:
            reasons.append("SERVING_EDGE_UNCERTAINTY_MULTIPLIER_MISSING")
    recomputed_lcb = (
        edge_mean - uncertainty_multiplier * edge_se
        if edge_mean is not None
        and edge_se is not None
        and uncertainty_multiplier is not None
        and edge_se >= 0.0
        and uncertainty_multiplier > 0.0
        else None
    )
    if (
        edge_lcb is None
        or recomputed_lcb is None
        or not math.isclose(edge_lcb, recomputed_lcb, rel_tol=1e-7, abs_tol=1e-7)
    ):
        reasons.append("SERVING_EDGE_LOWER_BOUND_FORMULA_INVALID")
    elif edge_lcb <= 0.0:
        reasons.append("SERVING_EDGE_LOWER_BOUND_NOT_POSITIVE")

    if not prior_verified_serving_exists and training_parent_is_non_serving_candidate:
        comparison_proven = True
        comparison_status = (
            "NO_INCUMBENT_VERIFIED_NON_SERVING_CANDIDATE_PARENT"
        )
    elif not prior_verified_serving_exists:
        comparison_proven = True
        comparison_status = (
            "BOOTSTRAP_NO_INCUMBENT_SAME_PARTITION_NOT_APPLICABLE"
        )
    elif training_parent_is_verified_serving:
        comparison_proven = True
        comparison_status = "PASS_SAME_UNTOUCHED_FORWARD_PARTITION"
    else:
        comparison_proven = False
        comparison_status = "FAIL_TRAINING_PARENT_NOT_VERIFIED_SERVING_INCUMBENT"
        reasons.append("SERVING_SAME_PARTITION_INCUMBENT_COMPARISON_NOT_PROVEN")

    allowed = not reasons
    return {
        "checkpoint_promotion_allowed": allowed,
        "checkpoint_promotion_rejected": not allowed,
        "checkpoint_promotion_reason": (
            "PIT_EDGE_CONFIDENCE_PARETO_SERVING_PROMOTION_PASS"
            if allowed
            else reasons[0]
        ),
        "checkpoint_promotion_rejection_reasons": reasons,
        "mandatory_pit_edge_gate_passed": bool(
            edge_lcb is not None and edge_lcb > 0.0
        ),
        "validation_policy_edge_after_cost_bps": edge_mean,
        "validation_policy_edge_standard_error_bps": edge_se,
        "validation_policy_edge_uncertainty_multiplier": uncertainty_multiplier,
        "validation_policy_edge_recomputed_lower_confidence_bound_bps": (
            recomputed_lcb
        ),
        "validation_policy_edge_lower_confidence_bound_bps": edge_lcb,
        "same_partition_incumbent_comparison_proven": comparison_proven,
        "same_partition_incumbent_comparison_status": comparison_status,
        "prior_verified_serving_exists": prior_verified_serving_exists,
        "training_parent_is_verified_serving": (
            training_parent_is_verified_serving
        ),
        "training_parent_is_non_serving_candidate": (
            training_parent_is_non_serving_candidate
        ),
        "optimizer_parameter_fingerprints_bound": parameter_fingerprints_bound,
        "actual_training_parent_policy_fingerprint": actual_parent_hash or None,
        "actual_candidate_policy_fingerprint": actual_candidate_hash or None,
        "market_static_loss_tolerance_used": False,
        "validation_disable_switch_used": False,
        "rejection_streak_override_used": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def checkpoint_evidence(
    *,
    checkpoint_role: str,
    ledger_disposition: str,
    candidate_decision: dict[str, Any],
    confidence_decision: dict[str, Any],
    serving_decision: dict[str, Any],
    training_metrics: dict[str, Any],
    ordered_update_keys: list[str],
) -> dict[str, Any]:
    """Build the immutable evidence payload bound into checkpoint identity."""
    metrics = dict(training_metrics)
    validation_fields = {
        key: value
        for key, value in metrics.items()
        if key.startswith("validation_")
        or key.startswith("confidence_calibration_")
    }
    optimizer = {
        "optimizer_steps_this_cycle": metrics.get("optimizer_steps_this_cycle"),
        "parameter_hash_before": metrics.get("parameter_hash_before"),
        "parameter_hash_after": metrics.get("parameter_hash_after"),
        "actual_training_parent_policy_fingerprint": metrics.get(
            "actual_training_parent_policy_fingerprint"
        ),
        "actual_candidate_policy_fingerprint": metrics.get(
            "actual_candidate_policy_fingerprint"
        ),
        "optimizer_parameter_fingerprints_bound": metrics.get(
            "optimizer_parameter_fingerprints_bound"
        ),
        "exact_optimizer_contract_valid": metrics.get(
            "exact_optimizer_contract_valid"
        ),
        "weight_delta_norm": metrics.get("weight_delta_norm"),
        "optimizer_anomaly_counters_complete": metrics.get(
            "optimizer_anomaly_counters_complete"
        ),
        "anomaly_free_optimizer_cycle": metrics.get(
            "anomaly_free_optimizer_cycle"
        ),
        "training_cycle_rolled_back": metrics.get(
            "training_cycle_rolled_back"
        ),
        "ppo_objective_used": metrics.get("ppo_objective_used"),
        "ppo_rows_consumed": metrics.get("ppo_rows_consumed"),
        "ppo_clipped_surrogate_rows": metrics.get(
            "ppo_clipped_surrogate_rows"
        ),
        "ppo_rows_available_but_optimizer_unavailable": metrics.get(
            "ppo_rows_available_but_optimizer_unavailable"
        ),
        "ppo_consumed_update_keys": list(ordered_update_keys),
        "ppo_consumed_update_keys_complete": metrics.get(
            "ppo_consumed_update_keys_complete"
        ),
        "ppo_consumed_update_keys_ordered": metrics.get(
            "ppo_consumed_update_keys_ordered"
        ),
        "ppo_consumed_update_keys_unique": metrics.get(
            "ppo_consumed_update_keys_unique"
        ),
        **{
            field_name: metrics.get(field_name)
            for field_name in OPTIMIZER_ANOMALY_COUNTER_FIELDS
        },
        "ppo_configured_optimizer_epochs_per_consumption_claim": metrics.get(
            "ppo_configured_optimizer_epochs_per_consumption_claim"
        ),
        "ppo_rows_reused_across_optimizer_steps_within_train_call": metrics.get(
            "ppo_rows_reused_across_optimizer_steps_within_train_call"
        ),
        "optimizer_input_lane": metrics.get("learning_update_lane"),
        "outcome_supervised_bootstrap": not ordered_update_keys,
    }
    return {
        "checkpoint_role": checkpoint_role,
        "ledger_disposition": ledger_disposition,
        "candidate_progress_decision": dict(candidate_decision),
        "confidence_promotion_decision": dict(confidence_decision),
        "serving_promotion_decision": dict(serving_decision),
        "optimizer_evidence": optimizer,
        "validation_evidence": validation_fields,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
