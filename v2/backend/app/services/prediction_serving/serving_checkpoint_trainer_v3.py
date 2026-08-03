"""Paper-only challenger trainer with explicit after-cost profitability confidence."""

from __future__ import annotations

import hashlib
import io
import math
import os
import stat
import tempfile
from collections import Counter
from datetime import datetime
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
from v2.backend.app.services.prediction_serving.serving_checkpoint_trainer_v2 import (
    FIXED_RANDOM_SEED,
    MIN_EDGE_TARGET_SCALE_BPS,
    MIN_STANDARDIZATION_SCALE,
    OPTIMIZER_STEPS,
    _parameter_fingerprint,
    _partition,
)
from v2.backend.app.services.prediction_serving.serving_dataset_v2 import ACTION_LABELS
from v2.backend.app.services.prediction_serving.serving_feature_abi_v2 import (
    ORDERED_FEATURE_NAMES,
    feature_abi_sha256,
    feature_builder_sha256,
)
from v2.backend.app.services.prediction_serving.serving_model_v4 import (
    DIRECTIONAL_ACTIONS,
    MODEL_ARCHITECTURE,
    build_serving_model_v4,
)
from v2.backend.app.services.prediction_serving.serving_training_artifact_v2 import (
    load_validated_training_artifacts,
)

SCHEMA_VERSION = "serving_checkpoint_training_report_v3"
EDGE_REGRESSION_LOSS_WEIGHT = 0.25
PROFITABILITY_LOSS_WEIGHT = 0.50
MIN_EFFECTIVE_INDEPENDENT_TRAINING_GROUPS = 80.0


def _read_regular_bytes(path: Path, field: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ValueError(f"{field}:REGULAR_FILE_REQUIRED") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"{field}:REGULAR_FILE_REQUIRED")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _prepare_output_directory(path: Path) -> None:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        raise ValueError("OUTPUT_DIR_ABSOLUTE_WITHOUT_TRAVERSAL_REQUIRED")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("OUTPUT_DIR_SAFE_DIRECTORY_REQUIRED")


def _publish_immutable_checkpoint(*, checkpoint_bytes: bytes, target_path: Path) -> None:
    """Publish once, or accept only a byte-identical idempotent replay."""

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.", suffix=".tmp", dir=target_path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        owned_descriptor = descriptor
        descriptor = -1
        with os.fdopen(owned_descriptor, "wb") as handle:
            handle.write(checkpoint_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, target_path, follow_symlinks=False)
        except FileExistsError as exc:
            existing_bytes = _read_regular_bytes(target_path, "checkpoint_path")
            if existing_bytes != checkpoint_bytes:
                raise ValueError(
                    "CHECKPOINT_ID_COLLISION_WITH_DIFFERENT_BYTES"
                ) from exc
        _fsync_directory(target_path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def _decision_minute(value: Any) -> str:
    text = str(value or "")
    if len(text) < 16 or "T" not in text:
        raise ValueError("TRAINING_DECISION_TIME_MALFORMED")
    return text[:16]


def decision_group_balance(
    rows: list[dict[str, Any]],
) -> tuple[list[float], dict[str, Any]]:
    """Give each decision-minute group equal aggregate training influence."""

    groups = [_decision_minute(row.get("decision_time")) for row in rows]
    counts = Counter(groups)
    raw_weights = [1.0 / counts[group] for group in groups]
    mean_weight = math.fsum(raw_weights) / len(raw_weights)
    weights = [weight / mean_weight for weight in raw_weights]
    nominal = len(rows)
    sum_group_sizes_squared = math.fsum(count * count for count in counts.values())
    unbalanced_group_kish = (
        (nominal * nominal) / sum_group_sizes_squared
        if sum_group_sizes_squared > 0.0
        else 0.0
    )
    weight_sum = math.fsum(weights)
    balanced_row_kish = (
        (weight_sum * weight_sum) / math.fsum(weight * weight for weight in weights)
        if weights
        else 0.0
    )
    # Independence cannot exceed the number of distinct decision clocks even
    # when inverse-group weighting gives a larger row-level Kish ESS.  The old
    # unbalanced metric is retained for drift diagnostics, but it must not gate
    # a loss that actually consumes the balanced weights above.
    effective_independent_groups = min(float(len(counts)), balanced_row_kish)
    report = {
        "schema_version": "decision_group_balance_v2",
        "grouping_semantics": "UTC_DECISION_TIME_MINUTE",
        "nominal_rows": nominal,
        "unique_decision_groups": len(counts),
        "unbalanced_cross_sectional_effective_groups_kish": float(
            unbalanced_group_kish
        ),
        "balanced_row_effective_sample_size_kish": float(balanced_row_kish),
        "effective_independent_training_groups": float(
            effective_independent_groups
        ),
        # Compatibility projection: the field now names the effective sample
        # actually consumed by the balanced loss, not a pre-weight diagnostic.
        "effective_independent_sample_size_kish": float(
            effective_independent_groups
        ),
        "effective_to_nominal_ratio": (
            float(effective_independent_groups / nominal) if nominal else 0.0
        ),
        "maximum_rows_per_group": max(counts.values(), default=0),
        "group_aggregate_weight_equalized": True,
        "group_counts_sha256": canonical_sha256(dict(sorted(counts.items()))),
    }
    return weights, report


def _calibrated_probability(probability: float, temperature: float) -> float:
    bounded = min(1.0 - 1e-12, max(1e-12, float(probability)))
    logit = math.log(bounded / (1.0 - bounded)) / float(temperature)
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, logit))))


def _evaluate(
    model: Any,
    x: Any,
    y: Any,
    edge_targets_bps: Any,
    profitability_targets: Any,
    edge_mean_bps: Any,
    edge_scale_bps: Any,
    *,
    confidence_temperature: float | None = None,
) -> dict[str, Any]:
    import torch

    with torch.no_grad():
        logits, edge_standardized, profitability_logits = model(x)
        action_probabilities = torch.softmax(logits, dim=1)
        edge_predictions_bps = edge_standardized * edge_scale_bps + edge_mean_bps
        profitability_probabilities = torch.sigmoid(profitability_logits)
    prediction = action_probabilities.argmax(dim=1)
    counts = Counter(ACTION_LABELS[int(index)] for index in prediction.tolist())
    edge_error = edge_predictions_bps - edge_targets_bps
    raw_brier = float(
        ((profitability_probabilities - profitability_targets) ** 2).mean().item()
    )
    calibrated_profitability = None
    calibrated_brier = None
    if confidence_temperature is not None:
        calibrated_profitability = [
            [
                _calibrated_probability(value, confidence_temperature)
                for value in row
            ]
            for row in profitability_probabilities.tolist()
        ]
        target_rows = profitability_targets.tolist()
        calibrated_brier = math.fsum(
            (probability - float(target)) ** 2
            for probability_row, target_row in zip(
                calibrated_profitability, target_rows, strict=True
            )
            for probability, target in zip(
                probability_row, target_row, strict=True
            )
        ) / (len(target_rows) * len(DIRECTIONAL_ACTIONS))
    selected_edges: list[float] = []
    selected_profitabilities: list[float] = []
    for prediction_index, edge_row, probability_row in zip(
        prediction.tolist(),
        edge_predictions_bps.tolist(),
        (
            calibrated_profitability
            if calibrated_profitability is not None
            else profitability_probabilities.tolist()
        ),
        strict=True,
    ):
        action = ACTION_LABELS[int(prediction_index)]
        if action in DIRECTIONAL_ACTIONS:
            directional_index = DIRECTIONAL_ACTIONS.index(action)
            selected_edges.append(float(edge_row[directional_index]))
            selected_profitabilities.append(float(probability_row[directional_index]))
    return {
        "rows": int(y.numel()),
        "accuracy": float((prediction == y).float().mean().item()),
        "directional_rate": float(
            (prediction != ACTION_LABELS.index("hold")).float().mean().item()
        ),
        "prediction_distribution": {
            action: int(counts[action]) for action in ACTION_LABELS
        },
        "all_predictions_one_action": len(
            [count for count in counts.values() if count > 0]
        )
        == 1,
        "nonfinite_probabilities": int(
            (~torch.isfinite(action_probabilities)).sum().item()
        ),
        "nonfinite_directional_net_edges": int(
            (~torch.isfinite(edge_predictions_bps)).sum().item()
        ),
        "nonfinite_profitability_probabilities": int(
            (~torch.isfinite(profitability_probabilities)).sum().item()
        ),
        "directional_net_edge_mae_bps": float(edge_error.abs().mean().item()),
        "directional_net_edge_rmse_bps": float(
            torch.sqrt((edge_error * edge_error).mean()).item()
        ),
        "profitability_raw_brier": raw_brier,
        "profitability_calibrated_brier": calibrated_brier,
        "selected_directional_positive_edge_rate": (
            sum(value > 0.0 for value in selected_edges) / len(selected_edges)
            if selected_edges
            else 0.0
        ),
        "selected_directional_profitability_mean": (
            math.fsum(selected_profitabilities) / len(selected_profitabilities)
            if selected_profitabilities
            else None
        ),
        "selected_directional_net_edges_bps": selected_edges,
        "prediction_indices": [int(value) for value in prediction.tolist()],
        "action_probabilities": [
            [float(item) for item in row] for row in action_probabilities.tolist()
        ],
        "directional_profitability_probabilities_raw": [
            [float(item) for item in row]
            for row in profitability_probabilities.tolist()
        ],
        "directional_profitability_probabilities_calibrated": (
            calibrated_profitability
        ),
    }


def train_serving_checkpoint_v3(
    *,
    dataset_path: Path,
    manifest_path: Path,
    parity_path: Path,
    build_receipt_path: Path,
    output_dir: Path,
) -> tuple[CheckpointBundleV2, dict[str, Any], Path]:
    """Train a non-activating paper challenger; never mutates the registry."""

    import torch

    torch.manual_seed(FIXED_RANDOM_SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(FIXED_RANDOM_SEED)
    torch.use_deterministic_algorithms(True)
    receipt_bytes_before_validation = _read_regular_bytes(
        build_receipt_path, "build_receipt_path"
    )
    dataset, manifest, parity, build_receipt = load_validated_training_artifacts(
        dataset_path=dataset_path,
        manifest_path=manifest_path,
        parity_path=parity_path,
        build_receipt_path=build_receipt_path,
    )
    receipt_bytes_after_validation = _read_regular_bytes(
        build_receipt_path, "build_receipt_path"
    )
    if receipt_bytes_before_validation != receipt_bytes_after_validation:
        raise ValueError("build_receipt_path:CHANGED_DURING_VALIDATION")
    build_receipt_file_sha256 = hashlib.sha256(
        receipt_bytes_before_validation
    ).hexdigest()

    train_rows = _partition(dataset, "train")
    validation_rows = _partition(dataset, "validation")
    holdout_rows = _partition(dataset, "holdout")
    row_weights, group_report = decision_group_balance(train_rows)
    if (
        group_report["effective_independent_training_groups"]
        < MIN_EFFECTIVE_INDEPENDENT_TRAINING_GROUPS
    ):
        raise ValueError("TRAINING_EFFECTIVE_INDEPENDENT_SAMPLE_BELOW_MINIMUM")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def tensors(rows: list[dict[str, Any]]) -> tuple[Any, Any, Any, Any]:
        x = torch.tensor(
            [row["feature_values"] for row in rows],
            dtype=torch.float32,
            device=device,
        )
        y = torch.tensor(
            [row["target_action_index"] for row in rows],
            dtype=torch.long,
            device=device,
        )
        edge = torch.tensor(
            [[row["long_net_bps"], row["short_net_bps"]] for row in rows],
            dtype=torch.float32,
            device=device,
        )
        profitability = (edge > 0.0).to(dtype=torch.float32)
        return x, y, edge, profitability

    x_train_raw, y_train, edge_train, profit_train = tensors(train_rows)
    x_validation_raw, y_validation, edge_validation, profit_validation = tensors(
        validation_rows
    )
    x_holdout_raw, y_holdout, edge_holdout, profit_holdout = tensors(holdout_rows)
    weights = torch.tensor(row_weights, dtype=torch.float32, device=device)
    mean = x_train_raw.mean(dim=0)
    observed_std = x_train_raw.std(dim=0, unbiased=False)
    training_min = x_train_raw.min(dim=0).values
    training_max = x_train_raw.max(dim=0).values
    scale = torch.clamp(observed_std, min=MIN_STANDARDIZATION_SCALE)
    x_train = (x_train_raw - mean) / scale
    x_validation = (x_validation_raw - mean) / scale
    x_holdout = (x_holdout_raw - mean) / scale
    edge_mean_bps = edge_train.mean(dim=0)
    edge_observed_std_bps = edge_train.std(dim=0, unbiased=False)
    edge_scale_bps = torch.clamp(
        edge_observed_std_bps, min=MIN_EDGE_TARGET_SCALE_BPS
    )
    edge_train_standardized = (edge_train - edge_mean_bps) / edge_scale_bps

    model = build_serving_model_v4(
        input_dim=len(ORDERED_FEATURE_NAMES), action_count=len(ACTION_LABELS)
    ).to(device)
    action_counts = torch.bincount(y_train, minlength=len(ACTION_LABELS)).float()
    class_weights = torch.sqrt(
        action_counts.sum() / torch.clamp(action_counts, min=1.0)
    )
    class_weights = class_weights / class_weights.mean()
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=1e-4)
    final_loss = float("nan")
    model.train()
    for _ in range(OPTIMIZER_STEPS):
        optimizer.zero_grad(set_to_none=True)
        logits, edge_standardized, profitability_logits = model(x_train)
        action_loss_by_row = torch.nn.functional.cross_entropy(
            logits, y_train, weight=class_weights, reduction="none"
        )
        edge_loss_by_row = torch.nn.functional.smooth_l1_loss(
            edge_standardized,
            edge_train_standardized,
            reduction="none",
        ).mean(dim=1)
        profitability_loss_by_row = torch.nn.functional.binary_cross_entropy_with_logits(
            profitability_logits,
            profit_train,
            reduction="none",
        ).mean(dim=1)
        loss_by_row = (
            action_loss_by_row
            + EDGE_REGRESSION_LOSS_WEIGHT * edge_loss_by_row
            + PROFITABILITY_LOSS_WEIGHT * profitability_loss_by_row
        )
        loss = (loss_by_row * weights).sum() / weights.sum()
        if not torch.isfinite(loss):
            raise ValueError("TRAINING_LOSS_NONFINITE")
        loss.backward()
        optimizer.step()
        final_loss = float(loss.detach().cpu().item())
    model.eval()
    training_evaluation = _evaluate(
        model,
        x_train,
        y_train,
        edge_train,
        profit_train,
        edge_mean_bps,
        edge_scale_bps,
    )
    validation_raw_evaluation = _evaluate(
        model,
        x_validation,
        y_validation,
        edge_validation,
        profit_validation,
        edge_mean_bps,
        edge_scale_bps,
    )

    calibration_probs: list[float] = []
    calibration_outcomes: list[int] = []
    calibration_row_ids: list[str] = []
    calibration_actions: list[str] = []
    for row, probability_row in zip(
        train_rows,
        training_evaluation["directional_profitability_probabilities_raw"],
        strict=True,
    ):
        for action, probability in zip(
            DIRECTIONAL_ACTIONS, probability_row, strict=True
        ):
            calibration_probs.append(float(probability))
            calibration_outcomes.append(int(float(row[f"{action}_net_bps"]) > 0.0))
            calibration_row_ids.append(f"{row['row_id']}:{action}:profitability_v4")
            calibration_actions.append(action)
    calibration = fit_temperature(
        calibration_probs,
        calibration_outcomes,
        row_ids=calibration_row_ids,
        action_labels=calibration_actions,
        validation_rows_used=0,
    )
    parameter_fingerprint = _parameter_fingerprint(model.state_dict())
    calibration.update(
        {
            "model_parameter_fingerprint": parameter_fingerprint,
            "probability_source": "DEDICATED_DIRECTIONAL_AFTER_COST_PROFITABILITY_HEAD",
            "action_probability_used_as_profitability_probability": False,
        }
    )
    calibration = normalize_calibration_state(calibration)
    calibration.update(
        {
            "probability_semantics_valid": calibration.get("fitted") is True,
            "probability_source": "DEDICATED_DIRECTIONAL_AFTER_COST_PROFITABILITY_HEAD",
            "action_probability_used_as_profitability_probability": False,
        }
    )
    if calibration.get("fitted") is not True:
        raise ValueError(f"CALIBRATION_REJECTED:{calibration.get('reason')}")
    temperature = float(calibration["temperature"])
    validation_evaluation = _evaluate(
        model,
        x_validation,
        y_validation,
        edge_validation,
        profit_validation,
        edge_mean_bps,
        edge_scale_bps,
        confidence_temperature=temperature,
    )
    # Holdout is consumed only after model weights and calibration are frozen.
    holdout_evaluation = _evaluate(
        model,
        x_holdout,
        y_holdout,
        edge_holdout,
        profit_holdout,
        edge_mean_bps,
        edge_scale_bps,
        confidence_temperature=temperature,
    )
    training_profit_base = profit_train.mean(dim=0)
    validation_base_brier = float(
        ((profit_validation - training_profit_base) ** 2).mean().item()
    )
    validation_evaluation["train_base_rate_brier"] = validation_base_brier
    validation_evaluation["calibrated_brier_improves_train_base_rate"] = bool(
        float(validation_evaluation["profitability_calibrated_brier"])
        < validation_base_brier
    )

    rejection_reasons: list[str] = []
    if validation_evaluation["directional_rate"] == 0.0:
        rejection_reasons.append("VALIDATION_DIRECTIONAL_RATE_ZERO")
    if validation_evaluation["all_predictions_one_action"]:
        rejection_reasons.append("VALIDATION_ALL_PREDICTIONS_ONE_ACTION")
    for field in (
        "nonfinite_probabilities",
        "nonfinite_directional_net_edges",
        "nonfinite_profitability_probabilities",
    ):
        if int(validation_evaluation[field]) > 0:
            rejection_reasons.append(f"VALIDATION_{field.upper()}")
        if int(holdout_evaluation[field]) > 0:
            rejection_reasons.append(f"HOLDOUT_{field.upper()}")
    if validation_evaluation["selected_directional_positive_edge_rate"] == 0.0:
        rejection_reasons.append("VALIDATION_DIRECTIONAL_NET_EDGE_RATE_ZERO")
    if rejection_reasons:
        raise ValueError("CHECKPOINT_REJECTED:" + ",".join(rejection_reasons))

    checkpoint_id = "SERVING_ABI_V2_PROFITABILITY_PAPER_" + hashlib.sha256(
        f"{manifest['manifest_sha256']}:{parameter_fingerprint}".encode("ascii")
    ).hexdigest()[:24]
    generated_at = max(
        dataset["rows"],
        key=lambda row: datetime.fromisoformat(
            row["label_available_at"].replace("Z", "+00:00")
        ),
    )["label_available_at"]
    training_artifact_authentication = {
        "schema_version": "serving_training_artifact_authentication_v2",
        "dataset_id": dataset["dataset_id"],
        "dataset_sha256": dataset["dataset_sha256"],
        "dataset_file_sha256": build_receipt["artifact_file_sha256s"][
            dataset_path.name
        ],
        "manifest_id": manifest["manifest_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "manifest_file_sha256": build_receipt["artifact_file_sha256s"][
            manifest_path.name
        ],
        "parity_file_sha256": build_receipt["artifact_file_sha256s"][
            parity_path.name
        ],
        "build_receipt_sha256": canonical_sha256(build_receipt),
        "build_receipt_file_sha256": build_receipt_file_sha256,
        "candidate_archive_terminal_chain_sha256": build_receipt[
            "candidate_archive_verification"
        ]["terminal_chain_sha256"],
        "base_dataset_file_sha256": build_receipt["base_dataset_file_sha256"],
        "artifact_contracts_authenticated": True,
    }
    meta = {
        "checkpoint_id": checkpoint_id,
        "checkpoint_classification": "PAPER_PROVISIONAL",
        "generated_utc": generated_at,
        "generated_utc_semantics": "LATEST_AUTHENTICATED_LABEL_AVAILABLE_AT",
        "manifest_id": manifest["manifest_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "feature_abi_sha256": feature_abi_sha256(),
        "feature_builder_sha256": feature_builder_sha256(),
        "feature_names": list(ORDERED_FEATURE_NAMES),
        "model_architecture": MODEL_ARCHITECTURE,
        "standardize_mean": [float(value) for value in mean.detach().cpu().tolist()],
        "standardize_std": [float(value) for value in scale.detach().cpu().tolist()],
        "observed_training_std": [
            float(value) for value in observed_std.detach().cpu().tolist()
        ],
        "training_feature_min": [
            float(value) for value in training_min.detach().cpu().tolist()
        ],
        "training_feature_max": [
            float(value) for value in training_max.detach().cpu().tolist()
        ],
        "minimum_standardization_scale": MIN_STANDARDIZATION_SCALE,
        "directional_net_edge_actions": list(DIRECTIONAL_ACTIONS),
        "directional_net_edge_mean_bps": [
            float(value) for value in edge_mean_bps.detach().cpu().tolist()
        ],
        "directional_net_edge_scale_bps": [
            float(value) for value in edge_scale_bps.detach().cpu().tolist()
        ],
        "directional_net_edge_observed_training_std_bps": [
            float(value) for value in edge_observed_std_bps.detach().cpu().tolist()
        ],
        "directional_net_edge_semantics": (
            "predicted_position_return_bps_after_complete_round_trip_cost"
        ),
        "directional_profitability_actions": list(DIRECTIONAL_ACTIONS),
        "directional_profitability_semantics": (
            "probability_directional_position_return_after_complete_cost_is_positive"
        ),
        "action_probability_used_as_profitability_probability": False,
        "decision_group_balance": group_report,
        "actions": list(ACTION_LABELS),
        "input_dim": len(ORDERED_FEATURE_NAMES),
        "checkpoint_weight_sha256": parameter_fingerprint,
        "model_parameter_fingerprint": parameter_fingerprint,
        "model_id": f"serving_abi_v2_profit_mlp_{parameter_fingerprint[:16]}",
        "confidence_calibration_state": calibration,
        "training_artifact_authentication": training_artifact_authentication,
        "training_metrics": {
            "optimizer_steps": OPTIMIZER_STEPS,
            "final_loss": final_loss,
            "finite_loss": math.isfinite(final_loss),
            "training": training_evaluation,
            "validation_raw": validation_raw_evaluation,
            "validation": validation_evaluation,
            "holdout": holdout_evaluation,
            "decision_group_balance": group_report,
        },
        "device": str(device),
        "paper_only": True,
        "checkpoint_promotable": False,
        "live_eligible": False,
        "routes_to_live": False,
        "economic_certification": "PROVISIONAL",
    }
    _prepare_output_directory(output_dir)
    checkpoint_path = output_dir / f"{checkpoint_id}.pt"
    checkpoint_buffer = io.BytesIO()
    torch.save(
        {
            "meta": meta,
            "state_dict": {
                key: value.detach().cpu() for key, value in model.state_dict().items()
            },
        },
        checkpoint_buffer,
    )
    checkpoint_bytes = checkpoint_buffer.getvalue()
    checkpoint_file_sha256 = hashlib.sha256(checkpoint_bytes).hexdigest()
    metrics = {
        "optimizer_steps": OPTIMIZER_STEPS,
        "final_loss": final_loss,
        "finite_loss": math.isfinite(final_loss),
        "training": training_evaluation,
        "validation_raw": validation_raw_evaluation,
        "validation": validation_evaluation,
        "holdout": holdout_evaluation,
        "calibration": calibration,
        "decision_group_balance": group_report,
        "required_feature_missing_rate": 0.0,
        "feature_abi_match": True,
        "training_serving_builder_match": True,
        "paper_only": True,
        "live_eligible": False,
        "checkpoint_promotable": False,
        "economic_certification": "PROVISIONAL",
        "training_artifact_authentication": training_artifact_authentication,
    }
    bundle = CheckpointBundleV2(
        checkpoint_id=checkpoint_id,
        checkpoint_classification="PAPER_PROVISIONAL",
        model_architecture=MODEL_ARCHITECTURE,
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
    bundle_reasons = bundle.validate()
    if bundle_reasons:
        raise ValueError("CHECKPOINT_BUNDLE_INVALID:" + ",".join(bundle_reasons))
    _publish_immutable_checkpoint(
        checkpoint_bytes=checkpoint_bytes,
        target_path=checkpoint_path,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "generated_at_semantics": "LATEST_AUTHENTICATED_LABEL_AVAILABLE_AT",
        "checkpoint_id": checkpoint_id,
        "checkpoint_path": str(checkpoint_path.resolve()),
        "checkpoint_file_sha256": checkpoint_file_sha256,
        "model_parameter_fingerprint": parameter_fingerprint,
        "manifest_id": manifest["manifest_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "feature_abi_sha256": feature_abi_sha256(),
        "feature_builder_sha256": feature_builder_sha256(),
        "training_artifact_authentication": training_artifact_authentication,
        "metrics": metrics,
        "holdout_consumed_once_after_model_and_calibration_frozen": True,
        "activation_eligible": False,
        "activation_block_reasons": [
            "RESEARCH_CHALLENGER_NOT_GOVERNED_FOR_ACTIVATION",
            *(
                []
                if validation_evaluation[
                    "calibrated_brier_improves_train_base_rate"
                ]
                else ["VALIDATION_PROFITABILITY_BRIER_NOT_ABOVE_BASELINE"]
            ),
            "FRESH_GENERATION_SCOPED_ECONOMIC_CERTIFICATION_REQUIRED",
        ],
        "paper_only": True,
        "live_eligible": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    return bundle, report, checkpoint_path


__all__ = ["decision_group_balance", "train_serving_checkpoint_v3"]
