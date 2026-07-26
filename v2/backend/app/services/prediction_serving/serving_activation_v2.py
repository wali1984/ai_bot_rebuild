"""Read-only current-universe qualification for ServingFeatureABIV2 activation."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.cli.v2_paper_provisional_prediction_publisher import (
    ADAPTIVE_COST_KEY_TEMPLATE,
    ProvisionalCheckpoint,
    read_current_feature_snapshot,
    read_json_key,
)
from v2.backend.app.contracts.runtime_v2.contracts import CheckpointBundleV2
from v2.backend.app.services.prediction_serving.checkpoint_registry import read_active
from v2.backend.app.services.prediction_serving.serving_feature_abi_v2 import (
    ORDERED_FEATURE_NAMES,
    build_serving_feature_vector,
    feature_abi_sha256,
    feature_builder_sha256,
)
from v2.backend.app.services.prediction_serving.serving_model_v3 import (
    MODEL_ARCHITECTURE,
)

SCHEMA_VERSION = "train_serve_feature_parity_report_v2"
MEAN_Z_LIMIT = 8.0
LOW_VARIANCE_ABSOLUTE_DELTA_LIMIT = 0.04
MIN_DISTRIBUTION_SAMPLE = 10


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def load_checkpoint_bundle(path: Path) -> CheckpointBundleV2:
    payload = json.loads(path.read_text())
    allowed = set(CheckpointBundleV2.__dataclass_fields__)
    values = {key: value for key, value in payload.items() if key in allowed}
    values["ordered_feature_names"] = tuple(values["ordered_feature_names"])
    values["action_labels"] = tuple(values["action_labels"])
    return CheckpointBundleV2(**values)


def _checkpoint_meta(path: Path) -> dict[str, Any]:
    import torch

    blob = torch.load(path, map_location="cpu", weights_only=False)
    meta = blob.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("CHECKPOINT_META_MISSING")
    return meta


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate_current_universe(
    client: Any,
    *,
    bundle: CheckpointBundleV2,
    manifest: Mapping[str, Any],
    symbols: Iterable[str],
    timeframes: Iterable[str],
) -> dict[str, Any]:
    """Evaluate every requested slot without publishing a prediction or intent."""
    weight_path = Path(bundle.weight_file_path)
    checkpoint = ProvisionalCheckpoint(weight_path)
    meta = _checkpoint_meta(weight_path)
    decision_time = _utc_now()
    vectors: list[tuple[float, ...]] = []
    observations: list[dict[str, Any]] = []
    rejections: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    nonfinite_probabilities = 0
    nonfinite_directional_net_edges = 0
    positive_directional_net_edges = 0
    directional_net_edge_observations = 0

    symbol_list = [str(symbol).upper() for symbol in symbols]
    timeframe_list = [str(timeframe) for timeframe in timeframes]
    for symbol in symbol_list:
        cost = read_json_key(client, ADAPTIVE_COST_KEY_TEMPLATE.format(symbol=symbol))
        for timeframe in timeframe_list:
            snapshot = read_current_feature_snapshot(client, symbol, timeframe)
            if not isinstance(snapshot, Mapping):
                rejections["NO_CURRENT_FEATURE_SNAPSHOT"] += 1
                continue
            if not isinstance(cost, Mapping):
                rejections["NO_EXACT_COST_RECORD"] += 1
                continue
            try:
                vector = build_serving_feature_vector(
                    feature_record=snapshot,
                    decision_time=decision_time,
                    exact_cost_record=cost,
                )
            except ValueError as error:
                reason = str(error).split(":", 1)[0]
                rejections[reason] += 1
                continue
            forward = checkpoint.forward(list(vector.values))
            probabilities = [float(value) for value in forward["probabilities"]]
            nonfinite_probabilities += sum(not math.isfinite(value) for value in probabilities)
            action = str(forward["action"])
            selected_edge = forward.get("selected_directional_net_edge_bps")
            if action in {"long", "short"}:
                directional_net_edge_observations += 1
                try:
                    parsed_edge = float(selected_edge)
                except (TypeError, ValueError):
                    nonfinite_directional_net_edges += 1
                else:
                    if not math.isfinite(parsed_edge):
                        nonfinite_directional_net_edges += 1
                    elif parsed_edge > 0.0:
                        positive_directional_net_edges += 1
            actions[action] += 1
            vectors.append(vector.values)
            observations.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "feature_snapshot_id": snapshot.get("feature_snapshot_id"),
                    "source_record_sha256": vector.source_record_sha256,
                    "action": action,
                    "probabilities": probabilities,
                    "selected_directional_net_edge_bps": selected_edge,
                }
            )

    distribution: list[dict[str, Any]] = []
    excessive_features: list[str] = []
    training_mean = [float(value) for value in meta["standardize_mean"]]
    training_std = [float(value) for value in meta["observed_training_std"]]
    training_min = [float(value) for value in meta["training_feature_min"]]
    training_max = [float(value) for value in meta["training_feature_max"]]
    for index, name in enumerate(ORDERED_FEATURE_NAMES):
        current = [float(row[index]) for row in vectors]
        current_mean = statistics.fmean(current) if current else None
        current_std = statistics.pstdev(current) if len(current) > 1 else None
        mean_delta = None if current_mean is None else current_mean - training_mean[index]
        mean_z = None
        low_variance_delta_excessive = False
        if mean_delta is not None:
            mean_z = mean_delta / max(training_std[index], 0.01)
            if training_std[index] < 0.01:
                low_variance_delta_excessive = abs(mean_delta) > LOW_VARIANCE_ABSOLUTE_DELTA_LIMIT
            if abs(mean_z) > MEAN_Z_LIMIT or low_variance_delta_excessive:
                excessive_features.append(name)
        distribution.append(
            {
                "name": name,
                "training_mean": training_mean[index],
                "training_std": training_std[index],
                "training_min": training_min[index],
                "training_max": training_max[index],
                "current_sample": len(current),
                "current_mean": current_mean,
                "current_std": current_std,
                "mean_delta_training_units": mean_z,
                "low_variance_feature": training_std[index] < 0.01,
                "low_variance_absolute_delta_excessive": low_variance_delta_excessive,
            }
        )

    accepted = len(vectors)
    directional = int(actions["long"] + actions["short"])
    represented_actions = sum(count > 0 for count in actions.values())
    enough_distribution_sample = accepted >= MIN_DISTRIBUTION_SAMPLE
    drift_above_limit = not enough_distribution_sample or bool(excessive_features)
    checkpoint_hash_valid = (
        weight_path.is_file() and _file_sha256(weight_path) == bundle.weight_sha256
    )
    manifest_hash_valid = (
        manifest.get("manifest_id") == bundle.training_manifest_id
        and manifest.get("manifest_sha256") == bundle.training_manifest_sha256
        and manifest.get("feature_abi_sha256") == bundle.feature_abi_sha256
    )
    feature_abi_valid = (
        bundle.feature_abi_sha256 == feature_abi_sha256()
        and bundle.ordered_feature_names == ORDERED_FEATURE_NAMES
        and bundle.training_feature_builder_sha == feature_builder_sha256()
        and bundle.serving_feature_builder_sha == feature_builder_sha256()
        and checkpoint.serving_feature_abi_v2
    )
    calibration_valid = (
        bundle.calibration_state.get("fitted") is True
        and bundle.calibration_state.get("probability_semantics_valid") is True
        and bundle.calibration_state.get("model_parameter_fingerprint")
        == bundle.model_parameter_fingerprint
        and bool(bundle.calibration_state.get("row_digest"))
    )
    all_predictions_one_action = accepted > 0 and represented_actions == 1
    serving_smoke_directional_rate = directional / accepted if accepted else 0.0
    serving_smoke_positive_directional_edge_rate = (
        positive_directional_net_edges / directional_net_edge_observations
        if directional_net_edge_observations
        else 0.0
    )
    directional_edge_model_required = (
        getattr(bundle, "model_architecture", None) == MODEL_ARCHITECTURE
    )
    directional_edge_model_valid = (
        not directional_edge_model_required
        or (
            directional_net_edge_observations > 0
            and nonfinite_directional_net_edges == 0
            and positive_directional_net_edges > 0
        )
    )
    shadow_prediction_valid = (
        accepted > 0
        and directional > 0
        and not all_predictions_one_action
        and nonfinite_probabilities == 0
        and directional_edge_model_valid
    )
    no_live_authority = (
        not bundle.live_eligible
        and not bundle.checkpoint_promotable
        and meta.get("paper_only") is True
        and meta.get("routes_to_live") is False
    )
    train_serve_parity_valid = (
        feature_abi_valid and enough_distribution_sample and not drift_above_limit and accepted > 0
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": decision_time,
        "checkpoint_id": bundle.checkpoint_id,
        "manifest_id": bundle.training_manifest_id,
        "manifest_sha256": bundle.training_manifest_sha256,
        "feature_abi_sha256": feature_abi_sha256(),
        "feature_builder_sha256": feature_builder_sha256(),
        "complete_eligible_universe_evaluated": True,
        "symbols_evaluated": len(symbol_list),
        "timeframes_evaluated": timeframe_list,
        "universe_slots_evaluated": len(symbol_list) * len(timeframe_list),
        "accepted_current_rows": accepted,
        "rejections_by_reason": dict(sorted(rejections.items())),
        "prediction_distribution": {name: int(actions[name]) for name in ("long", "short", "hold")},
        "serving_smoke_directional_rate": serving_smoke_directional_rate,
        "serving_smoke_positive_directional_edge_rate": (
            serving_smoke_positive_directional_edge_rate
        ),
        "directional_net_edge_model_required": directional_edge_model_required,
        "directional_net_edge_model_valid": directional_edge_model_valid,
        "directional_net_edge_observations": directional_net_edge_observations,
        "positive_directional_net_edge_observations": positive_directional_net_edges,
        "nonfinite_directional_net_edges": nonfinite_directional_net_edges,
        "all_predictions_one_action": all_predictions_one_action,
        "nonfinite_probabilities": nonfinite_probabilities,
        "required_feature_missing_rate": 0.0 if accepted else 1.0,
        "distribution_policy": {
            "mean_z_limit": MEAN_Z_LIMIT,
            "low_variance_absolute_delta_limit": LOW_VARIANCE_ABSOLUTE_DELTA_LIMIT,
            "minimum_current_sample": MIN_DISTRIBUTION_SAMPLE,
        },
        "feature_distribution": distribution,
        "excessive_drift_features": excessive_features,
        "feature_distribution_drift_above_limit": drift_above_limit,
        "checkpoint_hash_valid": checkpoint_hash_valid,
        "manifest_hash_valid": manifest_hash_valid,
        "feature_abi_valid": feature_abi_valid,
        "calibration_valid": calibration_valid,
        "train_serve_parity_valid": train_serve_parity_valid,
        "shadow_prediction_valid": shadow_prediction_valid,
        "no_live_authority": no_live_authority,
        "rollback_ready": read_active(client, lane="paper") is not None,
        "observations": observations,
        "paper_only": True,
        "live_eligible": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    report["activation_eligible"] = all(
        report.get(field) is True
        for field in (
            "checkpoint_hash_valid",
            "manifest_hash_valid",
            "feature_abi_valid",
            "calibration_valid",
            "train_serve_parity_valid",
            "shadow_prediction_valid",
            "no_live_authority",
            "rollback_ready",
        )
    )
    return report


__all__ = ["evaluate_current_universe", "load_checkpoint_bundle"]
