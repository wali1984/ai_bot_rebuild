"""Build one signed-release-bound, train-only feature representation challenger.

The worker does not alter ServingFeatureABIV2, a checkpoint, either model
registry lane, or paper/live execution.  It authenticates the exact rolling
dataset release, selects a compact candidate representation using training rows
only, and evaluates the frozen selection on validation/holdout rows.  The
result is research evidence for the automatic escalation ladder, never trading
authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from v2.backend.app.services.adaptive_system import escalation_supervisor_v2 as supervisor

SCHEMA_VERSION = "adaptive_feature_representation_challenger_v2"
OUTPUT_NAME = "adaptive_feature_representation_challenger_v2.json"
REQUIRED_COST_FEATURES = (
    "expected_funding_bps",
    "expected_slippage_bps",
    "fee_bps",
    "spread_bps",
)
MIN_SELECTED_FEATURES = 8
MAX_SELECTED_FEATURES = 20
LOW_VARIANCE_EPSILON = 1e-12
REDUNDANCY_ABS_CORRELATION_LIMIT = 0.995
VALIDATION_NONINFERIOR_RATIO = 1.005
RIDGE_ALPHA = 1e-3


class AdaptiveFeatureRepresentationError(RuntimeError):
    pass


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AdaptiveFeatureRepresentationError("STRICT_JSON_REQUIRED") from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_object(path: Path, field: str) -> dict[str, Any]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise AdaptiveFeatureRepresentationError(
            f"{field}:REGULAR_FILE_REQUIRED"
        ) from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise AdaptiveFeatureRepresentationError(
                f"{field}:REGULAR_FILE_REQUIRED"
            )
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as handle:
            try:
                value = json.load(
                    handle,
                    parse_constant=lambda token: (_ for _ in ()).throw(
                        ValueError(f"nonfinite:{token}")
                    ),
                    object_pairs_hook=_reject_duplicate_keys,
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise AdaptiveFeatureRepresentationError(
                    f"{field}:STRICT_JSON_REQUIRED"
                ) from exc
    finally:
        os.close(descriptor)
    if type(value) is not dict:
        raise AdaptiveFeatureRepresentationError(f"{field}:OBJECT_REQUIRED")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate_key:{key}")
        result[key] = value
    return result


def _safe_output_directory(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = os.lstat(path)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise AdaptiveFeatureRepresentationError("output_dir:SAFE_DIRECTORY_REQUIRED")
    return path.absolute()


def _write_immutable(path: Path, payload: Mapping[str, Any]) -> str:
    data = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except FileExistsError:
        try:
            metadata = os.lstat(path)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise AdaptiveFeatureRepresentationError(
                    "output:IMMUTABLE_COLLISION"
                )
            existing = path.read_bytes()
        except OSError as exc:
            raise AdaptiveFeatureRepresentationError(
                "output:IMMUTABLE_COLLISION"
            ) from exc
        if existing != data:
            raise AdaptiveFeatureRepresentationError("output:IMMUTABLE_COLLISION")
        return _sha256(existing)
    try:
        remaining = memoryview(data)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise AdaptiveFeatureRepresentationError("output:SHORT_WRITE")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return _sha256(data)


def _exact_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AdaptiveFeatureRepresentationError(f"{field}:FINITE_NUMBER_REQUIRED")
    converted = float(value)
    if not math.isfinite(converted):
        raise AdaptiveFeatureRepresentationError(f"{field}:FINITE_NUMBER_REQUIRED")
    return converted


def _matrix_by_split(
    dataset: Mapping[str, Any],
    ordered_features: tuple[str, ...],
) -> dict[str, tuple[np.ndarray, np.ndarray, tuple[str, ...]]]:
    rows = dataset.get("rows")
    if type(rows) is not list or not rows:
        raise AdaptiveFeatureRepresentationError("dataset.rows:NONEMPTY_LIST_REQUIRED")
    collected: dict[str, list[tuple[list[float], list[float], str]]] = {
        "train": [],
        "validation": [],
        "holdout": [],
    }
    for index, row in enumerate(rows):
        if type(row) is not dict:
            raise AdaptiveFeatureRepresentationError(
                f"dataset.rows[{index}]:OBJECT_REQUIRED"
            )
        split = row.get("split")
        if split not in collected:
            raise AdaptiveFeatureRepresentationError(
                f"dataset.rows[{index}].split:INVALID"
            )
        feature_values = row.get("feature_values")
        missing_mask = row.get("missing_mask")
        if (
            type(feature_values) is not list
            or len(feature_values) != len(ordered_features)
            or type(missing_mask) is not list
            or len(missing_mask) != len(ordered_features)
            or any(type(flag) is not int or flag not in {0, 1} for flag in missing_mask)
        ):
            raise AdaptiveFeatureRepresentationError(
                f"dataset.rows[{index}]:FEATURE_VECTOR_CONTRACT_INVALID"
            )
        if any(missing_mask):
            raise AdaptiveFeatureRepresentationError(
                f"dataset.rows[{index}]:REQUIRED_FEATURE_MISSING"
            )
        vector = [
            _exact_float(value, f"dataset.rows[{index}].feature_values")
            for value in feature_values
        ]
        targets = [
            _exact_float(row.get("long_net_bps"), f"dataset.rows[{index}].long_net_bps"),
            _exact_float(row.get("short_net_bps"), f"dataset.rows[{index}].short_net_bps"),
        ]
        action = row.get("target_action")
        if action not in {"long", "short", "hold"}:
            raise AdaptiveFeatureRepresentationError(
                f"dataset.rows[{index}].target_action:INVALID"
            )
        collected[str(split)].append((vector, targets, str(action)))
    result: dict[str, tuple[np.ndarray, np.ndarray, tuple[str, ...]]] = {}
    for split, values in collected.items():
        if not values:
            raise AdaptiveFeatureRepresentationError(f"dataset.{split}:NONEMPTY_REQUIRED")
        result[split] = (
            np.asarray([value[0] for value in values], dtype=np.float64),
            np.asarray([value[1] for value in values], dtype=np.float64),
            tuple(value[2] for value in values),
        )
    return result


def _absolute_correlation(left: np.ndarray, right: np.ndarray) -> float:
    left_centered = left - float(np.mean(left))
    right_centered = right - float(np.mean(right))
    denominator = float(
        np.sqrt(np.sum(left_centered * left_centered) * np.sum(right_centered * right_centered))
    )
    if denominator <= LOW_VARIANCE_EPSILON:
        return 0.0
    return abs(float(np.sum(left_centered * right_centered) / denominator))


def _select_features(
    ordered_features: tuple[str, ...],
    train_x: np.ndarray,
    train_y: np.ndarray,
    train_actions: tuple[str, ...],
) -> tuple[tuple[int, ...], list[dict[str, Any]]]:
    action_targets = {
        action: np.asarray([value == action for value in train_actions], dtype=np.float64)
        for action in ("long", "short", "hold")
    }
    relevances: list[float] = []
    standard_deviations: list[float] = []
    for position in range(len(ordered_features)):
        feature = train_x[:, position]
        standard_deviations.append(float(np.std(feature)))
        relevances.append(
            max(
                _absolute_correlation(feature, train_y[:, 0]),
                _absolute_correlation(feature, train_y[:, 1]),
                *(
                    _absolute_correlation(feature, action_target)
                    for action_target in action_targets.values()
                ),
            )
        )
    required_positions = [
        ordered_features.index(name)
        for name in REQUIRED_COST_FEATURES
        if name in ordered_features
    ]
    if len(required_positions) != len(REQUIRED_COST_FEATURES):
        raise AdaptiveFeatureRepresentationError("dataset:REQUIRED_COST_FEATURE_MISSING")
    ranked = sorted(
        range(len(ordered_features)),
        key=lambda position: (-relevances[position], position),
    )
    selected: list[int] = list(required_positions)
    reasons: dict[int, str] = {
        position: "REQUIRED_COST_IDENTITY" for position in required_positions
    }
    for position in ranked:
        if position in selected:
            continue
        if standard_deviations[position] <= LOW_VARIANCE_EPSILON:
            reasons[position] = "LOW_VARIANCE_TRAIN_ONLY"
            continue
        redundant_with = next(
            (
                other
                for other in selected
                if _absolute_correlation(
                    train_x[:, position],
                    train_x[:, other],
                )
                >= REDUNDANCY_ABS_CORRELATION_LIMIT
            ),
            None,
        )
        if redundant_with is not None and len(selected) >= MIN_SELECTED_FEATURES:
            reasons[position] = f"REDUNDANT_WITH:{ordered_features[redundant_with]}"
            continue
        if len(selected) >= MAX_SELECTED_FEATURES:
            reasons[position] = "RANK_BELOW_FROZEN_CAP"
            continue
        selected.append(position)
        reasons[position] = "TRAIN_ONLY_RELEVANCE_SELECTED"
    if len(selected) < MIN_SELECTED_FEATURES:
        for position in ranked:
            if position not in selected:
                selected.append(position)
                reasons[position] = "MINIMUM_REPRESENTATION_FLOOR"
            if len(selected) >= MIN_SELECTED_FEATURES:
                break
    selected_tuple = tuple(sorted(selected))
    evidence = [
        {
            "name": name,
            "position": position,
            "train_standard_deviation": standard_deviations[position],
            "train_relevance": relevances[position],
            "selected": position in selected_tuple,
            "exact_reason": reasons.get(position, "NOT_SELECTED"),
        }
        for position, name in enumerate(ordered_features)
    ]
    return selected_tuple, evidence


def _ridge_metrics(
    matrices: Mapping[str, tuple[np.ndarray, np.ndarray, tuple[str, ...]]],
    positions: Sequence[int],
) -> dict[str, dict[str, float | int]]:
    train_x, train_y, _train_actions = matrices["train"]
    selected_train = train_x[:, positions]
    mean = np.mean(selected_train, axis=0)
    std = np.std(selected_train, axis=0)
    safe_std = np.where(std > LOW_VARIANCE_EPSILON, std, 1.0)
    normalized = (selected_train - mean) / safe_std
    design = np.column_stack((np.ones(normalized.shape[0]), normalized))
    penalty = np.eye(design.shape[1], dtype=np.float64) * RIDGE_ALPHA
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(
        design.T @ design + penalty,
        design.T @ train_y,
    )
    output: dict[str, dict[str, float | int]] = {}
    for split in ("train", "validation", "holdout"):
        values, targets, actions = matrices[split]
        normalized_values = (values[:, positions] - mean) / safe_std
        predictions = np.column_stack(
            (np.ones(normalized_values.shape[0]), normalized_values)
        ) @ coefficients
        predicted_actions = np.where(
            (predictions[:, 0] > predictions[:, 1]) & (predictions[:, 0] > 0.0),
            "long",
            np.where(predictions[:, 1] > 0.0, "short", "hold"),
        )
        output[split] = {
            "rows": int(values.shape[0]),
            "net_bps_mean_squared_error": float(np.mean((predictions - targets) ** 2)),
            "target_action_accuracy": float(
                np.mean(predicted_actions == np.asarray(actions, dtype=object))
            ),
        }
    return output


def build_representation_candidate(
    *,
    dataset: Mapping[str, Any],
    release_projection: Mapping[str, Any],
    release_source: Mapping[str, Any],
) -> dict[str, Any]:
    ordered = dataset.get("ordered_feature_names")
    if (
        type(ordered) is not list
        or not ordered
        or any(type(name) is not str or not name for name in ordered)
        or len(set(ordered)) != len(ordered)
    ):
        raise AdaptiveFeatureRepresentationError(
            "dataset.ordered_feature_names:CANONICAL_UNIQUE_LIST_REQUIRED"
        )
    ordered_features = tuple(ordered)
    if dataset.get("dataset_sha256") != release_projection.get("dataset_sha256"):
        raise AdaptiveFeatureRepresentationError("dataset:RELEASE_IDENTITY_MISMATCH")
    matrices = _matrix_by_split(dataset, ordered_features)
    selected_positions, feature_evidence = _select_features(
        ordered_features,
        *matrices["train"],
    )
    full_positions = tuple(range(len(ordered_features)))
    full_metrics = _ridge_metrics(matrices, full_positions)
    selected_metrics = _ridge_metrics(matrices, selected_positions)
    validation_ratio = (
        selected_metrics["validation"]["net_bps_mean_squared_error"]
        / full_metrics["validation"]["net_bps_mean_squared_error"]
    )
    validation_noninferior = validation_ratio <= VALIDATION_NONINFERIOR_RATIO
    compact = len(selected_positions) < len(full_positions)
    candidate = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "PASS_COMPACT_VALIDATION_NONINFERIOR"
            if validation_noninferior and compact
            else "PASS_EVALUATED_NOT_NONINFERIOR"
        ),
        "dataset_release": dict(release_projection),
        "source_matured_revision_count": release_source.get(
            "matured_revision_count"
        ),
        "source_terminal_chain_sha256": release_source.get(
            "terminal_chain_sha256"
        ),
        "feature_abi_sha256": dataset.get("feature_abi_sha256"),
        "feature_builder_sha256": dataset.get("feature_builder_sha256"),
        "selection_partition": "TRAIN_ONLY",
        "validation_used_for_selection": False,
        "holdout_used_for_selection": False,
        "ordered_feature_names": list(ordered_features),
        "selected_positions": list(selected_positions),
        "selected_feature_names": [
            ordered_features[position] for position in selected_positions
        ],
        "feature_evidence": feature_evidence,
        "full_representation_metrics": full_metrics,
        "candidate_representation_metrics": selected_metrics,
        "validation_mse_ratio_selected_to_full": validation_ratio,
        "validation_noninferior_ratio_limit": VALIDATION_NONINFERIOR_RATIO,
        "validation_noninferior": validation_noninferior,
        "compact_representation": compact,
        "representation_superior": validation_noninferior and compact,
        "serving_abi_changed": False,
        "activation_eligible": False,
        "checkpoint_promotable": False,
        "live_eligible": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    representation_id = "adaptive_feature_representation_" + _sha256(
        _canonical_bytes(candidate)
    )[:24]
    candidate["representation_id"] = representation_id
    unsigned = dict(candidate)
    candidate["payload_sha256"] = _sha256(_canonical_bytes(unsigned))
    return candidate


def run_once(*, dataset_release_root: Path, output_dir: Path) -> dict[str, Any]:
    projection, source = supervisor._authenticated_dataset_release_evidence(  # noqa: SLF001
        dataset_release_root
    )
    dataset = _strict_object(Path(projection["paths"]["dataset"]), "dataset")
    candidate = build_representation_candidate(
        dataset=dataset,
        release_projection=projection,
        release_source=source,
    )
    root = _safe_output_directory(output_dir)
    output_sha256 = _write_immutable(root / OUTPUT_NAME, candidate)
    return {**candidate, "output_file_sha256": output_sha256}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-release-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_once(
        dataset_release_root=args.dataset_release_root,
        output_dir=args.output_dir,
    )
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
