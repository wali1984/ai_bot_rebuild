"""Fail-closed readiness contract for native-trainer learning.

Readiness is intentionally stricter than liveness or inference.  A canonical
``READY`` result is possible only from one current-cycle envelope whose identity
is repeated by every external proof used to validate it.  Historical metrics,
prediction counts, resource files, and service booleans remain useful telemetry,
but are never joined with ``or`` to manufacture learning evidence.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ALLOWED_EFFECTIVE_TRAINER_MODES: tuple[str, ...] = (
    "INFERENCE_ONLY",
    "TRUSTED_REPLAY_TRAINING",
    "ONLINE_PAPER_LEARNING",
    "REPLAY_AND_ONLINE_LEARNING",
    "BLOCKED",
)

CURRENT_CYCLE_ENVELOPE_SCHEMA = "v2_native_trainer_current_cycle_learning_envelope_v1"
GLOBAL_READINESS_ARTIFACT = "online_learning_global_readiness_override.json"
VERIFIED_SERVING_LINEAGE = "VERIFIED_SERVING_POLICY"
SERVING_PROMOTED_DISPOSITION = "SERVING_PROMOTED"


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _strict_nonnegative_int(value: Any) -> int | None:
    parsed = finite_float(value)
    if parsed is None or parsed < 0.0 or not parsed.is_integer():
        return None
    return int(parsed)


def _strict_positive_int(value: Any) -> int | None:
    parsed = _strict_nonnegative_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def _sha256_hex(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _aware_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _current_timestamp(
    value: Any,
    *,
    now_utc: datetime,
    freshness_budget_seconds: float | None,
) -> bool:
    parsed = _aware_utc(value)
    if parsed is None or freshness_budget_seconds is None:
        return False
    age_seconds = (now_utc - parsed).total_seconds()
    return 0.0 <= age_seconds <= freshness_budget_seconds


def _identity_matches(
    evidence: Mapping[str, Any],
    *,
    cycle_id: str,
    process_instance_id: str,
) -> bool:
    return bool(
        evidence.get("cycle_id") == cycle_id
        and evidence.get("process_instance_id") == process_instance_id
    )


def build_learning_readiness(
    *,
    training: Mapping[str, Any] | None = None,
    persistent_runtime: Mapping[str, Any] | None = None,
    latest_training_metrics: Mapping[str, Any] | None = None,
    prediction_rows: int = 0,
    trainer_process_active: bool | None = None,
    trainer_process_evidence: Mapping[str, Any] | None = None,
    cuda_inference_active: bool | None = None,
    current_cycle_learning_envelope: Mapping[str, Any] | None = None,
    runtime_status_evidence: Mapping[str, Any] | None = None,
    heartbeat_evidence: Mapping[str, Any] | None = None,
    verified_serving_checkpoint: Mapping[str, Any] | None = None,
    prediction_publication_evidence: Mapping[str, Any] | None = None,
    resource_evidence: Mapping[str, Any] | None = None,
    parity_evidence: Mapping[str, Any] | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Validate one coherent current-cycle learning evidence envelope.

    The legacy arguments are retained so old callers receive an explicit
    compatibility blocker instead of an exception.  They are deliberately not
    merged into the canonical envelope.  A producer must publish
    ``current_cycle_learning_envelope`` and bind every supporting payload to its
    cycle and process identity before this function can return READY.
    """

    training = as_dict(training)
    persistent_runtime = as_dict(persistent_runtime)
    latest_training_metrics = as_dict(latest_training_metrics)
    envelope = as_dict(current_cycle_learning_envelope)
    embedded_envelope = as_dict(training.get("current_cycle_learning_envelope"))
    if envelope and embedded_envelope and envelope != embedded_envelope:
        envelope_conflict = True
    else:
        envelope_conflict = False
        envelope = envelope or embedded_envelope

    heartbeat = as_dict(heartbeat_evidence)
    runtime_status = as_dict(runtime_status_evidence)
    process_evidence = as_dict(trainer_process_evidence)
    serving = as_dict(verified_serving_checkpoint)
    prediction = as_dict(prediction_publication_evidence)
    resource = as_dict(resource_evidence)
    parity = as_dict(parity_evidence)
    observed_now = now_utc or datetime.now(tz=timezone.utc)
    if observed_now.tzinfo is None or observed_now.utcoffset() is None:
        raise ValueError("learning readiness now_utc must be timezone-aware")
    observed_now = observed_now.astimezone(timezone.utc)

    checks: dict[str, bool] = {}

    def check(name: str, passed: bool) -> None:
        checks[name] = bool(passed)

    check("current_cycle_learning_envelope_present", bool(envelope))
    check("current_cycle_learning_envelope_not_conflicting", not envelope_conflict)
    check(
        "current_cycle_learning_envelope_schema_valid",
        envelope.get("schema_version") == CURRENT_CYCLE_ENVELOPE_SCHEMA,
    )

    cadence_seconds = finite_float(envelope.get("expected_cycle_cadence_seconds"))
    cadence_valid = cadence_seconds is not None and cadence_seconds > 0.0
    freshness_budget_seconds = cadence_seconds * 3.0 if cadence_valid else None
    check("expected_cycle_cadence_positive_finite", cadence_valid)

    cycle_id = str(envelope.get("cycle_id") or "")
    process_instance_id = str(envelope.get("process_instance_id") or "")
    check("cycle_id_nonempty", bool(cycle_id))
    check("process_instance_id_nonempty", bool(process_instance_id))
    check(
        "current_cycle_generated_utc_current",
        _current_timestamp(
            envelope.get("generated_utc"),
            now_utc=observed_now,
            freshness_budget_seconds=freshness_budget_seconds,
        ),
    )
    check("actual_trainer_process_active", trainer_process_active is True)
    process_id = _strict_positive_int(process_evidence.get("process_id"))
    check("trainer_process_evidence_present", bool(process_evidence))
    check("trainer_service_active_current", process_evidence.get("service_active") is True)
    check("trainer_process_id_positive", process_id is not None)
    check(
        "trainer_process_instance_identity_bound",
        process_evidence.get("process_instance_id") == process_instance_id,
    )
    check(
        "trainer_process_service_unit_bound",
        process_evidence.get("service_unit")
        in {
            "ai-bot-v2-native-cuda-trainer-persistent.service",
            "ai-bot-v2-native-rl-masa-ppo-cuda-trainer-loop.service",
        },
    )
    check("actual_cuda_probe_active", cuda_inference_active is True)

    check("runtime_status_evidence_present", bool(runtime_status))
    check(
        "runtime_status_envelope_exactly_bound",
        as_dict(runtime_status.get("current_cycle_learning_envelope")) == envelope
        if envelope
        else False,
    )
    check(
        "runtime_status_identity_bound",
        _identity_matches(
            runtime_status,
            cycle_id=cycle_id,
            process_instance_id=process_instance_id,
        ),
    )
    check(
        "runtime_status_cadence_bound",
        finite_float(runtime_status.get("expected_cycle_cadence_seconds"))
        == cadence_seconds
        if cadence_valid
        else False,
    )
    check(
        "runtime_status_generated_utc_current",
        _current_timestamp(
            runtime_status.get("generated_utc"),
            now_utc=observed_now,
            freshness_budget_seconds=freshness_budget_seconds,
        ),
    )
    runtime_status_expiry = _aware_utc(runtime_status.get("status_payload_expires_at"))
    check(
        "runtime_status_not_expired",
        bool(
            runtime_status_expiry is not None
            and runtime_status_expiry >= observed_now
        ),
    )
    check(
        "runtime_status_publication_active",
        runtime_status.get("status_publication_status") == "ACTIVE",
    )
    check(
        "runtime_status_readiness_consistent",
        runtime_status.get("runtime_readiness_status") == "READY"
        and runtime_status.get("trainer_learning_ready") is True,
    )

    # Heartbeat evidence is a separate source, so it must repeat the exact cycle
    # and process identity before it can support the envelope.
    check("heartbeat_evidence_present", bool(heartbeat))
    check(
        "heartbeat_identity_bound",
        _identity_matches(
            heartbeat,
            cycle_id=cycle_id,
            process_instance_id=process_instance_id,
        ),
    )
    check(
        "heartbeat_cadence_bound",
        finite_float(heartbeat.get("expected_cycle_cadence_seconds")) == cadence_seconds
        if cadence_valid
        else False,
    )
    check(
        "heartbeat_generated_utc_current",
        _current_timestamp(
            heartbeat.get("generated_utc"),
            now_utc=observed_now,
            freshness_budget_seconds=freshness_budget_seconds,
        ),
    )
    heartbeat_expiry = _aware_utc(heartbeat.get("expires_at"))
    check(
        "heartbeat_not_expired",
        bool(heartbeat_expiry is not None and heartbeat_expiry >= observed_now),
    )

    trusted_rows_loaded = _strict_nonnegative_int(envelope.get("trusted_rows_loaded"))
    trusted_replay_rows_loaded = _strict_nonnegative_int(
        envelope.get("trusted_replay_rows_loaded")
    )
    feedback_rows_entered_batch = _strict_nonnegative_int(
        envelope.get("feedback_rows_entered_batch")
    )
    optimizer_steps_this_cycle = _strict_positive_int(
        envelope.get("optimizer_steps_this_cycle")
    )
    optimizer_steps_total = _strict_positive_int(envelope.get("optimizer_steps_total"))
    optimizer_steps_last_hour = _strict_positive_int(
        envelope.get("optimizer_steps_last_hour")
    )
    check("trusted_rows_loaded_gt_0", bool(trusted_rows_loaded and trusted_rows_loaded > 0))
    check("optimizer_steps_this_cycle_gt_0", optimizer_steps_this_cycle is not None)
    check("optimizer_steps_total_positive_finite_integer", optimizer_steps_total is not None)
    check("optimizer_steps_last_hour_positive_finite_integer", optimizer_steps_last_hour is not None)

    parameter_hash_before = envelope.get("parameter_hash_before")
    parameter_hash_after = envelope.get("parameter_hash_after")
    parent_fingerprint = envelope.get("parent_policy_fingerprint")
    candidate_fingerprint = envelope.get("candidate_policy_fingerprint")
    check("parameter_hash_before_sha256", _sha256_hex(parameter_hash_before))
    check("parameter_hash_after_sha256", _sha256_hex(parameter_hash_after))
    check("parent_policy_fingerprint_sha256", _sha256_hex(parent_fingerprint))
    check("candidate_policy_fingerprint_sha256", _sha256_hex(candidate_fingerprint))
    check(
        "optimizer_parent_fingerprint_bound",
        bool(parameter_hash_before == parent_fingerprint),
    )
    check(
        "optimizer_candidate_fingerprint_bound",
        bool(parameter_hash_after == candidate_fingerprint),
    )
    check(
        "parameter_hash_after_differs",
        bool(parameter_hash_before and parameter_hash_after and parameter_hash_before != parameter_hash_after),
    )
    weight_delta_norm = finite_float(envelope.get("weight_delta_norm"))
    check("weight_delta_norm_positive_finite", bool(weight_delta_norm and weight_delta_norm > 0.0))

    checkpoint_id = str(envelope.get("checkpoint_id") or "")
    parent_checkpoint_id = str(envelope.get("parent_checkpoint_id") or "")
    checkpoint_hash = envelope.get("checkpoint_hash")
    check("checkpoint_id_nonempty", bool(checkpoint_id))
    check("parent_checkpoint_id_nonempty", bool(parent_checkpoint_id))
    check("checkpoint_hash_sha256", _sha256_hex(checkpoint_hash))
    check("checkpoint_weight_blob_written_true", envelope.get("checkpoint_weight_blob_written") is True)
    check("checkpoint_reload_verified_true", envelope.get("checkpoint_reload_verified") is True)
    check("verified_serving_claim_true", envelope.get("verified_serving") is True)
    check(
        "runtime_status_checkpoint_bound",
        runtime_status.get("checkpoint_id") == checkpoint_id,
    )
    check(
        "runtime_status_candidate_fingerprint_bound",
        runtime_status.get("candidate_policy_fingerprint") == candidate_fingerprint,
    )

    check("manager_verified_serving_evidence_present", bool(serving))
    check("manager_checkpoint_artifact_verified", serving.get("checkpoint_artifact_verified") is True)
    check("manager_checkpoint_causal_order_verified", serving.get("causal_order_verified") is True)
    check("manager_checkpoint_lineage_verified_serving", serving.get("lineage_kind") == VERIFIED_SERVING_LINEAGE)
    check("manager_checkpoint_id_bound", serving.get("checkpoint_id") == checkpoint_id)
    check("manager_parent_checkpoint_id_bound", serving.get("parent_checkpoint_id") == parent_checkpoint_id)
    check("manager_candidate_fingerprint_bound", serving.get("model_parameter_fingerprint") == candidate_fingerprint)
    check("manager_parent_fingerprint_bound", serving.get("parent_policy_fingerprint") == parent_fingerprint)
    check("manager_checkpoint_hash_bound", serving.get("weight_file_sha256") == checkpoint_hash)
    check("manager_exact_optimizer_contract_durable", serving.get("exact_optimizer_contract_durable") is True)
    check("manager_serving_disposition_verified", serving.get("ledger_disposition") == SERVING_PROMOTED_DISPOSITION)
    check(
        "manager_checkpoint_generated_utc_bound",
        serving.get("generated_utc") == envelope.get("checkpoint_generated_utc"),
    )
    check(
        "manager_checkpoint_generated_utc_current",
        _current_timestamp(
            serving.get("generated_utc"),
            now_utc=observed_now,
            freshness_budget_seconds=freshness_budget_seconds,
        ),
    )

    optimizer_contract = as_dict(envelope.get("exact_optimizer_contract"))
    check("exact_optimizer_contract_present", bool(optimizer_contract))
    check("exact_optimizer_contract_valid", optimizer_contract.get("valid") is True)
    check("exact_optimizer_ppo_objective_used", optimizer_contract.get("ppo_objective_used") is True)
    check(
        "exact_optimizer_fingerprints_bound",
        optimizer_contract.get("optimizer_parameter_fingerprints_bound") is True,
    )
    check(
        "optimizer_disposition_serving_promoted",
        optimizer_contract.get("ledger_disposition") == SERVING_PROMOTED_DISPOSITION,
    )
    check(
        "optimizer_contract_checkpoint_bound",
        optimizer_contract.get("checkpoint_id") == checkpoint_id,
    )

    # Prediction, resource, and parity proofs must be complete, current, and
    # repeat the same identity.  Counts alone never prove publication.
    check("prediction_publication_evidence_present", bool(prediction))
    check(
        "prediction_publication_identity_bound",
        _identity_matches(prediction, cycle_id=cycle_id, process_instance_id=process_instance_id),
    )
    check("prediction_publication_checkpoint_bound", prediction.get("checkpoint_id") == checkpoint_id)
    check(
        "prediction_publication_fingerprint_bound",
        prediction.get("candidate_policy_fingerprint") == candidate_fingerprint,
    )
    check("prediction_publication_complete", prediction.get("publication_complete") is True)
    expected_predictions = _strict_positive_int(prediction.get("expected_prediction_count"))
    published_predictions = _strict_positive_int(prediction.get("prediction_rows_count"))
    current_predictions = _strict_positive_int(prediction.get("current_prediction_count"))
    missing_predictions = _strict_nonnegative_int(prediction.get("missing_prediction_rows_count"))
    stale_predictions = _strict_nonnegative_int(prediction.get("stale_prediction_rows_count"))
    lineages_published = _strict_positive_int(prediction.get("lineages_published"))
    published_prediction_rows = [
        as_dict(row) for row in _as_list(prediction.get("prediction_rows"))
    ]
    rows_identity_bound = bool(
        published_prediction_rows
        and all(
            row.get("cycle_id") == cycle_id
            and row.get("process_instance_id") == process_instance_id
            and row.get("checkpoint_id") == checkpoint_id
            and row.get("candidate_policy_fingerprint") == candidate_fingerprint
            and row.get("status") == "PRESENT_CURRENT"
            for row in published_prediction_rows
        )
    )
    check(
        "prediction_grid_complete",
        bool(
            expected_predictions is not None
            and published_predictions == expected_predictions
            and current_predictions == expected_predictions
            and lineages_published == expected_predictions
            and len(published_prediction_rows) == expected_predictions
            and rows_identity_bound
            and missing_predictions == 0
            and stale_predictions == 0
        ),
    )
    check(
        "prediction_publication_generated_utc_current",
        _current_timestamp(
            prediction.get("generated_utc"),
            now_utc=observed_now,
            freshness_budget_seconds=freshness_budget_seconds,
        ),
    )

    check("resource_evidence_present", bool(resource))
    check(
        "resource_evidence_identity_bound",
        _identity_matches(resource, cycle_id=cycle_id, process_instance_id=process_instance_id),
    )
    check("resource_cuda_available_true", resource.get("cuda_available") is True)
    check("resource_cuda_active_true", resource.get("cuda_active") is True)
    check(
        "resource_generated_utc_current",
        _current_timestamp(
            resource.get("generated_utc"),
            now_utc=observed_now,
            freshness_budget_seconds=freshness_budget_seconds,
        ),
    )

    check("parity_evidence_present", bool(parity))
    check(
        "parity_evidence_identity_bound",
        _identity_matches(parity, cycle_id=cycle_id, process_instance_id=process_instance_id),
    )
    check("parity_complete_true", parity.get("parity_complete") is True)
    check("parity_required_missing_zero", parity.get("required_missing_parity_methods") == 0)
    check("parity_status_verified", parity.get("status") == "FULL_FUNCTION_PARITY_VERIFIED")
    check(
        "parity_generated_utc_current",
        _current_timestamp(
            parity.get("generated_utc"),
            now_utc=observed_now,
            freshness_budget_seconds=freshness_budget_seconds,
        ),
    )

    ledger = as_dict(envelope.get("ppo_ledger_integrity"))
    archive = as_dict(envelope.get("receipt_archive_sync_status"))
    check("ppo_ledger_integrity_present", bool(ledger))
    check("ppo_ledger_integrity_verified", ledger.get("integrity_verified") is True)
    check("receipt_archive_sync_status_present", bool(archive))
    check("receipt_archive_sync_integrity_verified", archive.get("archive_sync_integrity_verified") is True)
    check(
        "receipt_archive_terminal_attempts_fully_synced",
        _strict_nonnegative_int(archive.get("unsynced_terminal_attempts")) == 0,
    )
    check("receipt_archive_sync_sequence_valid", _strict_nonnegative_int(archive.get("sync_sequence")) is not None)
    check("receipt_archive_sync_chain_hash_valid", _sha256_hex(archive.get("sync_chain_hash")))
    check("receipt_archive_sync_state_digest_valid", _sha256_hex(archive.get("sync_state_digest")))

    status_publication = as_dict(envelope.get("status_publication"))
    check("status_publication_complete", status_publication.get("publication_complete") is True)
    check("status_publication_cycle_bound", status_publication.get("cycle_id") == cycle_id)
    check("status_publication_process_bound", status_publication.get("process_instance_id") == process_instance_id)
    check("trainer_process_status_consistent", envelope.get("trainer_process_status") == "ACTIVE_CURRENT_CYCLE")
    check("cuda_inference_status_consistent", envelope.get("cuda_inference_status") == "ACTIVE")
    check("prediction_publication_status_consistent", envelope.get("prediction_publication_status") == "ACTIVE")
    check("online_learning_status_consistent", envelope.get("online_learning_status") == "WEIGHTS_UPDATING")
    check("runtime_readiness_status_consistent", envelope.get("runtime_readiness_status") == "READY")
    check("paper_shadow_only_true", envelope.get("paper_only") is True)
    check("routes_to_live_false", envelope.get("routes_to_live") is False)
    check("places_real_order_false", envelope.get("places_real_order") is False)

    trainer_learning_ready = all(checks.values())
    blocking_reasons = [name for name, passed in checks.items() if not passed]

    replay_active = bool(trainer_learning_ready and trusted_replay_rows_loaded and trusted_replay_rows_loaded > 0)
    online_active = bool(trainer_learning_ready and feedback_rows_entered_batch and feedback_rows_entered_batch > 0)
    if trainer_learning_ready and replay_active and online_active:
        effective_mode = "REPLAY_AND_ONLINE_LEARNING"
    elif trainer_learning_ready and replay_active:
        effective_mode = "TRUSTED_REPLAY_TRAINING"
    elif trainer_learning_ready and online_active:
        effective_mode = "ONLINE_PAPER_LEARNING"
    elif trainer_learning_ready:
        effective_mode = "TRUSTED_REPLAY_TRAINING"
    else:
        effective_mode = "INFERENCE_ONLY"

    last_successful_weight_update_at = envelope.get("last_successful_weight_update_at")
    check_last_update = _current_timestamp(
        last_successful_weight_update_at,
        now_utc=observed_now,
        freshness_budget_seconds=freshness_budget_seconds,
    )
    # This check is evaluated last so the returned reason is explicit while the
    # rest of the identity contract remains inspectable.
    checks["last_successful_weight_update_current"] = check_last_update
    if not check_last_update and "last_successful_weight_update_current" not in blocking_reasons:
        blocking_reasons.append("last_successful_weight_update_current")
        trainer_learning_ready = False
        replay_active = False
        online_active = False
        effective_mode = "INFERENCE_ONLY"

    return {
        "schema_version": "online_learning_global_readiness_override_v2",
        "generated_utc": observed_now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "canonical_readiness_status": "READY" if trainer_learning_ready else "BLOCKED",
        "trainer_learning_ready": trainer_learning_ready,
        "trainer_process_status": "ACTIVE" if trainer_process_active is True else "INACTIVE",
        "cuda_inference_status": (
            "ACTIVE" if cuda_inference_active is True else "BLOCKED_NO_CURRENT_CUDA_PROBE_EVIDENCE"
        ),
        "prediction_publication_status": (
            "ACTIVE"
            if checks.get("prediction_publication_complete")
            and checks.get("prediction_grid_complete")
            and checks.get("prediction_publication_identity_bound")
            and checks.get("prediction_publication_generated_utc_current")
            else "BLOCKED_NO_CURRENT_COMPLETE_PREDICTION_PUBLICATION"
        ),
        "offline_replay_learning_status": (
            "ACTIVE" if replay_active else "BLOCKED_NO_CURRENT_CYCLE_TRUSTED_REPLAY_WEIGHT_UPDATE"
        ),
        "online_paper_learning_status": (
            "ACTIVE" if online_active else "BLOCKED_NO_CURRENT_CYCLE_CONSUMABLE_PAPER_FEEDBACK"
        ),
        "online_learning_status": (
            "WEIGHTS_UPDATING" if trainer_learning_ready else "BLOCKED_NO_COHERENT_CURRENT_CYCLE_LEARNING_ENVELOPE"
        ),
        "effective_trainer_mode": effective_mode,
        "allowed_effective_trainer_modes": list(ALLOWED_EFFECTIVE_TRAINER_MODES),
        "cycle_id": cycle_id or None,
        "process_instance_id": process_instance_id or None,
        "expected_cycle_cadence_seconds": cadence_seconds,
        "freshness_budget_seconds": freshness_budget_seconds,
        "last_successful_weight_update_at": (
            last_successful_weight_update_at if trainer_learning_ready else None
        ),
        "trusted_rows_loaded": trusted_rows_loaded or 0,
        "trusted_replay_rows_loaded": trusted_replay_rows_loaded or 0,
        "feedback_rows_entered_batch": feedback_rows_entered_batch or 0,
        "optimizer_steps_this_cycle": optimizer_steps_this_cycle or 0,
        "optimizer_steps_last_hour": optimizer_steps_last_hour or 0,
        "optimizer_steps_total": optimizer_steps_total or 0,
        "parameter_hash_before": parameter_hash_before,
        "parameter_hash_after": parameter_hash_after,
        "weight_delta_norm": weight_delta_norm or 0.0,
        "checkpoint_weight_blob_written": envelope.get("checkpoint_weight_blob_written") is True,
        "checkpoint_path": envelope.get("checkpoint_path"),
        "checkpoint_id": checkpoint_id or None,
        "parent_checkpoint_id": parent_checkpoint_id or None,
        "parent_policy_fingerprint": parent_fingerprint,
        "candidate_policy_fingerprint": candidate_fingerprint,
        "checkpoint_hash": checkpoint_hash,
        "checkpoint_reload_verified": envelope.get("checkpoint_reload_verified") is True,
        "requirement_checks": checks,
        "readiness_blocking_reasons": blocking_reasons,
        "legacy_unbound_evidence_observed": bool(
            training or persistent_runtime or latest_training_metrics or prediction_rows
        ),
        "unbound_legacy_evidence_used_for_readiness": False,
    }


def write_learning_readiness_artifact(path: Path, readiness: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(dict(readiness), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
