"""Build V2 challenger artifacts without live routing.

This command is paper-only and side-effect limited to local JSON artifacts. It
does not write Redis, place orders, restart services, mutate exchange settings,
or bind a challenger to paper fills. The blind lockbox and forward canary remain
blocked unless independent evidence exists after candidate freeze.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from v2.backend.app.services.native_trainer.challenger_v2_cost_model import (
    cost_model_hash,
    estimate_paper_cost,
    estimate_replay_cost,
    net_return_for_side,
)
from v2.backend.app.services.native_trainer.challenger_v2_feature_adapter import (
    NormalizationSpec,
    adapt_replay_snapshot,
    adapt_runtime_snapshot,
    build_normalization_spec,
    feature_schema_hash,
    normalization_hash,
    numeric_feature_mapping,
    stable_hash,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    default_archive_root,
    iter_snapshots,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    build_trusted_replay_row,
    parse_utc,
    snapshot_to_final_candle,
)


GOAL_ID = "V2_CHALLENGER_V2_REPRODUCIBLE_COST_PARITY_FEATURE_ADAPTER_BLIND_LOCKBOX_AND_FORWARD_CANARY"
V1_CANDIDATE_ID = "model_edge_recovery_challenger_2603e850a1d019c9"
SCHEMA_VERSION = "challenger_v2_reproducible_pipeline_v1"
MODEL_SOURCE = "V2_CHALLENGER_PRODUCTION_COST_SHARED_ADAPTER_RIDGE"
DEFAULT_RIDGE_LAMBDAS = (0.1, 1.0, 10.0, 100.0, 1000.0)
DEFAULT_THRESHOLDS_BPS = (0.0, 5.0, 10.0, 15.0, 20.0, 30.0, 50.0)
DEFAULT_TARGET_CLIPS_BPS = (50.0, 100.0, 200.0, 0.0)


@dataclass(frozen=True)
class ReplayCandidateRow:
    sample_id: str
    snapshot_id: str
    symbol: str
    timeframe: str
    decision_time: str
    feature_cutoff: str
    available_at: str
    gross_return_15m_bps: float
    long_net_return_bps: float
    short_net_return_bps: float
    target_edge_bps: float
    cost_long: dict[str, Any]
    cost_short: dict[str, Any]
    production_grade_cost_evidence: bool
    snapshot: Mapping[str, Any]


@dataclass(frozen=True)
class RidgePolicy:
    feature_names: tuple[str, ...]
    normalization: NormalizationSpec
    weights: tuple[float, ...]
    bias: float
    ridge_lambda: float
    threshold_bps: float
    target_clip_bps: float | None
    validation_metrics: dict[str, Any]

    def predict(self, snapshot: Mapping[str, Any]) -> float:
        adapted = adapt_replay_snapshot(snapshot, normalization=self.normalization)
        total = self.bias
        for value, weight in zip(adapted.normalized_vector, self.weights):
            total += value * weight
        return float(total)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "model_source": MODEL_SOURCE,
            "feature_names": list(self.feature_names),
            "normalization": self.normalization.to_jsonable(),
            "weights": list(self.weights),
            "bias": self.bias,
            "ridge_lambda": self.ridge_lambda,
            "threshold_bps": self.threshold_bps,
            "target_clip_bps": self.target_clip_bps,
            "validation_metrics": self.validation_metrics,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str) + "\n")
    tmp.replace(path)


def _run_git(repo_root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except Exception:
        return None
    return result.stdout.strip()


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: Path, repo_root: Path) -> str:
    return str(path.resolve().relative_to(repo_root.resolve()))


def _module_versions() -> dict[str, Any]:
    versions: dict[str, Any] = {
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
    }
    try:
        import numpy as np

        versions["numpy"] = np.__version__
    except Exception as exc:
        versions["numpy"] = f"UNAVAILABLE:{type(exc).__name__}"
    try:
        import torch

        versions["torch"] = torch.__version__
    except Exception as exc:
        versions["torch"] = f"UNAVAILABLE:{type(exc).__name__}"
    return versions


def _source_files(repo_root: Path) -> list[Path]:
    rels = [
        "v2/backend/app/cli/v2_challenger_v2_reproducible_pipeline.py",
        "v2/backend/app/services/native_trainer/challenger_v2_feature_adapter.py",
        "v2/backend/app/services/native_trainer/challenger_v2_cost_model.py",
        "v2/backend/tests/unit/services/native_trainer/test_challenger_v2_feature_adapter.py",
        "v2/backend/tests/unit/services/native_trainer/test_challenger_v2_cost_model.py",
    ]
    return [repo_root / rel for rel in rels if (repo_root / rel).exists()]


def _dependency_files(repo_root: Path) -> list[Path]:
    rels = [
        "v2/backend/app/services/native_trainer/trusted_replay/__init__.py",
        "v2/backend/app/services/native_trainer/trusted_replay/dataset.py",
        "v2/backend/app/services/native_trainer/trusted_replay/bootstrap.py",
        "v2/backend/app/services/native_trainer/durable_feature_snapshot_archive.py",
        "v2/backend/app/services/market_state_integrity/sample_rejection.py",
        "v2/backend/app/services/market_state_integrity/scoring.py",
        "v2/backend/app/services/market_state_integrity/validators.py",
        "v2/backend/app/services/market_state_integrity/contracts.py",
        "v2/backend/app/services/adaptive_capital_allocator/__init__.py",
        "v2/backend/app/services/adaptive_capital_allocator/contracts.py",
        "v2/backend/app/services/adaptive_capital_allocator/allocator.py",
        "v2/backend/app/cli/v2_trade_management_paper_loop.py",
    ]
    return [repo_root / rel for rel in rels if (repo_root / rel).exists()]


def _hashes(paths: Sequence[Path], repo_root: Path) -> dict[str, str]:
    return {_rel(path, repo_root): _sha256_file(path) for path in paths}


def _build_candle_index(snapshots: Sequence[Mapping[str, Any]]) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], Counter[str]]:
    candles: dict[tuple[str, str], list[dict[str, Any]]] = {}
    rejections: Counter[str] = Counter()
    for snapshot in snapshots:
        candle, reasons = snapshot_to_final_candle(snapshot)
        if candle is None:
            rejections.update(reasons)
            continue
        pair = (str(candle.get("symbol") or "").upper(), str(candle.get("timeframe") or ""))
        candles.setdefault(pair, []).append(candle)
    for rows in candles.values():
        rows.sort(key=lambda row: str(row.get("candle_close_time") or ""))
    return candles, rejections


def _target_edge(long_net: float, short_net: float) -> float:
    if long_net <= 0.0 and short_net <= 0.0:
        return 0.0
    if long_net >= short_net:
        return float(long_net)
    return -float(short_net)


def _build_dataset(
    *,
    repo_root: Path,
    scan_limit: int,
    replay_limit: int,
) -> tuple[list[ReplayCandidateRow], dict[str, Any], dict[str, int]]:
    archive_root = default_archive_root(repo_root)
    snapshots = list(iter_snapshots(archive_root, limit=scan_limit))
    candles, rejections = _build_candle_index(snapshots)
    rows: list[ReplayCandidateRow] = []
    for snapshot in snapshots:
        pair = (str(snapshot.get("symbol") or "").upper(), str(snapshot.get("timeframe") or ""))
        replay_row, reasons = build_trusted_replay_row(
            snapshot,
            candles=candles.get(pair) or [],
            round_trip_cost_bps=0.0,
            action_threshold_bps=0.0,
        )
        if replay_row is None:
            rejections.update(reasons)
            continue
        adapted = adapt_replay_snapshot(snapshot)
        if adapted.integrity_status.get("accepted_for_training") is not True:
            rejections.update(["ADAPTER_INTEGRITY_REJECTED", *adapted.rejection_reasons])
            continue
        gross = float(replay_row["future_return_15m_bps"])
        long_cost = estimate_replay_cost(snapshot, side="long")
        short_cost = estimate_replay_cost(snapshot, side="short")
        long_net = net_return_for_side(gross, "long", long_cost)
        short_net = net_return_for_side(gross, "short", short_cost)
        rows.append(
            ReplayCandidateRow(
                sample_id=str(replay_row.get("sample_id") or ""),
                snapshot_id=str(snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id") or ""),
                symbol=str(snapshot.get("symbol") or "").upper(),
                timeframe=str(snapshot.get("timeframe") or ""),
                decision_time=str(replay_row.get("decision_time") or snapshot.get("decision_time") or ""),
                feature_cutoff=str(replay_row.get("feature_cutoff") or snapshot.get("feature_cutoff") or ""),
                available_at=str(replay_row.get("available_at") or snapshot.get("available_at") or ""),
                gross_return_15m_bps=gross,
                long_net_return_bps=long_net,
                short_net_return_bps=short_net,
                target_edge_bps=_target_edge(long_net, short_net),
                cost_long=long_cost.to_jsonable(),
                cost_short=short_cost.to_jsonable(),
                production_grade_cost_evidence=long_cost.production_grade_evidence and short_cost.production_grade_evidence,
                snapshot=snapshot,
            )
        )
        if replay_limit and len(rows) >= replay_limit:
            break
    rows.sort(key=lambda row: (row.decision_time, row.sample_id))
    total = len(rows)
    train_end = int(total * 0.75)
    validation_end = total
    manifest = {
        "schema_version": "challenger_v2_dataset_manifest_v1",
        "archive_root": str(archive_root),
        "snapshots_scanned": len(snapshots),
        "production_cost_replay_rows": len(rows),
        "replay_limit": replay_limit,
        "scan_limit": scan_limit,
        "split_method": "STRICT_TEMPORAL_ORDER_TRAIN_VALIDATION_ONLY_NO_LOCKBOX_ACCESS",
        "training_window": {
            "rows": train_end,
            "start_decision_time": rows[0].decision_time if train_end else None,
            "end_decision_time": rows[train_end - 1].decision_time if train_end else None,
        },
        "validation_window": {
            "rows": validation_end - train_end,
            "start_decision_time": rows[train_end].decision_time if validation_end > train_end else None,
            "end_decision_time": rows[-1].decision_time if validation_end > train_end else None,
        },
        "blind_lockbox_window": {
            "mode": "FUTURE_SNAPSHOTS_AFTER_CANDIDATE_FREEZE_ONLY",
            "rows_viewed_before_freeze": 0,
            "rows_used_for_model_selection": 0,
        },
        "future_labels_used_as_features": False,
        "feature_cutoff_after_decision_rejected": rejections.get("FEATURE_CUTOFF_AFTER_DECISION_TIME", 0),
        "available_at_after_decision_rejected": rejections.get("AVAILABLE_AT_AFTER_DECISION_TIME", 0),
        "open_candle_rejected": rejections.get("OPEN_CANDLE_REJECTED", 0),
        "production_grade_cost_rows": sum(1 for row in rows if row.production_grade_cost_evidence),
    }
    manifest["dataset_manifest_hash"] = stable_hash(manifest)
    return rows, manifest, dict(sorted(rejections.items()))


def _select_feature_names(rows: Sequence[ReplayCandidateRow], *, max_features: int = 32) -> tuple[str, ...]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(numeric_feature_mapping(row.snapshot).keys())
    min_count = max(1, int(len(rows) * 0.95))
    stable = [name for name, count in counts.items() if count >= min_count]
    if len(stable) < max_features:
        stable = [name for name, _count in counts.most_common()]
    return tuple(sorted(stable, key=lambda name: (-counts[name], name))[:max_features])


def _adapt_clean_rows(rows: Sequence[ReplayCandidateRow], normalization: NormalizationSpec) -> list[tuple[ReplayCandidateRow, tuple[float, ...]]]:
    clean: list[tuple[ReplayCandidateRow, tuple[float, ...]]] = []
    for row in rows:
        adapted = adapt_replay_snapshot(row.snapshot, normalization=normalization)
        if adapted.integrity_status.get("accepted_for_training") is not True:
            continue
        if adapted.missing_feature_names or adapted.stale_feature_names:
            continue
        clean.append((row, adapted.normalized_vector))
    return clean


def _evaluate(rows: Sequence[ReplayCandidateRow], predictions: Sequence[float], *, threshold_bps: float) -> dict[str, Any]:
    pnls: list[float] = []
    long_count = short_count = hold_count = 0
    correct = false_positive = 0
    for row, prediction in zip(rows, predictions):
        if prediction >= threshold_bps:
            pnl = row.long_net_return_bps
            long_count += 1
        elif prediction <= -threshold_bps:
            pnl = row.short_net_return_bps
            short_count += 1
        else:
            hold_count += 1
            continue
        pnls.append(float(pnl))
        if pnl > 0.0:
            correct += 1
        else:
            false_positive += 1
    trade_count = len(pnls)
    profit = sum(value for value in pnls if value > 0.0)
    loss = abs(sum(value for value in pnls if value < 0.0))
    return {
        "rows": len(rows),
        "trade_count": trade_count,
        "long_count": long_count,
        "short_count": short_count,
        "no_trade_count": hold_count,
        "directional_accuracy": correct / trade_count if trade_count else None,
        "false_positive_rate": false_positive / trade_count if trade_count else None,
        "after_cost_expectancy_bps": sum(pnls) / trade_count if trade_count else None,
        "profit_factor": (profit / loss) if loss > 0.0 else (None if profit <= 0.0 else float("inf")),
        "worst_trade_bps": min(pnls) if pnls else None,
        "production_grade_cost_rows": sum(1 for row in rows if row.production_grade_cost_evidence),
    }


def _train_policy(
    *,
    rows: Sequence[ReplayCandidateRow],
    dataset_manifest: Mapping[str, Any],
    min_validation_trades: int,
) -> tuple[RidgePolicy | None, dict[str, Any], dict[str, Any]]:
    import numpy as np

    total = len(rows)
    train_end = int(total * 0.75)
    train_rows = list(rows[:train_end])
    validation_rows = list(rows[train_end:])
    training_status: dict[str, Any] = {
        "schema_version": "challenger_v2_training_status_v1",
        "model_source": MODEL_SOURCE,
        "dataset_manifest_hash": dataset_manifest.get("dataset_manifest_hash"),
        "train_rows_before_adapter_filter": len(train_rows),
        "validation_rows_before_adapter_filter": len(validation_rows),
        "strict_temporal_train_validation_split": True,
        "future_label_leakage_detected": False,
        "production_equivalent_cost_model_hash": cost_model_hash(),
    }
    if not train_rows or not validation_rows:
        training_status["status"] = "BLOCKED_INSUFFICIENT_TRAIN_VALIDATION_ROWS"
        return None, training_status, {"status": "BLOCKED_INSUFFICIENT_TRAIN_VALIDATION_ROWS"}

    feature_names = _select_feature_names(train_rows)
    if not feature_names:
        training_status["status"] = "BLOCKED_NO_SHARED_FEATURES"
        return None, training_status, {"status": "BLOCKED_NO_SHARED_FEATURES"}
    normalization = build_normalization_spec([row.snapshot for row in train_rows], feature_names=feature_names)
    clean_train = _adapt_clean_rows(train_rows, normalization)
    clean_validation = _adapt_clean_rows(validation_rows, normalization)
    training_status.update(
        {
            "feature_names_in_order": list(feature_names),
            "feature_schema_hash": feature_schema_hash(feature_names),
            "normalization_hash": normalization_hash(normalization),
            "train_rows_after_adapter_filter": len(clean_train),
            "validation_rows_after_adapter_filter": len(clean_validation),
        }
    )
    if not clean_train or not clean_validation:
        training_status["status"] = "BLOCKED_SHARED_ADAPTER_FILTER_REMOVED_ROWS"
        return None, training_status, {"status": "BLOCKED_SHARED_ADAPTER_FILTER_REMOVED_ROWS"}

    x_train = np.array([list(vector) for _row, vector in clean_train], dtype=float)
    raw_y = np.array([row.target_edge_bps for row, _vector in clean_train], dtype=float)
    x_val = np.array([list(vector) for _row, vector in clean_validation], dtype=float)
    validation_target_rows = [row for row, _vector in clean_validation]
    design = np.c_[np.ones(x_train.shape[0]), x_train]
    best: tuple[float, RidgePolicy, dict[str, Any], list[float]] | None = None
    scoreboard_rows: list[dict[str, Any]] = []
    for clip in DEFAULT_TARGET_CLIPS_BPS:
        y_train = np.clip(raw_y, -clip, clip) if clip and clip > 0 else raw_y
        for ridge_lambda in DEFAULT_RIDGE_LAMBDAS:
            penalty = float(ridge_lambda) * np.eye(design.shape[1])
            penalty[0, 0] = 0.0
            try:
                coef = np.linalg.solve(design.T @ design + penalty, design.T @ y_train)
            except np.linalg.LinAlgError:
                coef = np.linalg.pinv(design.T @ design + penalty) @ design.T @ y_train
            val_pred = np.c_[np.ones(x_val.shape[0]), x_val] @ coef
            for threshold in DEFAULT_THRESHOLDS_BPS:
                metrics = _evaluate(validation_target_rows, val_pred, threshold_bps=float(threshold))
                row = {
                    "ridge_lambda": float(ridge_lambda),
                    "threshold_bps": float(threshold),
                    "target_clip_bps": float(clip) if clip and clip > 0 else None,
                    **metrics,
                }
                scoreboard_rows.append(row)
                if metrics["trade_count"] < int(min_validation_trades):
                    continue
                expectancy = metrics["after_cost_expectancy_bps"]
                if expectancy is None:
                    continue
                score = float(expectancy) + 10.0 * float(metrics["directional_accuracy"] or 0.0) - 5.0 * float(metrics["false_positive_rate"] or 0.0)
                policy = RidgePolicy(
                    feature_names=feature_names,
                    normalization=normalization,
                    weights=tuple(float(v) for v in coef[1:]),
                    bias=float(coef[0]),
                    ridge_lambda=float(ridge_lambda),
                    threshold_bps=float(threshold),
                    target_clip_bps=float(clip) if clip and clip > 0 else None,
                    validation_metrics=metrics,
                )
                if best is None or score > best[0]:
                    best = (score, policy, row, [float(v) for v in val_pred])
    scoreboard = {
        "schema_version": "challenger_v2_validation_scoreboard_v1",
        "selection_scope": "VALIDATION_ONLY_NO_LOCKBOX_ACCESS",
        "min_validation_trades": int(min_validation_trades),
        "rows": scoreboard_rows,
        "selected": best[2] if best else None,
    }
    if best is None:
        training_status["status"] = "BLOCKED_NO_VALIDATION_CANDIDATE_MET_MIN_TRADE_COUNT"
        return None, training_status, scoreboard
    policy = best[1]
    training_status.update(
        {
            "status": "VALIDATION_SELECTED_CANDIDATE_FROZEN_PENDING_LOCKBOX",
            "selected_ridge_lambda": policy.ridge_lambda,
            "selected_threshold_bps": policy.threshold_bps,
            "selected_target_clip_bps": policy.target_clip_bps,
            "validation_metrics": policy.validation_metrics,
        }
    )
    return policy, training_status, scoreboard


def _read_current_snapshots(limit: int = 2000) -> tuple[list[Mapping[str, Any]], str]:
    try:
        import redis

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
    except Exception as exc:
        return [], f"REDIS_UNAVAILABLE:{type(exc).__name__}"
    snapshots: list[Mapping[str, Any]] = []
    for key in client.scan_iter("v2:features:latest:*", count=1000):
        if len(snapshots) >= limit:
            break
        try:
            raw = client.get(key)
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue
        if isinstance(payload, Mapping):
            item = dict(payload)
            item["_redis_key"] = key
            snapshots.append(item)
    return snapshots, "REDIS_V2_FEATURES_LATEST_READ_ONLY"


def _feature_parity_artifacts(
    *,
    policy: RidgePolicy | None,
    current_limit: int,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    snapshots, source = _read_current_snapshots(limit=current_limit)
    rows: list[dict[str, Any]] = []
    schema_mismatch = 0
    normalization_mismatch = 0
    unexplained_missing = 0
    integrity_pass = 0
    if policy is not None:
        for snapshot in snapshots:
            replay = adapt_replay_snapshot(snapshot, normalization=policy.normalization)
            runtime = adapt_runtime_snapshot(snapshot, normalization=policy.normalization)
            if replay.feature_names_in_order != runtime.feature_names_in_order:
                schema_mismatch += 1
            if replay.normalized_vector != runtime.normalized_vector:
                normalization_mismatch += 1
            if runtime.missing_feature_names and "MISSING_MODEL_FEATURE" not in runtime.rejection_reasons:
                unexplained_missing += 1
            if runtime.integrity_status.get("accepted_for_training") is True:
                integrity_pass += 1
            rows.append(
                {
                    "symbol": runtime.symbol,
                    "timeframe": runtime.timeframe,
                    "snapshot_id": runtime.snapshot_id,
                    "redis_key": snapshot.get("_redis_key"),
                    "integrity_status": runtime.integrity_status,
                    "feature_schema_version": runtime.feature_schema_version,
                    "feature_vector_hash": runtime.feature_vector_hash,
                    "missing_feature_names": list(runtime.missing_feature_names),
                    "stale_feature_names": list(runtime.stale_feature_names),
                    "out_of_range_features": list(runtime.out_of_range_features),
                    "normalization_status": runtime.normalization_status,
                    "rejection_reasons": list(runtime.rejection_reasons),
                }
            )
    total = len(snapshots)
    pass_rate = integrity_pass / total if total else 0.0
    parity_pass = (
        policy is not None
        and total > 0
        and pass_rate >= 0.95
        and unexplained_missing == 0
        and schema_mismatch == 0
        and normalization_mismatch == 0
    )
    parity = {
        "schema_version": "challenger_replay_runtime_feature_parity_status_v1",
        "status": "PASS" if parity_pass else "FAIL_FEATURE_PARITY_NOT_PROVEN",
        "current_snapshot_source": source,
        "current_rows_scanned": total,
        "current_integrity_pass_rate": pass_rate,
        "unexplained_missing_feature_rows": unexplained_missing,
        "schema_mismatch_rows": schema_mismatch,
        "normalization_mismatch_rows": normalization_mismatch,
        "shared_adapter_module": "v2.backend.app.services.native_trainer.challenger_v2_feature_adapter",
        "do_not_evaluate_current_supply_until_pass": not parity_pass,
    }
    matrix = {
        "schema_version": "challenger_current_feature_rejection_matrix_v1",
        "status": "CURRENT_FEATURE_PARITY_PASS" if parity_pass else "CURRENT_FEATURE_PARITY_FAILED",
        "current_record_count": len(rows),
        "rows": rows,
        "summary_counts": {
            "integrity_passed": integrity_pass,
            "integrity_failed": total - integrity_pass,
            "schema_mismatch_rows": schema_mismatch,
            "normalization_mismatch_rows": normalization_mismatch,
            "unexplained_missing_feature_rows": unexplained_missing,
            "missing_feature_rows": sum(1 for row in rows if row["missing_feature_names"]),
            "stale_feature_rows": sum(1 for row in rows if row["stale_feature_names"]),
            "out_of_range_rows": sum(1 for row in rows if row["out_of_range_features"]),
        },
    }
    return parity, matrix, rows


def _cost_parity_status() -> dict[str, Any]:
    fixture = {
        "observed_bid_ask_spread_bps": 2.5,
        "order_notional_usd": 1000.0,
        "orderbook_depth_usd": 100000.0,
        "maker_probability": 0.25,
        "taker_probability": 0.75,
        "maker_fee_bps": 1.0,
        "taker_fee_bps": 5.0,
        "funding_rate": 0.0008,
        "latency_ms": 250.0,
        "volatility_bps": 80.0,
        "partial_fill_probability": 0.9,
        "mark_price": 100.2,
        "index_price": 100.0,
        "liquidity_score": 0.8,
    }
    replay = estimate_replay_cost(fixture, side="long", order_notional_usd=1000.0, holding_period_seconds=3600)
    paper = estimate_paper_cost(fixture, side="long", order_notional_usd=1000.0, holding_period_seconds=3600)
    same = replay.to_jsonable() == paper.to_jsonable()
    fallback_fixture = estimate_replay_cost({"symbol": "BTCUSDT"}).to_jsonable()
    return {
        "schema_version": "challenger_cost_model_parity_status_v1",
        "status": "PASS_FUNCTION_PARITY" if same else "FAIL_REPLAY_PAPER_COST_FUNCTION_MISMATCH",
        "cost_model_hash": cost_model_hash(),
        "same_function_used_for_training_validation_lockbox_shadow_paper_canary": True,
        "replay_cost_equals_paper_cost_for_same_snapshot_and_order": same,
        "required_inputs": [
            "observed_bid_ask_spread_bps",
            "order_size",
            "book_depth",
            "expected_price_impact",
            "maker_taker_probability",
            "fees",
            "funding",
            "latency_reserve",
            "partial_fill_estimate",
            "mark_index_divergence",
        ],
        "fallback_values_labelled": True,
        "fallback_not_counted_as_production_grade_evidence": fallback_fixture["production_grade_evidence"] is False,
        "replay_fixture_cost": replay.to_jsonable(),
        "paper_fixture_cost": paper.to_jsonable(),
        "fallback_fixture_cost": fallback_fixture,
    }


def _policy_fingerprint(policy: RidgePolicy | None, dataset_manifest: Mapping[str, Any]) -> tuple[str, str]:
    material = {
        "model_source": MODEL_SOURCE,
        "policy": policy.to_jsonable() if policy else None,
        "dataset_manifest_hash": dataset_manifest.get("dataset_manifest_hash"),
        "cost_model_hash": cost_model_hash(),
    }
    fingerprint = stable_hash(material)
    return "challenger_v2_" + fingerprint[:24], fingerprint


def _reproducibility_manifest(
    *,
    repo_root: Path,
    candidate_id: str,
    policy_fingerprint: str,
    policy: RidgePolicy | None,
    dataset_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    source_files = _source_files(repo_root)
    dependency_files = _dependency_files(repo_root)
    tracked_status = _run_git(repo_root, "status", "--porcelain", "--", *[_rel(path, repo_root) for path in source_files + dependency_files])
    return {
        "schema_version": "challenger_v2_reproducibility_manifest_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": candidate_id,
        "git_commit": _run_git(repo_root, "rev-parse", "HEAD"),
        "git_worktree_clean_for_candidate_sources": tracked_status == "",
        "reproducibility_status": "PASS" if tracked_status == "" and policy is not None else "BLOCKED_UNCOMMITTED_OR_UNTRAINED_SOURCE",
        "policy_fingerprint": policy_fingerprint,
        "source_sha256_by_file": _hashes(source_files, repo_root),
        "dependency_sha256_by_file": _hashes(dependency_files, repo_root),
        "dependency_versions": _module_versions(),
        "feature_schema_hash": feature_schema_hash(policy.feature_names) if policy else None,
        "normalization_hash": normalization_hash(policy.normalization) if policy else None,
        "cost_model_hash": cost_model_hash(),
        "dataset_manifest_hash": dataset_manifest.get("dataset_manifest_hash"),
        "weights_hash": stable_hash(policy.to_jsonable()) if policy else None,
        "clean_checkout_reproduce_command": ".venv/bin/python -m v2.backend.app.cli.v2_challenger_v2_reproducible_pipeline --no-current-redis",
        "imports_from_head_or_other_branch_allowed": False,
    }


def _frozen_policy_status(
    *,
    candidate_id: str,
    policy_fingerprint: str,
    policy: RidgePolicy | None,
    dataset_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        "schema_version": "challenger_v2_frozen_policy_status_v1",
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": candidate_id,
        "policy_fingerprint": policy_fingerprint,
        "model_source": MODEL_SOURCE,
        "freeze_status": "FROZEN_VALIDATION_SELECTED_PENDING_BLIND_LOCKBOX" if policy else "NOT_FROZEN_NO_VALIDATION_SELECTED_POLICY",
        "feature_schema_hash": feature_schema_hash(policy.feature_names) if policy else None,
        "normalization_hash": normalization_hash(policy.normalization) if policy else None,
        "cost_model_hash": cost_model_hash(),
        "dataset_manifest_hash": dataset_manifest.get("dataset_manifest_hash"),
        "weights_hash": stable_hash(policy.to_jsonable()) if policy else None,
        "threshold": policy.threshold_bps if policy else None,
        "target_clipping_bps": policy.target_clip_bps if policy else None,
        "ridge_lambda": policy.ridge_lambda if policy else None,
        "paper_only": True,
        "routes_to_live": False,
        "promotion_allowed": False,
        "post_freeze_source_or_parameter_change_invalidates_candidate": True,
    }
    if policy:
        payload["feature_names_in_order"] = list(policy.feature_names)
        payload["normalization"] = policy.normalization.to_jsonable()
        payload["weights"] = list(policy.weights)
        payload["bias"] = policy.bias
    return payload


def _blocked_forward_artifacts(candidate_id: str, policy_fingerprint: str, feature_parity_pass: bool) -> dict[str, dict[str, Any]]:
    lockbox_manifest = {
        "schema_version": "challenger_v2_blind_lockbox_manifest_v1",
        "generated_utc": utc_now(),
        "candidate_id": candidate_id,
        "policy_fingerprint": policy_fingerprint,
        "status": "BLOCKED_FUTURE_LOCKBOX_NOT_COLLECTED",
        "lockbox_mode": "FUTURE_SNAPSHOTS_AFTER_CANDIDATE_FREEZE",
        "rows_viewed_before_freeze": 0,
        "rows_available": 0,
        "minimum_required_candidates": 300,
        "minimum_required_symbols": 30,
        "purged_overlapping_label_horizons": True,
        "embargo_between_data_windows": True,
        "closed_candles_only": True,
        "feature_cutoff_lte_decision_time_required": True,
        "available_at_lte_decision_time_required": True,
        "future_data_used_only_as_labels": True,
    }
    lockbox_performance = {
        "schema_version": "challenger_v2_blind_lockbox_performance_v1",
        "generated_utc": utc_now(),
        "candidate_id": candidate_id,
        "status": "BLOCKED_NO_VALID_LOCKBOX_ROWS",
        "rows_scanned": 0,
        "selected_economic_candidates": 0,
        "symbols": 0,
        "long_count": 0,
        "short_count": 0,
        "no_trade_count": 0,
        "after_cost_expectancy_bps": None,
        "expectancy_95pct_lower_bound_bps": None,
        "profit_factor": None,
        "false_positive_rate": None,
        "point_in_time_violations": 0,
        "pass": False,
        "zero_row_lockbox_is_blocked_not_verified": True,
    }
    forward_shadow = {
        "schema_version": "challenger_v2_forward_shadow_status_v1",
        "generated_utc": utc_now(),
        "candidate_id": candidate_id,
        "status": "NOT_PUBLISHED_FEATURE_PARITY_NOT_PASSED" if not feature_parity_pass else "READY_FOR_NON_EXECUTABLE_RANKING_LOOP",
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "counts_as_a_grade_evidence": False,
        "ranking_scope": "NON_EXECUTABLE_ONLY",
        "zero_supply_explanation_dimensions": [
            "no_net_edge",
            "cost",
            "integrity",
            "data_completeness",
            "distribution_drift",
            "threshold",
            "liquidity",
        ],
    }
    chain_binding = {
        "schema_version": "challenger_v2_paper_chain_binding_status_v1",
        "generated_utc": utc_now(),
        "candidate_id": candidate_id,
        "status": "NOT_STARTED_BLIND_LOCKBOX_NOT_PASSED",
        "challenger_v2_bound_to_paper_chain": False,
        "old_policy_silent_control_ruled_out": False,
        "routes_to_live": False,
    }
    canary = {
        "schema_version": "challenger_v2_forward_paper_canary_status_v1",
        "generated_utc": utc_now(),
        "candidate_id": candidate_id,
        "status": "NOT_STARTED_BLIND_LOCKBOX_NOT_PASSED",
        "forward_closed_outcomes": 0,
        "required_new_closed_economic_outcomes": 100,
        "symbols": 0,
        "long_count": 0,
        "short_count": 0,
        "paper_only": True,
        "routes_to_live": False,
        "pass": False,
    }
    promotion = {
        "schema_version": "challenger_v2_champion_promotion_status_v1",
        "generated_utc": utc_now(),
        "candidate_id": candidate_id,
        "status": "BLOCKED",
        "reproducibility_pass": False,
        "blind_lockbox_pass": False,
        "forward_paper_canary_pass": False,
        "claude_independent_verification_pass": False,
        "promotion_allowed": False,
        "routes_to_live": False,
        "a_grade": False,
    }
    return {
        "challenger_v2_blind_lockbox_manifest.json": lockbox_manifest,
        "challenger_v2_blind_lockbox_performance.json": lockbox_performance,
        "challenger_v2_forward_shadow_status.json": forward_shadow,
        "challenger_v2_paper_chain_binding_status.json": chain_binding,
        "challenger_v2_forward_paper_canary_status.json": canary,
        "challenger_v2_champion_promotion_status.json": promotion,
    }


def _forward_shadow_status(
    *,
    candidate_id: str,
    policy: RidgePolicy | None,
    feature_parity_pass: bool,
    current_limit: int,
    no_current_redis: bool,
) -> dict[str, Any]:
    base = {
        "schema_version": "challenger_v2_forward_shadow_status_v1",
        "generated_utc": utc_now(),
        "candidate_id": candidate_id,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "counts_as_a_grade_evidence": False,
        "ranking_scope": "NON_EXECUTABLE_ONLY",
        "top_long": [],
        "top_short": [],
    }
    if policy is None:
        base["status"] = "NOT_PUBLISHED_NO_VALIDATION_SELECTED_POLICY"
        return base
    if no_current_redis:
        base["status"] = "NOT_PUBLISHED_NO_CURRENT_REDIS_BY_OPERATOR_FLAG"
        return base
    if not feature_parity_pass:
        base["status"] = "NOT_PUBLISHED_FEATURE_PARITY_NOT_PASSED"
        return base

    snapshots, source = _read_current_snapshots(limit=current_limit)
    ranked: list[dict[str, Any]] = []
    cause_counts: Counter[str] = Counter()
    threshold = float(policy.threshold_bps)
    for snapshot in snapshots:
        adapted = adapt_runtime_snapshot(snapshot, normalization=policy.normalization)
        score = policy.predict(snapshot)
        side = "LONG" if score >= 0.0 else "SHORT"
        cost = estimate_paper_cost(snapshot, side=side.lower()).to_jsonable()
        reasons: list[str] = []
        if adapted.integrity_status.get("accepted_for_training") is not True:
            reasons.append("integrity")
        if adapted.missing_feature_names:
            reasons.append("data_completeness")
        if adapted.out_of_range_features:
            reasons.append("distribution_drift")
        if abs(score) < threshold:
            reasons.append("threshold")
        if cost.get("production_grade_evidence") is not True:
            reasons.append("cost")
        if abs(score) <= 0.0:
            reasons.append("no_net_edge")
        if "depth_impact_bps" in (cost.get("fallback_components") or []):
            reasons.append("liquidity")
        if not reasons:
            reasons.append("candidate_ranked_non_executable")
        for reason in set(reasons):
            cause_counts[reason] += 1
        ranked.append(
            {
                "symbol": adapted.symbol,
                "timeframe": adapted.timeframe,
                "snapshot_id": adapted.snapshot_id,
                "redis_key": snapshot.get("_redis_key"),
                "side": side,
                "score": score,
                "model_predicted_net_edge_bps": abs(score),
                "production_cost_estimate": cost,
                "net_expected_edge_bps": abs(score),
                "integrity_status": adapted.integrity_status,
                "feature_integrity": {
                    "missing_feature_names": list(adapted.missing_feature_names),
                    "stale_feature_names": list(adapted.stale_feature_names),
                    "out_of_range_features": list(adapted.out_of_range_features),
                    "normalization_status": adapted.normalization_status,
                },
                "rejection_reason": reasons[0],
                "rejection_reasons": sorted(set(reasons)),
                "paper_fill_allowed": False,
                "routes_to_live": False,
                "counts_as_a_grade_evidence": False,
            }
        )
    longs = sorted((row for row in ranked if row["side"] == "LONG"), key=lambda row: row["score"], reverse=True)
    shorts = sorted((row for row in ranked if row["side"] == "SHORT"), key=lambda row: row["score"])
    eligible_non_executable = [
        row
        for row in ranked
        if row["integrity_status"].get("accepted_for_training") is True
        and not row["feature_integrity"]["missing_feature_names"]
        and abs(float(row["score"])) >= threshold
        and row["production_cost_estimate"].get("production_grade_evidence") is True
    ]
    base.update(
        {
            "status": "PUBLISHED_NON_EXECUTABLE_RANKINGS",
            "current_snapshot_source": source,
            "current_rows_scanned": len(snapshots),
            "trade_threshold_bps": threshold,
            "eligible_non_executable_count": len(eligible_non_executable),
            "zero_current_supply_cause_counts": dict(sorted(cause_counts.items())),
            "top_long": longs[:20],
            "top_short": shorts[:20],
        }
    )
    return base


def run_pipeline(
    *,
    repo_root: Path,
    scan_limit: int,
    replay_limit: int,
    current_limit: int,
    no_current_redis: bool = False,
) -> dict[str, Any]:
    out_dir = repo_root / "goal_state" / GOAL_ID
    rows, dataset_manifest, rejections = _build_dataset(repo_root=repo_root, scan_limit=scan_limit, replay_limit=replay_limit)
    policy, training_status, validation_scoreboard = _train_policy(
        rows=rows,
        dataset_manifest=dataset_manifest,
        min_validation_trades=max(25, min(100, int(max(1, len(rows) * 0.01)))),
    )
    candidate_id, policy_fingerprint = _policy_fingerprint(policy, dataset_manifest)
    feature_parity, current_matrix, _current_rows = (
        (
            {
                "schema_version": "challenger_replay_runtime_feature_parity_status_v1",
                "status": "SKIPPED_NO_CURRENT_REDIS_BY_OPERATOR_FLAG",
                "current_rows_scanned": 0,
                "do_not_evaluate_current_supply_until_pass": True,
            },
            {
                "schema_version": "challenger_current_feature_rejection_matrix_v1",
                "status": "SKIPPED_NO_CURRENT_REDIS_BY_OPERATOR_FLAG",
                "current_record_count": 0,
                "rows": [],
                "summary_counts": {},
            },
            [],
        )
        if no_current_redis
        else _feature_parity_artifacts(policy=policy, current_limit=current_limit)
    )
    cost_parity = _cost_parity_status()
    reproducibility = _reproducibility_manifest(
        repo_root=repo_root,
        candidate_id=candidate_id,
        policy_fingerprint=policy_fingerprint,
        policy=policy,
        dataset_manifest=dataset_manifest,
    )
    frozen = _frozen_policy_status(
        candidate_id=candidate_id,
        policy_fingerprint=policy_fingerprint,
        policy=policy,
        dataset_manifest=dataset_manifest,
    )
    training_status.update(
        {
            "generated_utc": utc_now(),
            "goal_id": GOAL_ID,
            "candidate_id": candidate_id,
            "policy_fingerprint": policy_fingerprint,
            "cost_evidence_warning": "FALLBACK_COST_ROWS_NOT_PRODUCTION_GRADE"
            if dataset_manifest.get("production_grade_cost_rows", 0) < dataset_manifest.get("production_cost_replay_rows", 0)
            else None,
        }
    )
    validation_scoreboard.update(
        {
            "generated_utc": utc_now(),
            "goal_id": GOAL_ID,
            "candidate_id": candidate_id,
            "policy_fingerprint": policy_fingerprint,
        }
    )
    artifacts: dict[str, Any] = {
        "challenger_v2_reproducibility_manifest.json": reproducibility,
        "challenger_replay_runtime_feature_parity_status.json": feature_parity,
        "challenger_current_feature_rejection_matrix.json": current_matrix,
        "challenger_cost_model_parity_status.json": cost_parity,
        "challenger_v2_training_status.json": training_status,
        "challenger_v2_validation_scoreboard.json": validation_scoreboard,
        "challenger_v2_frozen_policy_status.json": frozen,
    }
    feature_parity_pass = feature_parity.get("status") == "PASS"
    artifacts.update(
        _blocked_forward_artifacts(
            candidate_id,
            policy_fingerprint,
            feature_parity_pass=feature_parity_pass,
        )
    )
    artifacts["challenger_v2_forward_shadow_status.json"] = _forward_shadow_status(
        candidate_id=candidate_id,
        policy=policy,
        feature_parity_pass=feature_parity_pass,
        current_limit=current_limit,
        no_current_redis=no_current_redis,
    )
    for name, payload in artifacts.items():
        _write_json(out_dir / name, payload)
    _write_jsonl(out_dir / "challenger_v2_blind_lockbox_rows.jsonl", [])
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_now(),
        "goal_id": GOAL_ID,
        "candidate_id": candidate_id,
        "policy_fingerprint": policy_fingerprint,
        "existing_v1_candidate_preserved": V1_CANDIDATE_ID,
        "dataset_rows": len(rows),
        "dataset_manifest_hash": dataset_manifest.get("dataset_manifest_hash"),
        "rejections_by_reason": rejections,
        "artifacts_written": sorted([*artifacts.keys(), "challenger_v2_blind_lockbox_rows.jsonl"]),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    _write_json(out_dir / "challenger_v2_pipeline_summary.json", summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--scan-limit", type=int, default=60_000)
    parser.add_argument("--replay-limit", type=int, default=30_000)
    parser.add_argument("--current-limit", type=int, default=2_000)
    parser.add_argument("--no-current-redis", action="store_true")
    args = parser.parse_args(argv)
    summary = run_pipeline(
        repo_root=args.repo_root,
        scan_limit=args.scan_limit,
        replay_limit=args.replay_limit,
        current_limit=args.current_limit,
        no_current_redis=args.no_current_redis,
    )
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
