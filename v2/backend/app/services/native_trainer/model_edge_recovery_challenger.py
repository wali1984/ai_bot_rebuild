"""Trusted-replay champion/challenger edge recovery.

This lane is intentionally paper-only. It trains a small deterministic
challenger on point-in-time durable feature snapshots, selects a trade
threshold on validation rows, evaluates once on the untouched temporal
holdout, and publishes B-grade paper challenger signals only when the holdout
beats the current champion baseline with positive after-cost expectancy.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from v2.backend.app.services.market_state_integrity.sample_rejection import (
    classify_training_sample,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    default_archive_root,
    iter_snapshots,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    FUTURE_LABEL_PREFIXES,
    build_trusted_replay_row,
    parse_utc,
    snapshot_to_final_candle,
)


GOAL_ID = "V2_MODEL_EDGE_RECOVERY_CHAMPION_CHALLENGER_AND_A_GRADE_BOOTSTRAP"
ARTIFACT_REL = Path("operator_runtime/v2_model_edge_recovery/latest")
SCHEMA_VERSION = "v2_model_edge_recovery_champion_challenger_v1"
MODEL_SOURCE = "V2_MODEL_EDGE_RECOVERY_TRUSTED_REPLAY_RIDGE"
PAPER_CHALLENGER_TIER = "B_GRADE_EXPLORATION_PAPER"
LIVE_GATE_BLOCKED = "blocked_human_only"

CHAMPION_BASELINE = {
    "directional_accuracy": 0.4137,
    "expected_move_mae_bps": 107.7881,
    "false_positive_rate": 0.5824,
    "after_cost_expectancy_bps": -5.1884,
    "a_grade_promotable_buckets": 0,
    "active_strategy_buckets": 0,
}

DEFAULT_RIDGE_LAMBDAS = (0.1, 1.0, 10.0, 100.0, 1000.0)
DEFAULT_THRESHOLDS_BPS = (0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 15.0, 20.0, 30.0, 50.0)
DEFAULT_MODEL_FEATURE_CAP = 32
DEFAULT_TARGET_CLIP_BPS = 50.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _stable_result_material(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _stable_result_material(item)
            for key, item in value.items()
            if str(key) not in {"generated_utc", "generated_at"}
        }
    if isinstance(value, list):
        return [_stable_result_material(item) for item in value]
    return value


def _feature_name_allowed(name: str) -> bool:
    lowered = str(name).lower()
    return not lowered.startswith(FUTURE_LABEL_PREFIXES)


def numeric_features_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, float]:
    raw = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    out: dict[str, float] = {}
    for name, value in raw.items():
        key = str(name)
        if not _feature_name_allowed(key):
            continue
        parsed = finite_float(value)
        if parsed is not None:
            out[key] = parsed
    return out


@dataclass(frozen=True)
class EdgeRecoveryRow:
    sample_id: str
    snapshot_id: str
    symbol: str
    timeframe: str
    decision_time: str
    feature_cutoff: str
    available_at: str
    future_return_after_cost_bps: float
    target_action: str
    features: dict[str, float]

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "snapshot_id": self.snapshot_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "decision_time": self.decision_time,
            "feature_cutoff": self.feature_cutoff,
            "available_at": self.available_at,
            "future_return_after_cost_bps": self.future_return_after_cost_bps,
            "target_action": self.target_action,
            "feature_count": len(self.features),
        }


@dataclass(frozen=True)
class DatasetFreeze:
    rows: list[EdgeRecoveryRow]
    manifest: dict[str, Any]
    rejections_by_reason: dict[str, int]


@dataclass(frozen=True)
class ChallengerModel:
    feature_names: list[str]
    means: list[float]
    stds: list[float]
    weights: list[float]
    bias: float
    ridge_lambda: float
    threshold_bps: float
    validation_metrics: dict[str, Any]
    target_transform: str = "raw_future_return_after_cost_bps"
    target_clip_bps: float | None = None
    feature_count_limit: int | None = None

    def predict(self, features: Mapping[str, Any]) -> float:
        total = self.bias
        for name, mean, std, weight in zip(self.feature_names, self.means, self.stds, self.weights):
            value = finite_float(features.get(name)) or 0.0
            total += ((value - mean) / (std if std > 1e-12 else 1.0)) * weight
        return float(total)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "model_source": MODEL_SOURCE,
            "feature_names": self.feature_names,
            "means": self.means,
            "stds": self.stds,
            "weights": self.weights,
            "bias": self.bias,
            "ridge_lambda": self.ridge_lambda,
            "threshold_bps": self.threshold_bps,
            "validation_metrics": self.validation_metrics,
            "target_transform": self.target_transform,
            "target_clip_bps": self.target_clip_bps,
            "feature_count_limit": self.feature_count_limit,
        }


def _row_reject_reasons(snapshot: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    if not features:
        reasons.append("FEATURES_EMPTY")
    if any(str(name).lower().startswith(FUTURE_LABEL_PREFIXES) for name in features):
        reasons.append("FUTURE_LABEL_PRESENT_IN_FEATURES")
    decision_time = parse_utc(snapshot.get("decision_time"))
    feature_cutoff = parse_utc(snapshot.get("feature_cutoff"))
    available_at = parse_utc(snapshot.get("available_at"))
    if decision_time is None:
        reasons.append("DECISION_TIME_MISSING")
    if feature_cutoff is None:
        reasons.append("FEATURE_CUTOFF_MISSING")
    if available_at is None:
        reasons.append("AVAILABLE_AT_MISSING")
    if feature_cutoff is not None and decision_time is not None and feature_cutoff > decision_time:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if available_at is not None and decision_time is not None and available_at > decision_time:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if snapshot.get("candle_closed_confirmed") is not True:
        reasons.append("OPEN_CANDLE_REJECTED")
    if snapshot.get("mtf_snapshot_id") in (None, ""):
        reasons.append("MTF_SNAPSHOT_ID_MISSING")
    return sorted(set(reasons))


def freeze_dataset_from_archive(
    *,
    archive_root: Path,
    scan_limit: int = 60_000,
    replay_limit: int = 30_000,
) -> DatasetFreeze:
    snapshots = list(iter_snapshots(archive_root, limit=scan_limit))
    archive_candles: dict[tuple[str, str], list[dict[str, Any]]] = {}
    rejections: Counter[str] = Counter()
    for snapshot in snapshots:
        candle, reasons = snapshot_to_final_candle(snapshot)
        if candle is None:
            rejections.update(reasons)
            continue
        pair = (str(candle.get("symbol") or "").upper(), str(candle.get("timeframe") or ""))
        archive_candles.setdefault(pair, []).append(candle)
    for rows in archive_candles.values():
        rows.sort(key=lambda row: str(row.get("candle_close_time") or ""))

    out: list[EdgeRecoveryRow] = []
    for snapshot in snapshots:
        reasons = _row_reject_reasons(snapshot)
        if reasons:
            rejections.update(reasons)
            continue
        pair = (str(snapshot.get("symbol") or "").upper(), str(snapshot.get("timeframe") or ""))
        replay_row, replay_reasons = build_trusted_replay_row(
            snapshot,
            candles=archive_candles.get(pair) or [],
        )
        if replay_row is None:
            rejections.update(replay_reasons)
            continue
        features = numeric_features_from_snapshot(snapshot)
        if not features:
            rejections.update(["NO_NUMERIC_FEATURES"])
            continue
        out.append(
            EdgeRecoveryRow(
                sample_id=str(replay_row.get("sample_id") or ""),
                snapshot_id=str(snapshot.get("snapshot_id") or snapshot.get("feature_snapshot_id") or ""),
                symbol=str(snapshot.get("symbol") or "").upper(),
                timeframe=str(snapshot.get("timeframe") or ""),
                decision_time=str(replay_row.get("decision_time") or snapshot.get("decision_time") or ""),
                feature_cutoff=str(replay_row.get("feature_cutoff") or snapshot.get("feature_cutoff") or ""),
                available_at=str(replay_row.get("available_at") or snapshot.get("available_at") or ""),
                future_return_after_cost_bps=float(replay_row["future_return_after_cost_bps"]),
                target_action=str(replay_row.get("target_action") or ""),
                features=features,
            )
        )
        if replay_limit and len(out) >= int(replay_limit):
            break

    out.sort(key=lambda row: (row.decision_time, row.sample_id))
    manifest = build_split_manifest(out)
    manifest.update(
        {
            "schema_version": SCHEMA_VERSION + "_dataset_freeze",
            "generated_utc": utc_now(),
            "archive_root": str(archive_root),
            "snapshots_scanned": len(snapshots),
            "trusted_replay_rows": len(out),
            "replay_limit": int(replay_limit),
            "scan_limit": int(scan_limit),
            "future_labels_used_as_features": False,
            "paper_only": True,
            "routes_to_live": False,
        }
    )
    return DatasetFreeze(rows=out, manifest=manifest, rejections_by_reason=dict(sorted(rejections.items())))


def build_split_manifest(rows: Sequence[EdgeRecoveryRow]) -> dict[str, Any]:
    total = len(rows)
    train_end = int(total * 0.70)
    validation_end = int(total * 0.85)
    return {
        "split_method": "STRICT_TEMPORAL_ORDER_NO_RANDOM_ROW_SPLIT",
        "temporal_overlap": False,
        "training_window": {
            "rows": train_end,
            "start_decision_time": rows[0].decision_time if train_end else None,
            "end_decision_time": rows[train_end - 1].decision_time if train_end else None,
        },
        "validation_window": {
            "rows": validation_end - train_end,
            "start_decision_time": rows[train_end].decision_time if validation_end > train_end else None,
            "end_decision_time": rows[validation_end - 1].decision_time if validation_end > train_end else None,
        },
        "holdout_window": {
            "rows": total - validation_end,
            "start_decision_time": rows[validation_end].decision_time if total > validation_end else None,
            "end_decision_time": rows[-1].decision_time if total > validation_end else None,
        },
    }


def select_feature_names(rows: Sequence[EdgeRecoveryRow], *, max_features: int = 256) -> list[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(row.features.keys())
    return [
        name
        for name, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if _feature_name_allowed(name)
    ][:max_features]


def _matrix(rows: Sequence[EdgeRecoveryRow], feature_names: Sequence[str]):
    import numpy as np

    return np.array(
        [
            [float(row.features.get(name, 0.0)) for name in feature_names]
            for row in rows
        ],
        dtype=float,
    )


def _targets(rows: Sequence[EdgeRecoveryRow]):
    import numpy as np

    return np.array([float(row.future_return_after_cost_bps) for row in rows], dtype=float)


def _actions_from_predictions(predictions: Any, threshold_bps: float):
    import numpy as np

    threshold = float(threshold_bps)
    return np.where(predictions >= threshold, 1, np.where(predictions <= -threshold, -1, 0))


def evaluate_predictions(
    *,
    rows: Sequence[EdgeRecoveryRow],
    predictions: Sequence[float],
    threshold_bps: float,
) -> dict[str, Any]:
    import numpy as np

    y = _targets(rows)
    pred = np.array(list(predictions), dtype=float)
    actions = _actions_from_predictions(pred, threshold_bps)
    pnl = np.where(actions == 1, y, np.where(actions == -1, -y, 0.0))
    trade_mask = actions != 0
    trade_count = int(trade_mask.sum())
    false_positive_count = int(((pnl <= 0.0) & trade_mask).sum())
    true_positive_count = int(((pnl > 0.0) & trade_mask).sum())
    return {
        "sample_count": len(rows),
        "trade_count": trade_count,
        "hold_count": int((actions == 0).sum()),
        "long_count": int((actions == 1).sum()),
        "short_count": int((actions == -1).sum()),
        "coverage": (trade_count / len(rows)) if rows else 0.0,
        "directional_accuracy": (true_positive_count / trade_count) if trade_count else None,
        "false_positive_rate": (false_positive_count / trade_count) if trade_count else None,
        "after_cost_expectancy_bps": float(pnl[trade_mask].mean()) if trade_count else None,
        "expected_move_mae_bps": float(np.abs(pred - y).mean()) if len(rows) else None,
        "true_positive_count": true_positive_count,
        "false_positive_count": false_positive_count,
        "expectancy_scope": "directional_challenger_trades_only",
    }


def train_challenger_model(
    *,
    train_rows: Sequence[EdgeRecoveryRow],
    validation_rows: Sequence[EdgeRecoveryRow],
    max_features: int = 256,
    ridge_lambdas: Sequence[float] = DEFAULT_RIDGE_LAMBDAS,
    thresholds_bps: Sequence[float] = DEFAULT_THRESHOLDS_BPS,
    min_validation_trades: int = 100,
    model_feature_cap: int | None = DEFAULT_MODEL_FEATURE_CAP,
    target_clip_bps: float | None = DEFAULT_TARGET_CLIP_BPS,
) -> ChallengerModel:
    import numpy as np

    if not train_rows:
        raise ValueError("train_rows_required")
    if not validation_rows:
        raise ValueError("validation_rows_required")
    feature_limit = min(int(max_features), int(model_feature_cap)) if model_feature_cap else int(max_features)
    feature_names = select_feature_names(train_rows, max_features=feature_limit)
    if not feature_names:
        raise ValueError("numeric_feature_names_required")
    x_train = _matrix(train_rows, feature_names)
    raw_y_train = _targets(train_rows)
    clip_bps = float(target_clip_bps) if target_clip_bps is not None else None
    y_train = np.clip(raw_y_train, -clip_bps, clip_bps) if clip_bps and clip_bps > 0 else raw_y_train
    x_val = _matrix(validation_rows, feature_names)
    means = x_train.mean(axis=0)
    stds = x_train.std(axis=0)
    stds[stds < 1e-9] = 1.0
    xs_train = (x_train - means) / stds
    xs_val = (x_val - means) / stds
    x_design = np.c_[np.ones(xs_train.shape[0]), xs_train]
    best: tuple[float, float, float, Any, dict[str, Any]] | None = None
    for ridge_lambda in ridge_lambdas:
        penalty = float(ridge_lambda) * np.eye(x_design.shape[1])
        penalty[0, 0] = 0.0
        try:
            coef = np.linalg.solve(x_design.T @ x_design + penalty, x_design.T @ y_train)
        except np.linalg.LinAlgError:
            coef = np.linalg.pinv(x_design.T @ x_design + penalty) @ x_design.T @ y_train
        val_pred = np.c_[np.ones(xs_val.shape[0]), xs_val] @ coef
        for threshold in thresholds_bps:
            metrics = evaluate_predictions(
                rows=validation_rows,
                predictions=val_pred,
                threshold_bps=float(threshold),
            )
            if metrics["trade_count"] < int(min_validation_trades):
                continue
            expectancy = metrics["after_cost_expectancy_bps"]
            if expectancy is None:
                continue
            # Validation selects only model hyperparameters. Holdout remains untouched.
            score = float(expectancy) + 10.0 * float(metrics["directional_accuracy"] or 0.0)
            if best is None or score > best[0]:
                best = (score, float(ridge_lambda), float(threshold), coef, metrics)
    if best is None:
        raise ValueError("no_validation_candidate_met_minimum_trade_count")
    _score, ridge_lambda, threshold, coef, validation_metrics = best
    return ChallengerModel(
        feature_names=list(feature_names),
        means=[float(v) for v in means],
        stds=[float(v) for v in stds],
        weights=[float(v) for v in coef[1:]],
        bias=float(coef[0]),
        ridge_lambda=ridge_lambda,
        threshold_bps=threshold,
        validation_metrics=validation_metrics,
        target_transform="clipped_future_return_after_cost_bps"
        if clip_bps and clip_bps > 0
        else "raw_future_return_after_cost_bps",
        target_clip_bps=clip_bps if clip_bps and clip_bps > 0 else None,
        feature_count_limit=feature_limit,
    )


def predict_rows(model: ChallengerModel, rows: Sequence[EdgeRecoveryRow]) -> list[float]:
    return [model.predict(row.features) for row in rows]


def _split_rows(rows: Sequence[EdgeRecoveryRow]) -> tuple[list[EdgeRecoveryRow], list[EdgeRecoveryRow], list[EdgeRecoveryRow]]:
    total = len(rows)
    train_end = int(total * 0.70)
    validation_end = int(total * 0.85)
    return list(rows[:train_end]), list(rows[train_end:validation_end]), list(rows[validation_end:])


def _improvement_status(holdout_metrics: Mapping[str, Any]) -> dict[str, Any]:
    directional = finite_float(holdout_metrics.get("directional_accuracy"))
    mae = finite_float(holdout_metrics.get("expected_move_mae_bps"))
    false_positive = finite_float(holdout_metrics.get("false_positive_rate"))
    expectancy = finite_float(holdout_metrics.get("after_cost_expectancy_bps"))
    return {
        "directional_accuracy_improved": directional is not None and directional > CHAMPION_BASELINE["directional_accuracy"],
        "expected_move_mae_improved": mae is not None and mae < CHAMPION_BASELINE["expected_move_mae_bps"],
        "false_positive_rate_improved": false_positive is not None and false_positive < CHAMPION_BASELINE["false_positive_rate"],
        "after_cost_expectancy_improved": expectancy is not None and expectancy > CHAMPION_BASELINE["after_cost_expectancy_bps"],
        "positive_after_cost_expectancy": expectancy is not None and expectancy > 0.0,
    }


def run_champion_challenger(
    *,
    repo_root: Path,
    scan_limit: int = 60_000,
    replay_limit: int = 30_000,
    min_train_rows: int = 1000,
    min_validation_trades: int = 100,
    min_holdout_trades: int = 100,
    max_features: int = 256,
    archive_root: Path | None = None,
) -> dict[str, Any]:
    archive_root = archive_root or default_archive_root(repo_root)
    freeze = freeze_dataset_from_archive(
        archive_root=archive_root,
        scan_limit=scan_limit,
        replay_limit=replay_limit,
    )
    train_rows, validation_rows, holdout_rows = _split_rows(freeze.rows)
    status = "BLOCKED_INSUFFICIENT_TRUSTED_REPLAY_ROWS"
    model: ChallengerModel | None = None
    train_metrics = validation_metrics = holdout_metrics = None
    blocker_reasons: list[str] = []
    if len(train_rows) < int(min_train_rows):
        blocker_reasons.append("INSUFFICIENT_TRAIN_ROWS")
    if not validation_rows:
        blocker_reasons.append("VALIDATION_ROWS_MISSING")
    if not holdout_rows:
        blocker_reasons.append("HOLDOUT_ROWS_MISSING")
    if not blocker_reasons:
        try:
            model = train_challenger_model(
                train_rows=train_rows,
                validation_rows=validation_rows,
                max_features=max_features,
                min_validation_trades=min_validation_trades,
            )
        except ValueError as exc:
            blocker_reasons.append(str(exc).upper())
            status = "BLOCKED_VALIDATION_CANDIDATE_NOT_PROVEN"
            improvements = {}
        else:
            train_metrics = evaluate_predictions(
                rows=train_rows,
                predictions=predict_rows(model, train_rows),
                threshold_bps=model.threshold_bps,
            )
            validation_metrics = model.validation_metrics
            holdout_predictions = predict_rows(model, holdout_rows)
            holdout_metrics = evaluate_predictions(
                rows=holdout_rows,
                predictions=holdout_predictions,
                threshold_bps=model.threshold_bps,
            )
            improvements = _improvement_status(holdout_metrics)
            if holdout_metrics["trade_count"] < int(min_holdout_trades):
                blocker_reasons.append("INSUFFICIENT_HOLDOUT_TRADES")
            for name, passed in improvements.items():
                if not passed:
                    blocker_reasons.append(name.upper() + "_FAILED")
            status = "PASSED_PAPER_CHALLENGER_READY" if not blocker_reasons else "BLOCKED_HOLDOUT_EDGE_NOT_PROVEN"
    else:
        improvements = {}

    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "status": status,
        "blocker_reasons": sorted(set(blocker_reasons)),
        "champion_baseline": CHAMPION_BASELINE,
        "dataset_freeze": freeze.manifest,
        "rejections_by_reason": freeze.rejections_by_reason,
        "row_counts": {
            "train": len(train_rows),
            "validation": len(validation_rows),
            "untouched_holdout": len(holdout_rows),
        },
        "point_in_time_safety": {
            "future_labels_used_as_features": False,
            "feature_available_at_after_decision_rejected": freeze.rejections_by_reason.get("AVAILABLE_AT_AFTER_DECISION_TIME", 0),
            "feature_cutoff_after_decision_rejected": freeze.rejections_by_reason.get("FEATURE_CUTOFF_AFTER_DECISION_TIME", 0),
            "open_candle_rejected": freeze.rejections_by_reason.get("OPEN_CANDLE_REJECTED", 0),
            "temporal_overlap": False,
        },
        "model": model.to_jsonable() if model else None,
        "train_metrics": train_metrics,
        "validation_metrics": validation_metrics,
        "untouched_holdout_metrics": holdout_metrics,
        "holdout_improvement": improvements,
        "paper_challenger_policy": {
            "enabled": status == "PASSED_PAPER_CHALLENGER_READY",
            "paper_opportunity_tier": PAPER_CHALLENGER_TIER,
            "paper_fill_allowed_upstream": False,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_a_grade_evidence": False,
            "a_grade_promotion_allowed": False,
            "live_ready_implication": False,
        },
        "safety": {
            "paper_only": True,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        },
    }
    result["result_hash"] = stable_hash(_stable_result_material(result))
    return result


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def emit_artifacts(repo_root: Path, result: Mapping[str, Any]) -> list[Path]:
    paths = [
        repo_root / "goal_state" / GOAL_ID / "model_edge_recovery_champion_challenger_status.json",
        repo_root / "v2/frontend/public" / ARTIFACT_REL / "model_edge_recovery_champion_challenger_status.json",
    ]
    for path in paths:
        _write_json(path, result)
    return paths


def _trust_row_for_current_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    decision_time = (
        snapshot.get("decision_time")
        or snapshot.get("decision_time_est")
        or snapshot.get("decision_cutoff_time_est")
        or snapshot.get("generated_at")
    )
    feature_cutoff = (
        snapshot.get("feature_cutoff")
        or snapshot.get("candle_close_time")
        or snapshot.get("source_event_time_est")
    )
    available_at = (
        snapshot.get("available_at")
        or snapshot.get("source_available_time")
        or snapshot.get("generated_at")
    )
    return {
        "symbol": str(snapshot.get("symbol") or "").upper(),
        "timeframe": str(snapshot.get("timeframe") or ""),
        "feature_snapshot_id": snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id"),
        "feature_vector_hash": hashlib.sha256(_canonical_json(features).encode("utf-8")).hexdigest(),
        "generated_at": snapshot.get("generated_at") or snapshot.get("generated_utc") or decision_time,
        "feature_cutoff": feature_cutoff,
        "available_at": available_at,
        "decision_time_est": decision_time,
        "source_event_time_est": snapshot.get("source_event_time_est") or feature_cutoff,
        "source_received_time_est": snapshot.get("source_received_time_est") or available_at,
        "source_available_time": snapshot.get("source_available_time") or available_at,
        "candle_closed_confirmed": snapshot.get("candle_closed_confirmed"),
        "candle_open_time": snapshot.get("candle_open_time"),
        "candle_close_time": snapshot.get("candle_close_time") or feature_cutoff,
        "feature_freshness_state": snapshot.get("feature_freshness_state"),
        "trainer_consumable": snapshot.get("trainer_consumable") is not False,
        "row_classification": "TRAINABLE",
        "missing_feature_count": snapshot.get("missing_feature_count") or 0,
        "missing_feature_names": list(snapshot.get("missing_feature_flags") or []),
        "stale_feature_count": len(snapshot.get("stale_feature_flags") or []),
        "stale_feature_names": list(snapshot.get("stale_feature_flags") or []),
        "features": dict(features),
    }


def build_paper_challenger_signal(
    *,
    model: ChallengerModel,
    snapshot: Mapping[str, Any],
    result_hash: str,
) -> dict[str, Any] | None:
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    if not features:
        return None
    if any(not _feature_name_allowed(str(name)) for name in features):
        return None
    prediction = model.predict(features)
    if abs(prediction) < model.threshold_bps:
        return None
    side = "long" if prediction > 0.0 else "short"
    trust_row = _trust_row_for_current_snapshot(snapshot)
    trust = classify_training_sample(trust_row)
    if trust["accepted_for_training"] is not True:
        return None
    confidence = min(0.74, max(0.50, 0.50 + min(abs(prediction) / max(model.threshold_bps, 1.0), 1.0) * 0.20))
    snapshot_id = str(snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id") or "")
    symbol = str(snapshot.get("symbol") or "").upper()
    timeframe = str(snapshot.get("timeframe") or "")
    signal_id = "sig_model_edge_recovery_" + stable_hash({
        "snapshot_id": snapshot_id,
        "side": side,
        "result_hash": result_hash,
    })[:24]
    return {
        "signal_id": signal_id,
        "winner_proposal_id": signal_id,
        "prediction_id": "pred_model_edge_recovery_" + stable_hash({"snapshot_id": snapshot_id, "result_hash": result_hash})[:24],
        "symbol": symbol,
        "timeframe": timeframe,
        "side": side,
        "action": side,
        "selected_action": side,
        "expected_move_after_cost_bps": float(prediction),
        "expected_move_bps": float(prediction),
        "confidence_calibrated": round(float(confidence), 8),
        "confidence_raw": round(float(confidence), 8),
        "paper_opportunity_tier": PAPER_CHALLENGER_TIER,
        "paper_execution_tier": PAPER_CHALLENGER_TIER,
        "paper_fill_allowed": False,
        "paper_fill_gate_status": "BLOCKED_STRICT_GATE_CHALLENGER_LOCAL_ONLY",
        "paper_fill_gate_block_reasons": ["MODEL_EDGE_RECOVERY_CHALLENGER_B_GRADE_LOCAL_PAPER_ONLY"],
        "valid_for_paper": True,
        "market_state_id": trust.get("market_state_id"),
        "market_state_integrity_score": trust.get("market_state_integrity_score"),
        "market_state_reject_reasons": [],
        "feature_snapshot_id": snapshot_id,
        "feature_cutoff": trust_row.get("feature_cutoff"),
        "decision_time": trust_row.get("decision_time_est"),
        "available_at": trust_row.get("available_at"),
        "generated_utc": utc_now(),
        "trainer_source": MODEL_SOURCE,
        "model_source": MODEL_SOURCE,
        "model_version": result_hash,
        "checkpoint_id": None,
        "source_hashes": snapshot.get("source_hashes") or {},
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "counts_as_a_grade_evidence": False,
        "a_grade_promotion_allowed": False,
        "live_ready_implication": False,
        "future_labels_used_as_features": False,
    }


def publish_paper_challenger_signals(
    *,
    client: Any,
    result: Mapping[str, Any],
    max_signals: int = 5,
) -> dict[str, Any]:
    if result.get("status") != "PASSED_PAPER_CHALLENGER_READY":
        return {
            "status": "NOT_PUBLISHED_HOLDOUT_EDGE_NOT_PROVEN",
            "published_count": 0,
            "paper_only": True,
            "routes_to_live": False,
        }
    model_payload = result.get("model") if isinstance(result.get("model"), Mapping) else None
    if not model_payload:
        return {"status": "NOT_PUBLISHED_MODEL_MISSING", "published_count": 0}
    model = ChallengerModel(
        feature_names=list(model_payload["feature_names"]),
        means=[float(v) for v in model_payload["means"]],
        stds=[float(v) for v in model_payload["stds"]],
        weights=[float(v) for v in model_payload["weights"]],
        bias=float(model_payload["bias"]),
        ridge_lambda=float(model_payload["ridge_lambda"]),
        threshold_bps=float(model_payload["threshold_bps"]),
        validation_metrics=dict(model_payload.get("validation_metrics") or {}),
    )
    keys = list(client.scan_iter("v2:features:latest:*", count=1000))
    published: list[str] = []
    rejected = 0
    for key in keys:
        if len(published) >= int(max_signals):
            break
        try:
            raw = client.get(key)
            snapshot = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            rejected += 1
            continue
        if not isinstance(snapshot, Mapping):
            rejected += 1
            continue
        signal = build_paper_challenger_signal(
            model=model,
            snapshot=snapshot,
            result_hash=str(result.get("result_hash") or ""),
        )
        if signal is None:
            rejected += 1
            continue
        out_key = f"v2:signals:paper:challenger:model_edge_recovery:{signal['symbol']}:{signal['timeframe']}"
        client.set(out_key, json.dumps(signal, sort_keys=True, default=str), ex=900)
        published.append(out_key)
    return {
        "status": "PUBLISHED_PAPER_ONLY_CHALLENGER_SIGNALS" if published else "NO_CURRENT_CHALLENGER_SIGNAL_ELIGIBLE",
        "published_count": len(published),
        "rejected_count": rejected,
        "keys_written": published,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
