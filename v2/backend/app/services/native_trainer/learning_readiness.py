"""Hard readiness contract for native trainer learning.

The helpers in this module intentionally separate process liveness, CUDA
inference, prediction publication, and actual weight learning. A live process
or a current prediction grid is not evidence that the model learned.
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

GLOBAL_READINESS_ARTIFACT = "online_learning_global_readiness_override.json"


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _first_number(*values: Any) -> float:
    for value in values:
        parsed = finite_float(value)
        if parsed is not None:
            return parsed
    return 0.0


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _bool_any(*values: Any) -> bool:
    return any(bool(value) for value in values)


def build_learning_readiness(
    *,
    training: Mapping[str, Any] | None = None,
    persistent_runtime: Mapping[str, Any] | None = None,
    latest_training_metrics: Mapping[str, Any] | None = None,
    prediction_rows: int = 0,
) -> dict[str, Any]:
    training = as_dict(training)
    persistent_runtime = as_dict(persistent_runtime)
    latest_training_metrics = as_dict(latest_training_metrics)
    metrics = as_dict(latest_training_metrics.get("metrics")) or as_dict(training.get("metrics"))

    trusted_rows_loaded = int(
        _first_number(
            metrics.get("trusted_rows_loaded"),
            training.get("trusted_rows_loaded"),
            training.get("train_rows"),
            persistent_runtime.get("trusted_rows_loaded"),
        )
    )
    trusted_replay_rows_loaded = int(
        _first_number(
            metrics.get("trusted_replay_rows_loaded"),
            training.get("trusted_replay_rows_loaded"),
            persistent_runtime.get("trusted_replay_rows_loaded"),
        )
    )
    feedback_rows_entered_batch = int(
        _first_number(
            metrics.get("feedback_rows_entered_batch"),
            metrics.get("closed_trade_feedback_rows_loaded"),
            training.get("feedback_rows_entered_batch"),
            persistent_runtime.get("feedback_rows_entered_batch"),
        )
    )
    optimizer_steps_this_cycle = int(
        _first_number(
            metrics.get("optimizer_steps_this_cycle"),
            training.get("optimizer_steps_this_cycle"),
            persistent_runtime.get("optimizer_steps_this_cycle"),
        )
    )
    optimizer_steps_total = int(
        _first_number(
            metrics.get("optimizer_steps_total"),
            training.get("optimizer_steps_total"),
            persistent_runtime.get("optimizer_steps_total"),
            optimizer_steps_this_cycle,
        )
    )
    optimizer_steps_last_hour = int(
        _first_number(
            metrics.get("optimizer_steps_last_hour"),
            training.get("optimizer_steps_last_hour"),
            persistent_runtime.get("optimizer_steps_last_hour"),
            persistent_runtime.get("training_steps_last_hour"),
        )
    )

    parameter_hash_before = _first_present(
        metrics.get("parameter_hash_before"),
        training.get("parameter_hash_before"),
        persistent_runtime.get("parameter_hash_before"),
    )
    parameter_hash_after = _first_present(
        metrics.get("parameter_hash_after"),
        training.get("parameter_hash_after"),
        persistent_runtime.get("parameter_hash_after"),
    )
    weight_delta_norm = _first_number(
        metrics.get("weight_delta_norm"),
        training.get("weight_delta_norm"),
        persistent_runtime.get("weight_delta_norm"),
    )
    checkpoint_weight_blob_written = _bool_any(
        metrics.get("checkpoint_weight_blob_written"),
        training.get("checkpoint_weight_blob_written"),
        latest_training_metrics.get("checkpoint_weight_blob_written"),
        persistent_runtime.get("checkpoint_weight_blob_written"),
    )
    checkpoint_reload_verified = _bool_any(
        metrics.get("checkpoint_reload_verified"),
        training.get("checkpoint_reload_verified"),
        latest_training_metrics.get("checkpoint_reload_verified"),
        persistent_runtime.get("checkpoint_reload_verified"),
    )
    checkpoint_path = _first_present(
        metrics.get("checkpoint_path"),
        training.get("checkpoint_path"),
        latest_training_metrics.get("checkpoint_path"),
        persistent_runtime.get("checkpoint_path"),
    )
    checkpoint_hash = _first_present(
        metrics.get("checkpoint_hash"),
        training.get("checkpoint_hash"),
        latest_training_metrics.get("checkpoint_hash"),
        persistent_runtime.get("checkpoint_hash"),
    )
    last_successful_weight_update_at = _first_present(
        metrics.get("last_successful_weight_update_at"),
        training.get("last_successful_weight_update_at"),
        persistent_runtime.get("last_successful_weight_update_at"),
    )

    requirement_checks = {
        "trusted_rows_loaded_gt_0": trusted_rows_loaded > 0,
        "optimizer_steps_last_hour_gt_0": optimizer_steps_last_hour > 0,
        "parameter_hash_before_non_null": bool(parameter_hash_before),
        "parameter_hash_after_differs": bool(
            parameter_hash_before
            and parameter_hash_after
            and parameter_hash_before != parameter_hash_after
        ),
        "checkpoint_weight_blob_written_true": checkpoint_weight_blob_written is True,
        "checkpoint_reload_verified_true": checkpoint_reload_verified is True,
    }
    trainer_learning_ready = all(requirement_checks.values())
    blocking_reasons = [
        name
        for name, passed in requirement_checks.items()
        if not passed
    ]

    replay_active = bool(trainer_learning_ready and trusted_replay_rows_loaded > 0)
    online_active = bool(trainer_learning_ready and feedback_rows_entered_batch > 0)
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

    offline_replay_learning_status = (
        "ACTIVE" if replay_active else "BLOCKED_NO_TRUSTED_REPLAY_WEIGHT_UPDATE"
    )
    online_paper_learning_status = (
        "ACTIVE" if online_active else "BLOCKED_NO_CONSUMABLE_PAPER_FEEDBACK"
    )
    online_learning_status = (
        "WEIGHTS_UPDATING"
        if trainer_learning_ready
        else (
            "BLOCKED_NO_TRUSTED_FEEDBACK"
            if trusted_rows_loaded <= 0
            else "BLOCKED_NO_DURABLE_WEIGHT_UPDATE"
        )
    )

    return {
        "schema_version": "online_learning_global_readiness_override_v1",
        "generated_utc": utc_now(),
        "trainer_learning_ready": trainer_learning_ready,
        "trainer_process_status": "ACTIVE",
        "cuda_inference_status": "ACTIVE",
        "prediction_publication_status": "ACTIVE" if int(prediction_rows) > 0 else "BLOCKED_NO_PREDICTIONS",
        "offline_replay_learning_status": offline_replay_learning_status,
        "online_paper_learning_status": online_paper_learning_status,
        "online_learning_status": online_learning_status,
        "effective_trainer_mode": effective_mode,
        "allowed_effective_trainer_modes": list(ALLOWED_EFFECTIVE_TRAINER_MODES),
        "last_successful_weight_update_at": (
            last_successful_weight_update_at if trainer_learning_ready else None
        ),
        "trusted_rows_loaded": trusted_rows_loaded,
        "trusted_replay_rows_loaded": trusted_replay_rows_loaded,
        "feedback_rows_entered_batch": feedback_rows_entered_batch,
        "optimizer_steps_this_cycle": optimizer_steps_this_cycle,
        "optimizer_steps_last_hour": optimizer_steps_last_hour,
        "optimizer_steps_total": optimizer_steps_total,
        "parameter_hash_before": parameter_hash_before,
        "parameter_hash_after": parameter_hash_after,
        "weight_delta_norm": weight_delta_norm,
        "checkpoint_weight_blob_written": checkpoint_weight_blob_written,
        "checkpoint_path": checkpoint_path,
        "checkpoint_hash": checkpoint_hash,
        "checkpoint_reload_verified": checkpoint_reload_verified,
        "requirement_checks": requirement_checks,
        "readiness_blocking_reasons": blocking_reasons,
    }


def write_learning_readiness_artifact(path: Path, readiness: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(dict(readiness), indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
