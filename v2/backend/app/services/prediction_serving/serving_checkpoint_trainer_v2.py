"""Deterministic paper-only trainer for ServingFeatureABIV2."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.contracts.runtime_v2.contracts import (
    CheckpointBundleV2,
    canonical_sha256,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    fit_temperature,
    normalize_calibration_state,
)
from v2.backend.app.services.prediction_serving.serving_dataset_v2 import ACTION_LABELS
from v2.backend.app.services.prediction_serving.serving_feature_abi_v2 import (
    ORDERED_FEATURE_NAMES,
    feature_abi_sha256,
    feature_builder_sha256,
)

SCHEMA_VERSION = "serving_checkpoint_training_report_v2"
FIXED_RANDOM_SEED = 20260726
OPTIMIZER_STEPS = 400
MIN_STANDARDIZATION_SCALE = 0.01


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parameter_fingerprint(state_dict: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state_dict):
        tensor = state_dict[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(json.dumps(list(tensor.shape)).encode("ascii"))
        digest.update(tensor.numpy().tobytes(order="C"))
    return digest.hexdigest()


def _evaluate(model: Any, x: Any, y: Any) -> dict[str, Any]:
    import torch

    with torch.no_grad():
        logits = model(x)
        probabilities = torch.softmax(logits, dim=1)
    prediction = probabilities.argmax(dim=1)
    counts = Counter(ACTION_LABELS[int(index)] for index in prediction.tolist())
    nonfinite = int((~torch.isfinite(probabilities)).sum().item())
    return {
        "rows": int(y.numel()),
        "accuracy": float((prediction == y).float().mean().item()),
        "directional_rate": float(
            (prediction != ACTION_LABELS.index("hold")).float().mean().item()
        ),
        "prediction_distribution": {action: int(counts[action]) for action in ACTION_LABELS},
        "all_predictions_one_action": len([count for count in counts.values() if count > 0]) == 1,
        "nonfinite_probabilities": nonfinite,
        "prediction_indices": [int(value) for value in prediction.tolist()],
        "probabilities": [[float(item) for item in row] for row in probabilities.tolist()],
    }


def _partition(dataset: dict[str, Any], split: str) -> list[dict[str, Any]]:
    return [row for row in dataset["rows"] if row.get("split") == split]


def train_serving_checkpoint_v2(
    *,
    dataset_path: Path,
    manifest_path: Path,
    output_dir: Path,
) -> tuple[CheckpointBundleV2, dict[str, Any], Path]:
    import torch

    torch.manual_seed(FIXED_RANDOM_SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(FIXED_RANDOM_SEED)
    torch.use_deterministic_algorithms(True)
    dataset = json.loads(dataset_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    if dataset.get("feature_abi_sha256") != feature_abi_sha256():
        raise ValueError("DATASET_FEATURE_ABI_MISMATCH")
    if dataset.get("feature_builder_sha256") != feature_builder_sha256():
        raise ValueError("DATASET_FEATURE_BUILDER_MISMATCH")
    if tuple(dataset.get("ordered_feature_names") or ()) != ORDERED_FEATURE_NAMES:
        raise ValueError("DATASET_FEATURE_ORDER_MISMATCH")
    if manifest.get("dataset_sha256") != dataset.get("dataset_sha256"):
        raise ValueError("DATASET_MANIFEST_BINDING_MISMATCH")
    if any(
        int(manifest.get(field, -1)) != 0
        for field in (
            "duplicate_rows",
            "future_time_rejections",
            "finality_unproven",
            "missing_cost_evidence",
            "missing_label_evidence",
        )
    ):
        raise ValueError("DATASET_ADMISSION_COUNTS_NOT_CLEAN")

    train_rows = _partition(dataset, "train")
    validation_rows = _partition(dataset, "validation")
    holdout_rows = _partition(dataset, "holdout")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def tensors(rows: list[dict[str, Any]]) -> tuple[Any, Any]:
        x = torch.tensor(
            [row["feature_values"] for row in rows], dtype=torch.float32, device=device
        )
        y = torch.tensor(
            [row["target_action_index"] for row in rows], dtype=torch.long, device=device
        )
        return x, y

    x_train_raw, y_train = tensors(train_rows)
    x_validation_raw, y_validation = tensors(validation_rows)
    x_holdout_raw, y_holdout = tensors(holdout_rows)
    mean = x_train_raw.mean(dim=0)
    observed_std = x_train_raw.std(dim=0, unbiased=False)
    training_min = x_train_raw.min(dim=0).values
    training_max = x_train_raw.max(dim=0).values
    scale = torch.clamp(observed_std, min=MIN_STANDARDIZATION_SCALE)
    x_train = (x_train_raw - mean) / scale
    x_validation = (x_validation_raw - mean) / scale
    x_holdout = (x_holdout_raw - mean) / scale

    model = torch.nn.Sequential(
        torch.nn.Linear(len(ORDERED_FEATURE_NAMES), 32),
        torch.nn.ReLU(),
        torch.nn.Linear(32, len(ACTION_LABELS)),
    ).to(device)
    action_counts = torch.bincount(y_train, minlength=len(ACTION_LABELS)).float()
    class_weights = torch.sqrt(action_counts.sum() / torch.clamp(action_counts, min=1.0))
    class_weights = class_weights / class_weights.mean()
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=1e-4)
    loss_fn = torch.nn.CrossEntropyLoss(weight=class_weights)
    final_loss = float("nan")
    model.train()
    for _ in range(OPTIMIZER_STEPS):
        optimizer.zero_grad(set_to_none=True)
        loss = loss_fn(model(x_train), y_train)
        if not torch.isfinite(loss):
            raise ValueError("TRAINING_LOSS_NONFINITE")
        loss.backward()
        optimizer.step()
        final_loss = float(loss.detach().cpu().item())
    model.eval()
    training_evaluation = _evaluate(model, x_train, y_train)
    validation_evaluation = _evaluate(model, x_validation, y_validation)

    # Fit confidence using the purged training partition only.  The calibration
    # target is profitability of the model-selected directional action.
    calibration_probs: list[float] = []
    calibration_outcomes: list[int] = []
    calibration_row_ids: list[str] = []
    calibration_actions: list[str] = []
    for row, _predicted, probs in zip(
        train_rows,
        training_evaluation["prediction_indices"],
        training_evaluation["probabilities"],
        strict=True,
    ):
        # Each authenticated label binding contains the after-cost result for
        # both directional actions.  Fit the shared temperature against both
        # directional heads on every training row, so calibration includes
        # wins and losses for LONG and SHORT without using validation/holdout.
        for action in ("long", "short"):
            action_index = ACTION_LABELS.index(action)
            net_bps = float(row[f"{action}_net_bps"])
            calibration_probs.append(float(probs[action_index]))
            calibration_outcomes.append(int(net_bps > 0.0))
            calibration_row_ids.append(f"{row['row_id']}:{action}")
            calibration_actions.append(action)
    calibration = fit_temperature(
        calibration_probs,
        calibration_outcomes,
        row_ids=calibration_row_ids,
        action_labels=calibration_actions,
        validation_rows_used=0,
    )
    parameter_fingerprint = _parameter_fingerprint(model.state_dict())
    calibration["model_parameter_fingerprint"] = parameter_fingerprint
    calibration = normalize_calibration_state(calibration)
    calibration["probability_semantics_valid"] = calibration.get("fitted") is True
    if calibration.get("fitted") is not True:
        raise ValueError(f"CALIBRATION_REJECTED:{calibration.get('reason')}")

    # The checkpoint and calibration are now frozen.  Holdout is read exactly
    # once for reporting; no parameter or threshold changes follow it.
    holdout_evaluation = _evaluate(model, x_holdout, y_holdout)
    rejection_reasons: list[str] = []
    if validation_evaluation["directional_rate"] == 0.0:
        rejection_reasons.append("VALIDATION_DIRECTIONAL_RATE_ZERO")
    if validation_evaluation["all_predictions_one_action"]:
        rejection_reasons.append("VALIDATION_ALL_PREDICTIONS_ONE_ACTION")
    if validation_evaluation["nonfinite_probabilities"] > 0:
        rejection_reasons.append("VALIDATION_NONFINITE_PROBABILITIES")
    if holdout_evaluation["nonfinite_probabilities"] > 0:
        rejection_reasons.append("HOLDOUT_NONFINITE_PROBABILITIES")
    if rejection_reasons:
        raise ValueError("CHECKPOINT_REJECTED:" + ",".join(rejection_reasons))

    checkpoint_id = (
        "SERVING_ABI_V2_PAPER_"
        + hashlib.sha256(
            f"{manifest['manifest_sha256']}:{parameter_fingerprint}".encode("ascii")
        ).hexdigest()[:24]
    )
    generated_at = _utc_now()
    meta = {
        "checkpoint_id": checkpoint_id,
        "checkpoint_classification": "PAPER_PROVISIONAL",
        "generated_utc": generated_at,
        "manifest_id": manifest["manifest_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "feature_abi_sha256": feature_abi_sha256(),
        "feature_builder_sha256": feature_builder_sha256(),
        "feature_names": list(ORDERED_FEATURE_NAMES),
        "standardize_mean": [float(value) for value in mean.detach().cpu().tolist()],
        "standardize_std": [float(value) for value in scale.detach().cpu().tolist()],
        "observed_training_std": [float(value) for value in observed_std.detach().cpu().tolist()],
        "training_feature_min": [float(value) for value in training_min.detach().cpu().tolist()],
        "training_feature_max": [float(value) for value in training_max.detach().cpu().tolist()],
        "minimum_standardization_scale": MIN_STANDARDIZATION_SCALE,
        "actions": list(ACTION_LABELS),
        "input_dim": len(ORDERED_FEATURE_NAMES),
        "checkpoint_weight_sha256": parameter_fingerprint,
        "model_parameter_fingerprint": parameter_fingerprint,
        "model_id": f"serving_abi_v2_mlp_{parameter_fingerprint[:16]}",
        "confidence_calibration_state": calibration,
        "training_metrics": {
            "optimizer_steps": OPTIMIZER_STEPS,
            "final_loss": final_loss,
            "finite_loss": math.isfinite(final_loss),
            "training": training_evaluation,
            "validation": validation_evaluation,
            "holdout": holdout_evaluation,
        },
        "device": str(device),
        "paper_only": True,
        "checkpoint_promotable": False,
        "live_eligible": False,
        "routes_to_live": False,
        "economic_certification": "PROVISIONAL",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / f"{checkpoint_id}.pt"
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{checkpoint_id}.", suffix=".tmp", dir=output_dir
    )
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        torch.save(
            {
                "meta": meta,
                "state_dict": {k: v.detach().cpu() for k, v in model.state_dict().items()},
            },
            temporary_path,
        )
        temporary_path.replace(checkpoint_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    checkpoint_file_sha256 = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
    metrics = {
        "optimizer_steps": OPTIMIZER_STEPS,
        "final_loss": final_loss,
        "finite_loss": math.isfinite(final_loss),
        "training": training_evaluation,
        "validation": validation_evaluation,
        "holdout": holdout_evaluation,
        "calibration": calibration,
        "required_feature_missing_rate": 0.0,
        "feature_abi_match": True,
        "training_serving_builder_match": True,
        "paper_only": True,
        "live_eligible": False,
        "checkpoint_promotable": False,
        "economic_certification": "PROVISIONAL",
    }
    bundle = CheckpointBundleV2(
        checkpoint_id=checkpoint_id,
        checkpoint_classification="PAPER_PROVISIONAL",
        model_architecture="mlp_29x32x3_softmax_v2",
        model_source=meta["model_id"],
        training_manifest_id=manifest["manifest_id"],
        training_manifest_sha256=manifest["manifest_sha256"],
        feature_abi_sha256=feature_abi_sha256(),
        ordered_feature_names=ORDERED_FEATURE_NAMES,
        input_width=len(ORDERED_FEATURE_NAMES),
        action_labels=ACTION_LABELS,
        weight_file_path=str(checkpoint_path.resolve()),
        weight_sha256=checkpoint_file_sha256,
        model_parameter_fingerprint=parameter_fingerprint,
        calibration_state=calibration,
        calibration_state_sha256=canonical_sha256(calibration),
        training_rows=len(train_rows),
        validation_rows=len(validation_rows),
        holdout_rows=len(holdout_rows),
        optimizer_steps=OPTIMIZER_STEPS,
        training_metrics=metrics,
        generated_at=generated_at,
        serving_feature_builder_sha=feature_builder_sha256(),
        training_feature_builder_sha=feature_builder_sha256(),
    )
    reasons = bundle.validate()
    if reasons:
        raise ValueError("CHECKPOINT_BUNDLE_INVALID:" + ",".join(reasons))
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "checkpoint_id": checkpoint_id,
        "checkpoint_path": str(checkpoint_path.resolve()),
        "checkpoint_file_sha256": checkpoint_file_sha256,
        "model_parameter_fingerprint": parameter_fingerprint,
        "manifest_id": manifest["manifest_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "feature_abi_sha256": feature_abi_sha256(),
        "feature_builder_sha256": feature_builder_sha256(),
        "metrics": metrics,
        "holdout_consumed_once_after_model_and_calibration_frozen": True,
        "activation_eligible": False,
        "activation_block_reason": "CURRENT_SERVING_SMOKE_AND_DISTRIBUTION_PARITY_PENDING",
        "paper_only": True,
        "live_eligible": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    return bundle, report, checkpoint_path


__all__ = ["train_serving_checkpoint_v2"]
