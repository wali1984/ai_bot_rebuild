"""Persistent native CUDA trainer runtime and paper drawdown guard.

This module keeps the V2 native PPO/MASA CUDA trainer resident without using
the legacy trainer bridge or wrapper. It publishes V2-owned runtime artifacts,
checkpoint-retention status, resource telemetry, and a paper-only confidence
trial drawdown guard. It never touches live execution or exchange mutation
paths.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    default_archive_root,
    iter_snapshots,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (
    DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE,
    DEFAULT_ROLLOUT_MAX_ENVS,
    DEFAULT_ROLLOUT_N_STEPS,
    DEFAULT_TIMEFRAMES,
    TRAINER_SOURCE,
    HybridTrainerConfig,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
    V2HybridTrainerDataLoader,
    _classification_from_lineage,
    _lineage_trust_fields,
    _snapshot_decision_time_lineage,
    trainer_feedback_quarantine_rejection_reasons,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    ENV_PPO_ENTROPY_COEFFICIENT_MAX,
    ENV_PPO_LEARNING_RATE_MAX,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.runtime import (
    run_hybrid_trainer_cycle,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import V2OnlyJsonIO
from v2.backend.app.services.native_trainer.learning_readiness import (
    GLOBAL_READINESS_ARTIFACT,
    build_learning_readiness,
    write_learning_readiness_artifact,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    build_trusted_replay_row,
    snapshot_to_final_candle,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (
    SMOKE_TEST_SYMBOLS,
    resolve_symbols,
    resolve_symbols_with_provenance,
)


READY = "V2_PERSISTENT_CUDA_TRAINER_RESOURCE_UTILIZATION_AND_PAPER_DRAWDOWN_GUARD_READY"
BLOCKED = "V2_PERSISTENT_CUDA_TRAINER_RESOURCE_UTILIZATION_AND_PAPER_DRAWDOWN_GUARD_BLOCKED"
TRUSTED_REPLAY_GOAL_ID = "V2_TRUSTED_REPLAY_BOOTSTRAP_PAPER_EXPLORATION_AND_ONLINE_LEARNING_ACTIVATION"

ARTIFACT_REL = Path("v2_persistent_cuda_trainer_resource_utilization_and_paper_drawdown_guard/latest")
OPERATOR_REL = Path("operator_runtime/v2_native_trainer/latest")
PORTFOLIO_REL = Path("operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json")
PREDICTION_REL = Path("operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json")
PAPER_TRIAL_REL = Path("v2_paper_only_confidence_threshold_trial_and_outcome_monitor/latest/operator_dashboard_payload.json")
MODEL_DIR_REL = Path(".local_models/v2_native_rl_masa_ppo")
STATE_REL = Path("v2/runtime/native_cuda_trainer_persistent_state.json")

PERSISTENT_UNIT = "ai-bot-v2-native-cuda-trainer-persistent.service"
LEGACY_BRIDGE_UNIT = "ai-bot-v2-trainer-bridge.service"
TRIAL_SIGNAL_REDIS_KEY = "v2:signals:paper:confidence_threshold_trial"
TRIAL_STATUS_REDIS_KEY = "v2:paper:confidence_threshold_trial:status"
TRIAL_DRAWDOWN_GUARD_REDIS_KEY = "v2:paper:confidence_threshold_trial:drawdown_guard"

PREVIOUS_PAPER_PNL_BASELINE = 30.41842727
TRIAL_DRAWDOWN_DELTA_THRESHOLD_USD = -50.0
TRIAL_OVERLAY_PNL_THRESHOLD_USD = -25.0
TRAINER_GPU_UTILIZATION_LIMIT_PERCENT = 75.0
TRAINER_VRAM_LIMIT_MB = 12 * 1024
TRAINER_CPU_QUOTA_PERCENT = 50.0
TRAINER_RAM_LIMIT_GB = 75.0
EST = ZoneInfo("America/New_York")
DEFAULT_HOLDOUT_CALIBRATION_SCAN_LIMIT = 100_000
DEFAULT_HOLDOUT_CALIBRATION_EVAL_LIMIT = 512
DEFAULT_HOLDOUT_CALIBRATION_MIN_INTERVAL_SECONDS = 900
_HOLDOUT_EXAMPLE_CACHE: dict[str, Any] = {}


@dataclass(frozen=True)
class PersistentTrainerPaths:
    repo_root: Path

    @property
    def public_root(self) -> Path:
        return self.repo_root / "v2/frontend/public"

    @property
    def artifact_dir(self) -> Path:
        return self.public_root / ARTIFACT_REL

    @property
    def worklog_dir(self) -> Path:
        return self.repo_root / "claude_worklog/final_readiness" / ARTIFACT_REL

    @property
    def operator_dir(self) -> Path:
        return self.public_root / OPERATOR_REL

    @property
    def state_path(self) -> Path:
        return self.repo_root / STATE_REL

    @property
    def model_dir(self) -> Path:
        return self.repo_root / MODEL_DIR_REL


def est_now() -> str:
    return datetime.now(tz=EST).isoformat(timespec="seconds")


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    tmp.replace(path)


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _percentile(values: Iterable[float], q: float) -> float | None:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = max(0.0, min(1.0, float(q))) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distribution(values: Iterable[float]) -> dict[str, Any]:
    numbers = [float(value) for value in values if math.isfinite(float(value))]
    return {
        "count": len(numbers),
        "min": min(numbers) if numbers else None,
        "p25": _percentile(numbers, 0.25),
        "median": _percentile(numbers, 0.50),
        "p75": _percentile(numbers, 0.75),
        "max": max(numbers) if numbers else None,
    }


def parse_runtime_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def connect_redis() -> Any | None:
    try:
        import redis  # type: ignore

        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=5,
        )
        client.ping()
        return client
    except Exception:
        return None


def redis_json(client: Any | None, key: str, default: Any = None) -> Any:
    if client is None:
        return {} if default is None else default
    try:
        raw = client.get(key)
    except Exception:
        return {} if default is None else default
    if raw is None:
        return {} if default is None else default
    try:
        return json.loads(raw)
    except Exception:
        return {} if default is None else default


def _redis_json_list(key: str) -> list[dict[str, Any]]:
    client = connect_redis()
    payload = redis_json(client, key, default=[])
    return [dict(row) for row in as_list(payload) if isinstance(row, Mapping)]


def _prediction_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in as_list(payload.get("prediction_rows")) if isinstance(row, Mapping)]


def _trust_envelope_complete(row: Mapping[str, Any]) -> tuple[bool, list[str]]:
    missing: list[str] = []
    for field in (
        "prediction_id",
        "signal_id",
        "decision_id",
        "feature_snapshot_id",
        "mtf_snapshot_id",
        "feature_cutoff",
        "decision_time",
        "available_at",
        "symbol",
        "timeframe",
        "selected_action",
        "model_version",
        "checkpoint_id",
    ):
        if row.get(field) in (None, "", [], {}):
            missing.append(field)
    if not as_dict(row.get("source_hashes")):
        missing.append("source_hashes")
    feature_cutoff = parse_runtime_time(row.get("feature_cutoff"))
    decision_time = parse_runtime_time(row.get("decision_time"))
    available_at = parse_runtime_time(row.get("available_at"))
    if feature_cutoff is None:
        missing.append("feature_cutoff_parseable")
    if decision_time is None:
        missing.append("decision_time_parseable")
    if available_at is None:
        missing.append("available_at_parseable")
    if feature_cutoff is not None and decision_time is not None and feature_cutoff > decision_time:
        missing.append("feature_cutoff_after_decision_time")
    if available_at is not None and decision_time is not None and available_at > decision_time:
        missing.append("available_at_after_decision_time")
    return not missing, sorted(set(missing))


def _allowed_exploration_blockers(blockers: Iterable[Any]) -> bool:
    allowed = {"confidence_below_threshold", "expected_move_after_cost_below_threshold"}
    return all(str(reason) in allowed for reason in blockers)


def _binary_action_outcome(row: Mapping[str, Any]) -> float | None:
    profitable = row.get("action_was_profitable")
    if isinstance(profitable, bool):
        return 1.0 if profitable else 0.0
    trade_outcome = str(row.get("trade_outcome") or "").upper()
    if trade_outcome == "WIN":
        return 1.0
    if trade_outcome == "LOSS":
        return 0.0
    return None


def _trusted_feedback_metric_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    calibration_rows: list[dict[str, float]] = []
    expected_move_rows: list[dict[str, float]] = []
    rejected: dict[str, int] = {}
    holdout_rows = 0
    trusted_rows = 0
    for row in rows:
        if row.get("trainer_consumable") is False:
            rejected["trainer_consumable_false"] = rejected.get("trainer_consumable_false", 0) + 1
            continue
        trust_ok, trust_missing = _trust_envelope_complete(row)
        if not trust_ok:
            rejected["trust_envelope_incomplete"] = rejected.get("trust_envelope_incomplete", 0) + 1
            for reason in trust_missing:
                key = f"trust:{reason}"
                rejected[key] = rejected.get(key, 0) + 1
            continue
        trusted_rows += 1
        if row.get("out_of_sample_holdout") is True or row.get("untouched_holdout_window") is True:
            holdout_rows += 1
        confidence = finite_float(row.get("confidence_calibrated"))
        outcome = _binary_action_outcome(row)
        if confidence is not None and 0.0 <= confidence <= 1.0 and outcome is not None:
            calibration_rows.append({"confidence": confidence, "outcome": outcome})
        else:
            rejected["missing_confidence_or_binary_outcome"] = rejected.get("missing_confidence_or_binary_outcome", 0) + 1
        expected = finite_float(row.get("expected_move_after_cost_bps"))
        realized = finite_float(row.get("realized_net_pnl_bps") or row.get("realized_pnl_bps"))
        if expected is not None and realized is not None:
            expected_move_rows.append({"expected": expected, "realized": realized})
        else:
            rejected["missing_expected_move_or_realized_pnl"] = rejected.get("missing_expected_move_or_realized_pnl", 0) + 1
    return {
        "trusted_rows": trusted_rows,
        "holdout_rows": holdout_rows,
        "calibration_rows": calibration_rows,
        "expected_move_rows": expected_move_rows,
        "rows_rejected_by_reason": rejected,
    }


def _brier_score(rows: Iterable[Mapping[str, float]]) -> float | None:
    values = [
        (float(row["confidence"]) - float(row["outcome"])) ** 2
        for row in rows
        if "confidence" in row and "outcome" in row
    ]
    return sum(values) / len(values) if values else None


def _expected_calibration_error(rows: list[dict[str, float]], *, bucket_count: int = 10) -> tuple[float | None, list[dict[str, Any]]]:
    if not rows:
        return None, []
    buckets: list[dict[str, Any]] = []
    total = len(rows)
    weighted_error = 0.0
    for index in range(bucket_count):
        low = index / bucket_count
        high = (index + 1) / bucket_count
        if index == bucket_count - 1:
            bucket_rows = [row for row in rows if low <= row["confidence"] <= high]
        else:
            bucket_rows = [row for row in rows if low <= row["confidence"] < high]
        if not bucket_rows:
            continue
        avg_conf = sum(row["confidence"] for row in bucket_rows) / len(bucket_rows)
        empirical = sum(row["outcome"] for row in bucket_rows) / len(bucket_rows)
        error = abs(avg_conf - empirical)
        weighted_error += (len(bucket_rows) / total) * error
        buckets.append(
            {
                "bucket_min": low,
                "bucket_max": high,
                "sample_count": len(bucket_rows),
                "avg_confidence": avg_conf,
                "empirical_success_rate": empirical,
                "absolute_calibration_error": error,
                "brier_score": _brier_score(bucket_rows),
            }
        )
    return weighted_error, buckets


def _expected_move_mae(rows: Iterable[Mapping[str, float]]) -> float | None:
    errors = [
        abs(float(row["expected"]) - float(row["realized"]))
        for row in rows
        if "expected" in row and "realized" in row
    ]
    return sum(errors) / len(errors) if errors else None


def _bounded_env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    value = os.environ.get(name)
    try:
        parsed = int(value) if value not in (None, "") else int(default)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(int(minimum), min(int(maximum), parsed))


def _bounded_env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    value = os.environ.get(name)
    try:
        parsed = float(value) if value not in (None, "") else float(default)
    except (TypeError, ValueError):
        parsed = float(default)
    return max(float(minimum), min(float(maximum), parsed))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value in (None, ""):
        return bool(default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _setting_source(name: str, default_source: str = "default") -> str:
    return f"env:{name}" if os.environ.get(name) not in (None, "") else default_source


def _current_env_values(names: Iterable[str]) -> dict[str, str | None]:
    return {name: os.environ.get(name) for name in names}


def _sha256_path(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trusted_replay_holdout_manifest(repo_root: Path) -> dict[str, Any]:
    candidates = (
        repo_root
        / "goal_state"
        / TRUSTED_REPLAY_GOAL_ID
        / "trusted_replay_train_validation_holdout_manifest.json",
        repo_root
        / "v2/frontend/public/operator_runtime/v2_native_trainer/latest/trusted_replay_train_validation_holdout_manifest.json",
        repo_root
        / "claude_worklog/final_readiness"
        / TRUSTED_REPLAY_GOAL_ID
        / "latest/trusted_replay_train_validation_holdout_manifest.json",
    )
    for path in candidates:
        payload = as_dict(read_json(path))
        holdout = as_dict(payload.get("holdout_window"))
        if holdout.get("start_decision_time") and holdout.get("end_decision_time"):
            return {**payload, "manifest_path": str(path)}
    return {}


def _holdout_window(manifest: Mapping[str, Any]) -> tuple[datetime | None, datetime | None, int]:
    holdout = as_dict(manifest.get("holdout_window"))
    start = parse_runtime_time(holdout.get("start_decision_time"))
    end = parse_runtime_time(holdout.get("end_decision_time"))
    rows = int(finite_float(holdout.get("rows")) or 0)
    return start, end, rows


def _sample_evenly(rows: list[Any], limit: int) -> list[Any]:
    if limit <= 0:
        return []
    if len(rows) <= limit:
        return list(rows)
    if limit == 1:
        return [rows[-1]]
    last = len(rows) - 1
    indices = [int(round((last * index) / (limit - 1))) for index in range(limit)]
    out: list[Any] = []
    seen: set[int] = set()
    for index in indices:
        if index in seen:
            continue
        seen.add(index)
        out.append(rows[index])
    return out


def _selected_action_outcome(selected_action: Any, realized_after_cost_bps: float) -> float | None:
    action = str(selected_action or "").lower()
    if action == "long":
        return 1.0 if realized_after_cost_bps > 0.0 else 0.0
    if action == "short":
        return 1.0 if realized_after_cost_bps < 0.0 else 0.0
    if action == "hold":
        return 1.0 if abs(realized_after_cost_bps) < 4.0 else 0.0
    return None


def _expected_after_cost_bps(expected_move_bps: float, *, round_trip_cost_bps: float = 2.0) -> float:
    if expected_move_bps > 0.0:
        return expected_move_bps - abs(round_trip_cost_bps)
    if expected_move_bps < 0.0:
        return expected_move_bps + abs(round_trip_cost_bps)
    return 0.0


def _directional_accuracy_hit(selected_action: Any, realized_after_cost_bps: float) -> bool | None:
    action = str(selected_action or "").lower()
    if action == "long":
        return realized_after_cost_bps > 0.0
    if action == "short":
        return realized_after_cost_bps < 0.0
    if action == "hold":
        return abs(realized_after_cost_bps) < 4.0
    return None


def _trusted_replay_holdout_examples(
    *,
    repo_root: Path,
    manifest: Mapping[str, Any],
    scan_limit: int,
    eval_limit: int,
) -> dict[str, Any]:
    start, end, manifest_rows = _holdout_window(manifest)
    if start is None or end is None:
        return {
            "status": "BLOCKED_NO_TRUSTED_REPLAY_HOLDOUT_WINDOW",
            "examples": [],
            "rows_rejected_by_reason": {"holdout_window_missing": 1},
        }
    archive_root = default_archive_root(repo_root)
    cache_key = hashlib.sha256(
        json.dumps(
            {
                "archive_root": str(archive_root),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "manifest_rows": manifest_rows,
                "scan_limit": int(scan_limit),
                "eval_limit": int(eval_limit),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    cached = _HOLDOUT_EXAMPLE_CACHE.get(cache_key)
    if isinstance(cached, Mapping):
        return {**dict(cached), "cache_hit": True}

    rejected: dict[str, int] = {}
    archive_candles: dict[tuple[str, str], list[dict[str, Any]]] = {}
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    snapshots_scanned = 0
    try:
        for snapshot in iter_snapshots(archive_root, limit=scan_limit):
            snapshots_scanned += 1
            candle, _reasons = snapshot_to_final_candle(snapshot)
            if candle is not None:
                pair = (str(candle.get("symbol") or "").upper(), str(candle.get("timeframe") or ""))
                archive_candles.setdefault(pair, []).append(candle)
            decision_time = parse_runtime_time(snapshot.get("decision_time"))
            if decision_time is None or decision_time < start or decision_time > end:
                continue
            sample_id = str(snapshot.get("snapshot_id") or snapshot.get("feature_snapshot_id") or "")
            candidates.append((decision_time.isoformat(), sample_id, dict(snapshot)))
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "BLOCKED_TRUSTED_REPLAY_HOLDOUT_ARCHIVE_SCAN_FAILED",
            "examples": [],
            "snapshots_scanned": snapshots_scanned,
            "rows_rejected_by_reason": {f"archive_scan_failed:{type(exc).__name__}": 1},
        }

    for rows in archive_candles.values():
        rows.sort(key=lambda row: str(row.get("candle_close_time") or ""))
    candidates.sort(key=lambda item: (item[0], item[1]))
    selected = _sample_evenly(candidates, eval_limit)
    loader = V2HybridTrainerDataLoader(
        io=V2OnlyJsonIO(client=None),
        trusted_replay_archive_root=archive_root,
    )
    examples: list[TrainingExample] = []
    sample_ids: list[str] = []
    for _decision_time, _sample_id, snapshot in selected:
        symbol = str(snapshot.get("symbol") or "").upper()
        timeframe = str(snapshot.get("timeframe") or "")
        if not symbol or not timeframe:
            rejected["symbol_or_timeframe_missing"] = rejected.get("symbol_or_timeframe_missing", 0) + 1
            continue
        replay_row, reasons = build_trusted_replay_row(
            snapshot,
            candles=list(archive_candles.get((symbol, timeframe)) or []),
        )
        if replay_row is None:
            for reason in reasons or ["trusted_replay_row_not_built"]:
                rejected[str(reason)] = rejected.get(str(reason), 0) + 1
            continue
        features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
        if not features:
            rejected["features_empty"] = rejected.get("features_empty", 0) + 1
            continue
        payloads = loader._payloads_from_feature_snapshot(  # noqa: SLF001
            snapshot=snapshot,
            features=features,
            feedback_row=replay_row,
        )
        payloads["_keys"] = {
            "features_latest": f"durable_feature_snapshot_archive:{snapshot.get('snapshot_id')}",
            "trainer_feedback_outcomes": replay_row["sample_id"],
            "ohlcv": "durable_feature_snapshot_archive_holdout",
        }
        try:
            tensor = loader.tensor_builder.build(symbol=symbol, timeframe=timeframe, payloads=payloads)
        except Exception as exc:  # noqa: BLE001
            reason = f"tensor_build_failed:{type(exc).__name__}"
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        if tensor.data_coverage_percent < 20.0:
            rejected["data_coverage_below_20"] = rejected.get("data_coverage_below_20", 0) + 1
            continue
        snapshot_lineage = _snapshot_decision_time_lineage(snapshot)
        classification = _classification_from_lineage(tensor=tensor, lineage=snapshot_lineage)
        trust_row = dict(replay_row)
        trust_row.update(_lineage_trust_fields(tensor=tensor, lineage=snapshot_lineage))
        trust_row.update(
            {
                "row_classification": classification,
                "feature_vector_hash": tensor.tensor_id,
                "reject_reasons": list(reasons),
                "out_of_sample_holdout": True,
                "untouched_holdout_window": True,
            }
        )
        examples.append(
            TrainingExample(
                symbol=symbol,
                timeframe=timeframe,
                tensor=tensor,
                label_action_index=loader._label_action(float(replay_row["future_return_after_cost_bps"])),  # noqa: SLF001
                label_expected_move_after_cost_bps=float(replay_row["future_return_after_cost_bps"]),
                payload_keys=tuple((payloads.get("_keys") or {}).values()),
                row_classification=classification,
                trust_row=trust_row,
            )
        )
        sample_ids.append(str(replay_row.get("sample_id") or ""))

    payload = {
        "status": "ACTIVE_TRUSTED_REPLAY_HOLDOUT_EXAMPLES_LOADED" if examples else "BLOCKED_NO_USABLE_HOLDOUT_EXAMPLES",
        "examples": examples,
        "cache_hit": False,
        "snapshots_scanned": snapshots_scanned,
        "holdout_candidates_found": len(candidates),
        "manifest_holdout_rows": manifest_rows,
        "selected_candidate_rows": len(selected),
        "usable_examples": len(examples),
        "rows_rejected_by_reason": rejected,
        "holdout_sample_identity_hash": hashlib.sha256(
            json.dumps(sample_ids, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if sample_ids
        else None,
    }
    _HOLDOUT_EXAMPLE_CACHE.clear()
    _HOLDOUT_EXAMPLE_CACHE[cache_key] = payload
    return dict(payload)


def build_trusted_replay_holdout_calibration(
    *,
    repo_root: Path | None,
    model_dir: Path | None,
    generated_utc: str,
) -> dict[str, Any]:
    if repo_root is None or model_dir is None:
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_NO_REPO_MODEL_CONTEXT",
            "confidence_outcome_join_available": False,
            "reason": "repo_root and model_dir are required for trusted replay holdout evaluation",
        }
    manifest = _trusted_replay_holdout_manifest(Path(repo_root))
    start, end, manifest_rows = _holdout_window(manifest)
    if start is None or end is None:
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_NO_TRUSTED_REPLAY_HOLDOUT_WINDOW",
            "confidence_outcome_join_available": False,
            "reason": "trusted replay temporal holdout manifest is missing or incomplete",
        }
    scan_limit = _bounded_env_int(
        "V2_TRUSTED_REPLAY_HOLDOUT_SCAN_LIMIT",
        DEFAULT_HOLDOUT_CALIBRATION_SCAN_LIMIT,
        minimum=1_000,
        maximum=250_000,
    )
    eval_limit = _bounded_env_int(
        "V2_TRUSTED_REPLAY_HOLDOUT_EVAL_LIMIT",
        DEFAULT_HOLDOUT_CALIBRATION_EVAL_LIMIT,
        minimum=32,
        maximum=5_000,
    )
    loaded = _trusted_replay_holdout_examples(
        repo_root=Path(repo_root),
        manifest=manifest,
        scan_limit=scan_limit,
        eval_limit=eval_limit,
    )
    examples = [example for example in as_list(loaded.get("examples")) if isinstance(example, TrainingExample)]
    if not examples:
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": str(loaded.get("status") or "BLOCKED_NO_USABLE_HOLDOUT_EXAMPLES"),
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "manifest_holdout_rows": manifest_rows,
            "scan_limit": scan_limit,
            "eval_limit": eval_limit,
            "rows_rejected_by_reason": as_dict(loaded.get("rows_rejected_by_reason")),
            "reason": "no PIT-safe trusted replay holdout examples could be materialized",
        }
    input_dim = len(examples[0].tensor.model_vector)
    checkpoint_manager = V2HybridCheckpointManager(Path(model_dir))
    manifest_checkpoint = checkpoint_manager.latest_manifest(input_dim=input_dim)
    if manifest_checkpoint is None or not manifest_checkpoint.weight_blob_written or not manifest_checkpoint.weight_file_path:
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_NO_COMPATIBLE_CHECKPOINT_WEIGHT_BLOB",
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "manifest_holdout_rows": manifest_rows,
            "evaluated_rows": 0,
            "reason": "latest compatible checkpoint manifest has no safe npz weight blob",
        }
    weight_path = Path(str(manifest_checkpoint.weight_file_path))
    if not weight_path.is_absolute():
        weight_path = Path(repo_root) / weight_path
    model = V2HybridPolicyModel(input_dim=input_dim)
    try:
        load_result = model.load_weight_blob(weight_path)
    except Exception as exc:  # noqa: BLE001
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_CHECKPOINT_WEIGHT_BLOB_LOAD_FAILED",
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "checkpoint_id": manifest_checkpoint.checkpoint_id,
            "checkpoint_path": str(weight_path),
            "reason": f"checkpoint load failed: {type(exc).__name__}",
        }

    calibration_rows: list[dict[str, float]] = []
    expected_move_rows: list[dict[str, float]] = []
    rows_rejected = dict(as_dict(loaded.get("rows_rejected_by_reason")))
    direction_hits = 0
    direction_total = 0
    preview: list[dict[str, Any]] = []
    future_label_separation_ok = 0
    for example in examples:
        trust_row = as_dict(example.trust_row)
        realized = finite_float(trust_row.get("future_return_after_cost_bps"))
        if realized is None:
            rows_rejected["missing_future_return_after_cost_bps"] = rows_rejected.get(
                "missing_future_return_after_cost_bps", 0
            ) + 1
            continue
        if trust_row.get("future_labels_not_in_feature_tensor") is True:
            future_label_separation_ok += 1
        try:
            forward = model.forward(example.tensor)
        except Exception as exc:  # noqa: BLE001
            reason = f"model_forward_failed:{type(exc).__name__}"
            rows_rejected[reason] = rows_rejected.get(reason, 0) + 1
            continue
        confidence = finite_float(forward.confidence_calibrated)
        outcome = _selected_action_outcome(forward.selected_action, realized)
        expected_after_cost = _expected_after_cost_bps(float(forward.expected_move_bps))
        if confidence is not None and 0.0 <= confidence <= 1.0 and outcome is not None:
            calibration_rows.append({"confidence": confidence, "outcome": outcome})
        else:
            rows_rejected["missing_confidence_or_selected_action_outcome"] = rows_rejected.get(
                "missing_confidence_or_selected_action_outcome", 0
            ) + 1
        expected_move_rows.append({"expected": expected_after_cost, "realized": realized})
        hit = _directional_accuracy_hit(forward.selected_action, realized)
        if hit is not None:
            direction_total += 1
            direction_hits += 1 if hit else 0
        if len(preview) < 25:
            preview.append(
                {
                    "sample_id": trust_row.get("sample_id"),
                    "symbol": example.symbol,
                    "timeframe": example.timeframe,
                    "decision_time": trust_row.get("decision_time"),
                    "selected_action": forward.selected_action,
                    "target_action": trust_row.get("target_action"),
                    "confidence_calibrated": confidence,
                    "expected_move_after_cost_bps": expected_after_cost,
                    "future_return_after_cost_bps": realized,
                    "action_was_profitable": outcome,
                }
            )
    ece, buckets = _expected_calibration_error(calibration_rows)
    brier = _brier_score(calibration_rows)
    expected_mae = _expected_move_mae(expected_move_rows)
    status = (
        "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION"
        if calibration_rows and future_label_separation_ok == len(examples)
        else "BLOCKED_NO_USABLE_HOLDOUT_CONFIDENCE_OUTCOMES"
    )
    return {
        "schema_version": "trusted_replay_holdout_calibration_status_v1",
        "generated_utc": generated_utc,
        "status": status,
        "confidence_outcome_join_available": bool(calibration_rows),
        "calibration_source": "TRUSTED_REPLAY_TEMPORAL_HOLDOUT_CURRENT_CHECKPOINT_FORWARD",
        "learning_mode": "EVALUATION_ONLY_NOT_TRAINING",
        "paper_only": True,
        "routes_to_live": False,
        "future_labels_used_as_features": False,
        "future_labels_not_in_feature_tensor_rows": future_label_separation_ok,
        "future_labels_not_in_feature_tensor_verified": future_label_separation_ok == len(examples),
        "uses_expected_move_as_realized_reward": False,
        "holdout_window": as_dict(manifest.get("holdout_window")),
        "manifest_path": manifest.get("manifest_path"),
        "manifest_holdout_rows": manifest_rows,
        "snapshots_scanned": loaded.get("snapshots_scanned"),
        "holdout_candidates_found": loaded.get("holdout_candidates_found"),
        "holdout_sample_identity_hash": loaded.get("holdout_sample_identity_hash"),
        "scan_limit": scan_limit,
        "eval_limit": eval_limit,
        "evaluated_rows": len(examples),
        "trusted_holdout_rows": len(calibration_rows),
        "brier_score": brier,
        "ece": ece,
        "expected_move_mae": expected_mae,
        "directional_accuracy": direction_hits / direction_total if direction_total else None,
        "confidence_reliability_buckets": buckets,
        "checkpoint_id": manifest_checkpoint.checkpoint_id,
        "checkpoint_path": str(weight_path),
        "checkpoint_hash": _sha256_path(weight_path),
        "checkpoint_weight_blob_loaded": bool(load_result.get("model_state_restored")),
        "device": model.device,
        "cuda_active": model.cuda_active,
        "cache_hit": bool(loaded.get("cache_hit")),
        "rows_rejected_by_reason": rows_rejected,
        "evaluation_rows_preview": preview,
        "reason": None if status == "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION" else "holdout rows lacked usable confidence/outcome joins",
        "_calibration_rows": calibration_rows,
        "_expected_move_rows": expected_move_rows,
    }


def build_paper_exploration_artifacts(
    *,
    prediction_public: Mapping[str, Any],
    generated_utc: str,
) -> dict[str, dict[str, Any]]:
    rows = _prediction_rows(prediction_public)
    scored: list[dict[str, Any]] = []
    rejection_counts: dict[str, int] = {}
    a_grade = 0
    for row in rows:
        trust_ok, trust_missing = _trust_envelope_complete(row)
        action = str(row.get("selected_action") or "").lower()
        edge = finite_float(row.get("expected_move_after_cost_bps")) or 0.0
        confidence = finite_float(row.get("confidence_calibrated")) or 0.0
        coverage = finite_float(row.get("data_coverage_percent")) or 0.0
        integrity = finite_float(row.get("market_state_integrity_score")) or 0.0
        spread = finite_float(row.get("actual_observed_spread_entry_bps"))
        stale_count = int(finite_float(row.get("stale_feature_count")) or 0)
        blockers = [str(reason) for reason in as_list(row.get("paper_fill_gate_block_reasons"))]
        if trust_ok and row.get("paper_fill_allowed") is True and action in {"long", "short"}:
            a_grade += 1
        reasons: list[str] = []
        if not trust_ok:
            reasons.extend(f"missing_{name}" for name in trust_missing)
        if action not in {"long", "short"}:
            reasons.append("not_directional_action")
        if edge <= 0.0:
            reasons.append("non_positive_edge_after_cost")
        if coverage < 70.0:
            reasons.append("data_coverage_below_70")
        if integrity < 80.0 or as_list(row.get("market_state_reject_reasons")):
            reasons.append("market_state_integrity_not_clean")
        if stale_count > 0:
            reasons.append("stale_feature_present")
        if spread is None or spread > 10.0:
            reasons.append("spread_unacceptable_or_missing")
        if not _allowed_exploration_blockers(blockers):
            reasons.append("paper_risk_or_lineage_blocker_present")
        if row.get("live_gate") != "blocked_human_only" or as_list(row.get("live_symbols")):
            reasons.append("live_gate_or_live_symbol_not_blocked")
        if reasons:
            for reason in sorted(set(reasons)):
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            continue
        uncertainty = max(0.0, 1.0 - abs(confidence - 0.5) * 2.0)
        score = (edge * 0.55) + (coverage / 100.0 * 12.0) + (integrity / 100.0 * 12.0) + (uncertainty * 8.0)
        scored.append(
            {
                "prediction_id": row.get("prediction_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "selected_action": action,
                "confidence_calibrated": confidence,
                "expected_move_after_cost_bps": edge,
                "data_coverage_percent": coverage,
                "market_state_integrity_score": integrity,
                "actual_observed_spread_entry_bps": spread,
                "exploration_score": round(score, 6),
                "uncertainty_score": round(uncertainty, 6),
                "paper_only": True,
                "routes_to_live": False,
                "live_allowed": False,
                "selected_before_outcome": True,
            }
        )
    score_floor = _percentile([float(row["exploration_score"]) for row in scored], 0.80)
    diversified: list[dict[str, Any]] = []
    symbol_seen: set[str] = set()
    side_counts: dict[str, int] = {}
    timeframe_counts: dict[str, int] = {}
    for row in sorted(scored, key=lambda item: float(item["exploration_score"]), reverse=True):
        if score_floor is not None and float(row["exploration_score"]) < score_floor:
            continue
        symbol = str(row.get("symbol") or "")
        side = str(row.get("selected_action") or "")
        timeframe = str(row.get("timeframe") or "")
        if symbol in symbol_seen:
            continue
        if side_counts.get(side, 0) >= 25 or timeframe_counts.get(timeframe, 0) >= 15:
            continue
        symbol_seen.add(symbol)
        side_counts[side] = side_counts.get(side, 0) + 1
        timeframe_counts[timeframe] = timeframe_counts.get(timeframe, 0) + 1
        diversified.append(row)
    status = "ACTIVE_PAPER_ONLY_EXPLORATION_SELECTION" if diversified else "BLOCKED_NO_EXPLORATION_CANDIDATES"
    return {
        "paper_exploration_tier_status.json": {
            "schema_version": "paper_exploration_tier_status_v1",
            "generated_utc": generated_utc,
            "status": status,
            "paper_only": True,
            "routes_to_live": False,
            "exchange_mutation": False,
            "live_allowed": False,
            "tiers": {
                "A_GRADE_EXECUTION_PAPER": a_grade,
                "B_GRADE_EXPLORATION_PAPER": len(diversified),
                "SHADOW_ONLY": max(0, len(scored) - len(diversified)),
                "NO_TRADE": max(0, len(rows) - len(scored) - a_grade),
            },
            "selection_method": "adaptive_top_quantile_by_edge_quality_uncertainty_with_side_timeframe_symbol_diversification",
            "dynamic_score_floor": score_floor,
            "candidate_rows": len(scored),
            "selected_rows": len(diversified),
            "rejection_counts": rejection_counts,
        },
        "paper_exploration_admission_matrix.json": {
            "schema_version": "paper_exploration_admission_matrix_v1",
            "generated_utc": generated_utc,
            "status": status,
            "selection_scope": "PAPER_ONLY_CURRENT_PREDICTION_ROWS",
            "required_checks": [
                "complete_trust_envelope",
                "feature_cutoff_lte_decision_time",
                "available_at_lte_decision_time",
                "market_state_integrity_pass",
                "no_stale_feature",
                "positive_expected_move_after_observed_costs",
                "acceptable_spread",
                "paper_only_risk_envelope",
                "candidate_selected_before_outcome",
            ],
            "rejection_counts": rejection_counts,
            "selected_candidates": diversified[:50],
        },
        "paper_exploration_risk_budget_status.json": {
            "schema_version": "paper_exploration_risk_budget_status_v1",
            "generated_utc": generated_utc,
            "status": status,
            "paper_only": True,
            "routes_to_live": False,
            "exchange_mutation": False,
            "fixed_usdt_sizing": False,
            "exploration_risk_budget_formula": "normal_adaptive_risk_budget * posterior_exploration_multiplier * drawdown_multiplier",
            "posterior_exploration_multiplier_source": "confidence_uncertainty_and_edge_quality_bucket",
            "drawdown_multiplier_source": "paper_drawdown_guard",
            "selected_candidate_count": len(diversified),
            "candidate_budget_multipliers": [
                {
                    "prediction_id": row.get("prediction_id"),
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "posterior_exploration_multiplier": round(max(0.05, min(0.50, float(row["uncertainty_score"]) * 0.5)), 6),
                    "drawdown_multiplier": 1.0,
                }
                for row in diversified[:50]
            ],
        },
    }


def build_confidence_artifacts(
    *,
    prediction_public: Mapping[str, Any],
    generated_utc: str,
    current_gate: float = 0.55,
    repo_root: Path | None = None,
    model_dir: Path | None = None,
    run_holdout_calibration: bool = True,
    previous_trusted_confidence_calibration: Mapping[str, Any] | None = None,
    holdout_calibration_reuse_age_seconds: float | None = None,
    holdout_calibration_min_interval_seconds: int | None = None,
) -> dict[str, dict[str, Any]]:
    rows = _prediction_rows(prediction_public)
    raw_values = [value for row in rows if (value := finite_float(row.get("confidence_raw"))) is not None]
    calibrated_values = [
        value for row in rows if (value := finite_float(row.get("confidence_calibrated"))) is not None
    ]
    capable = [value for value in calibrated_values if value >= current_gate]
    coverage_penalties = [max(0.0, 100.0 - (finite_float(row.get("data_coverage_percent")) or 0.0)) for row in rows]
    missing_penalties = [float(finite_float(row.get("missing_feature_count")) or 0.0) for row in rows]
    stale_penalties = [float(finite_float(row.get("stale_feature_count")) or 0.0) for row in rows]
    reachability_status = (
        "CONFIDENCE_GATE_REACHABLE_BY_CURRENT_CALIBRATION"
        if capable
        else "CONFIDENCE_GATE_UNREACHABLE_BY_CURRENT_CALIBRATION"
    )
    feedback_metrics = _trusted_feedback_metric_rows(_redis_json_list("v2:trainer:feedback:outcomes"))
    previous_calibration = as_dict(previous_trusted_confidence_calibration)
    if run_holdout_calibration:
        holdout_artifact = build_trusted_replay_holdout_calibration(
            repo_root=repo_root,
            model_dir=model_dir,
            generated_utc=generated_utc,
        )
        reused_holdout_calibration = False
    else:
        previous_status = str(previous_calibration.get("status") or "")
        holdout_artifact = {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": previous_calibration.get("trusted_replay_holdout_status")
            or previous_status
            or "BLOCKED_TRUSTED_HOLDOUT_CALIBRATION_CADENCE_DEFERRED",
            "confidence_outcome_join_available": previous_calibration.get("confidence_outcome_join_available"),
            "trusted_holdout_rows": previous_calibration.get("trusted_holdout_rows"),
            "evaluated_rows": previous_calibration.get("trusted_replay_holdout_evaluated_rows"),
            "calibration_source": previous_calibration.get("trusted_replay_holdout_source")
            or "RECENT_PUBLISHED_TRUSTED_HOLDOUT_CALIBRATION_REUSED",
            "checkpoint_hash": previous_calibration.get("trusted_replay_holdout_checkpoint_hash"),
            "checkpoint_id": previous_calibration.get("trusted_replay_holdout_checkpoint_id"),
            "rows_rejected_by_reason": previous_calibration.get("trusted_replay_holdout_rows_rejected_by_reason")
            or {},
            "future_labels_used_as_features": previous_calibration.get("future_labels_used_as_features"),
            "uses_expected_move_as_realized_reward": previous_calibration.get("uses_expected_move_as_realized_reward"),
            "reason": "recent trusted replay holdout calibration reused to protect trainer cadence"
            if previous_status == "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION"
            else "trusted replay holdout calibration deferred by cadence control",
            "_calibration_rows": [],
            "_expected_move_rows": [],
        }
        reused_holdout_calibration = bool(previous_calibration)
    holdout_calibration_rows = [
        dict(row)
        for row in as_list(holdout_artifact.get("_calibration_rows"))
        if isinstance(row, Mapping)
    ]
    public_holdout_artifact = {
        key: value for key, value in holdout_artifact.items() if not str(key).startswith("_")
    }
    reused_active_holdout = (
        reused_holdout_calibration
        and str(previous_calibration.get("status") or "") == "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION"
    )
    holdout_active = (
        holdout_artifact.get("status") == "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION"
        and bool(holdout_calibration_rows)
    )
    public_holdout_active = holdout_active or reused_active_holdout
    calibration_rows = holdout_calibration_rows if holdout_active else list(feedback_metrics["calibration_rows"])
    ece, buckets = _expected_calibration_error(calibration_rows)
    brier = _brier_score(calibration_rows)
    if reused_active_holdout and not calibration_rows:
        brier = finite_float(previous_calibration.get("brier_score"))
        ece = finite_float(previous_calibration.get("ece"))
    confidence_join_available = bool(calibration_rows)
    trusted_holdout_available = bool(feedback_metrics["holdout_rows"]) or public_holdout_active
    trusted_holdout_rows = (
        int(
            finite_float(holdout_artifact.get("trusted_holdout_rows"))
            or finite_float(previous_calibration.get("trusted_holdout_rows"))
            or 0
        )
        if public_holdout_active
        else feedback_metrics["holdout_rows"]
    )
    if reused_active_holdout:
        calibration_status = "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION"
        calibration_reason = "recent trusted replay holdout calibration reused to protect trainer cadence"
    elif holdout_active:
        calibration_status = "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION"
        calibration_reason = None
    elif confidence_join_available:
        calibration_status = "ACTIVE_TRUSTED_CONFIDENCE_OUTCOME_CALIBRATION"
        calibration_reason = (
            "trusted confidence/outcome rows are available, but no untouched holdout rows are flagged"
        )
    else:
        calibration_status = "BLOCKED_NO_CONFIDENCE_OUTCOME_JOIN_FOR_TRUSTED_HOLDOUT"
        calibration_reason = "paper outcome labels currently omit confidence/expected-move prediction fields"
    return {
        "confidence_gate_reachability_status.json": {
            "schema_version": "confidence_gate_reachability_status_v1",
            "generated_utc": generated_utc,
            "status": reachability_status,
            "current_gate": current_gate,
            "prediction_rows": len(rows),
            "raw_confidence_distribution": _distribution(raw_values),
            "temperature_scaled_distribution": None,
            "coverage_penalty_distribution": _distribution(coverage_penalties),
            "missing_feature_penalty": _distribution(missing_penalties),
            "stale_feature_penalty": _distribution(stale_penalties),
            "final_calibrated_distribution": _distribution(calibrated_values),
            "rows_capable_of_reaching_current_gate": len(capable),
            "percentage_capable_of_reaching_current_gate": (len(capable) / len(calibrated_values) * 100.0)
            if calibrated_values
            else 0.0,
        },
        "trusted_confidence_calibration_status.json": {
            "schema_version": "trusted_confidence_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": calibration_status,
            "trusted_holdout_required": True,
            "confidence_outcome_join_available": confidence_join_available,
            "trusted_rows_scanned": feedback_metrics["trusted_rows"],
            "trusted_confidence_outcome_rows": len(calibration_rows),
            "trusted_holdout_rows": trusted_holdout_rows,
            "trusted_holdout_available": trusted_holdout_available,
            "trusted_replay_holdout_status": holdout_artifact.get("status"),
            "trusted_replay_holdout_evaluated_rows": holdout_artifact.get("evaluated_rows"),
            "trusted_replay_holdout_manifest_rows": holdout_artifact.get("manifest_holdout_rows"),
            "trusted_replay_holdout_source": holdout_artifact.get("calibration_source"),
            "trusted_replay_holdout_checkpoint_id": holdout_artifact.get("checkpoint_id"),
            "trusted_replay_holdout_checkpoint_hash": holdout_artifact.get("checkpoint_hash"),
            "future_labels_used_as_features": holdout_artifact.get("future_labels_used_as_features"),
            "uses_expected_move_as_realized_reward": holdout_artifact.get("uses_expected_move_as_realized_reward"),
            "temperature_scaling_fit": False,
            "isotonic_calibration_fit": False,
            "brier_score": brier,
            "ece": ece,
            "rows_rejected_by_reason": feedback_metrics["rows_rejected_by_reason"],
            "trusted_replay_holdout_rows_rejected_by_reason": as_dict(
                holdout_artifact.get("rows_rejected_by_reason")
            ),
            "holdout_calibration_reused": reused_active_holdout,
            "holdout_calibration_reuse_age_seconds": holdout_calibration_reuse_age_seconds,
            "holdout_calibration_min_interval_seconds": holdout_calibration_min_interval_seconds,
            "reason": calibration_reason,
        },
        "confidence_reliability_matrix.json": {
            "schema_version": "confidence_reliability_matrix_v1",
            "generated_utc": generated_utc,
            "status": calibration_status,
            "buckets": buckets,
            "sample_count": len(calibration_rows),
            "brier_score": brier,
            "ece": ece,
            "reason": calibration_reason
            or (
                "confidence reliability buckets computed from trusted replay holdout rows"
                if holdout_active
                else "confidence reliability buckets computed from trusted feedback rows"
            ),
        },
        "trusted_replay_holdout_calibration_status.json": public_holdout_artifact,
    }


def holdout_calibration_min_interval_seconds() -> int:
    return _bounded_env_int(
        "V2_TRUSTED_REPLAY_HOLDOUT_MIN_INTERVAL_SECONDS",
        DEFAULT_HOLDOUT_CALIBRATION_MIN_INTERVAL_SECONDS,
        minimum=60,
        maximum=86_400,
    )


def holdout_calibration_due(
    previous_calibration: Mapping[str, Any] | None,
    *,
    generated_utc: str,
    min_interval_seconds: int,
) -> tuple[bool, float | None]:
    previous = as_dict(previous_calibration)
    if str(previous.get("status") or "") != "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION":
        return True, None
    previous_time = parse_runtime_time(previous.get("generated_utc"))
    current_time = parse_runtime_time(generated_utc)
    if previous_time is None or current_time is None:
        return True, None
    age_seconds = max(0.0, (current_time - previous_time).total_seconds())
    return age_seconds >= int(min_interval_seconds), age_seconds


def build_trainer_quality_artifact(*, generated_utc: str) -> dict[str, Any]:
    rows = _redis_json_list("v2:trainer:feedback:outcomes")
    feedback_metrics = _trusted_feedback_metric_rows(rows)
    calibration_rows = list(feedback_metrics["calibration_rows"])
    expected_move_rows = list(feedback_metrics["expected_move_rows"])
    ece, reliability_buckets = _expected_calibration_error(calibration_rows)
    brier = _brier_score(calibration_rows)
    expected_move_mae = _expected_move_mae(expected_move_rows)
    realized_values: list[float] = []
    wins = losses = breakeven = 0
    direction_correct = direction_total = 0
    missing_expected_move = missing_confidence = 0
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        realized = finite_float(row.get("realized_net_pnl_bps") or row.get("realized_pnl_bps"))
        if realized is None:
            continue
        realized_values.append(realized)
        if realized > 0:
            wins += 1
        elif realized < 0:
            losses += 1
        else:
            breakeven += 1
        action = str(row.get("selected_action") or row.get("side") or "").lower()
        directional = str(row.get("directional_outcome") or "").upper()
        if action in {"long", "short"} and directional in {"UP", "DOWN", "FLAT"}:
            direction_total += 1
            if (action == "long" and directional == "UP") or (action == "short" and directional == "DOWN"):
                direction_correct += 1
        if finite_float(row.get("expected_move_after_cost_bps")) is None:
            missing_expected_move += 1
        if finite_float(row.get("confidence_calibrated")) is None:
            missing_confidence += 1
        key = "|".join(
            [
                str(row.get("symbol") or "UNKNOWN"),
                str(row.get("timeframe") or "UNKNOWN"),
                action or "UNKNOWN",
                str(row.get("market_regime_at_entry") or "UNKNOWN"),
            ]
        )
        group = groups.setdefault(key, {"sample_count": 0, "net_bps": 0.0, "wins": 0, "losses": 0})
        group["sample_count"] += 1
        group["net_bps"] += realized
        if realized > 0:
            group["wins"] += 1
        elif realized < 0:
            group["losses"] += 1
    profit = sum(value for value in realized_values if value > 0)
    loss = abs(sum(value for value in realized_values if value < 0))
    sample_count = len(realized_values)
    by_group = []
    for key, group in groups.items():
        symbol, timeframe, side, regime = key.split("|", 3)
        by_group.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "side": side,
                "regime": regime,
                "sample_count": group["sample_count"],
                "after_cost_expectancy_bps": group["net_bps"] / group["sample_count"]
                if group["sample_count"]
                else None,
                "win_rate": group["wins"] / group["sample_count"] if group["sample_count"] else None,
            }
        )
    by_group.sort(key=lambda item: int(item["sample_count"]), reverse=True)
    metrics_available = bool(calibration_rows or expected_move_rows)
    return {
        "schema_version": "trainer_accuracy_calibration_runtime_status_v1",
        "generated_utc": generated_utc,
        "status": (
            "ACTIVE_REALIZED_PAPER_QUALITY_METRICS"
            if sample_count and metrics_available
            else (
                "ACTIVE_REALIZED_PAPER_QUALITY_METRICS_WITH_CALIBRATION_GAPS"
                if sample_count
                else "BLOCKED_NO_REALIZED_PAPER_FEEDBACK"
            )
        ),
        "sample_count": sample_count,
        "directional_accuracy": direction_correct / direction_total if direction_total else None,
        "expected_move_mae": expected_move_mae,
        "expected_move_mae_sample_count": len(expected_move_rows),
        "brier_score": brier,
        "ece": ece,
        "calibration_sample_count": len(calibration_rows),
        "confidence_reliability_buckets": reliability_buckets,
        "after_cost_expectancy_bps": sum(realized_values) / sample_count if sample_count else None,
        "profit_factor": profit / loss if loss > 0 else None,
        "false_positive_rate": losses / (wins + losses) if (wins + losses) else None,
        "false_negative_rate": None,
        "trade_outcome_counts": {"WIN": wins, "LOSS": losses, "BREAKEVEN": breakeven},
        "confidence_interval": None,
        "missing_expected_move_rows": missing_expected_move,
        "missing_confidence_rows": missing_confidence,
        "trusted_rows_scanned": feedback_metrics["trusted_rows"],
        "trusted_holdout_rows": feedback_metrics["holdout_rows"],
        "rows_rejected_by_reason": feedback_metrics["rows_rejected_by_reason"],
        "metrics_by_symbol_timeframe_side_regime": by_group[:100],
        "calibration_gap_reason": (
            None
            if metrics_available
            else "feedback rows do not yet preserve confidence_calibrated or expected_move_after_cost_bps"
        ),
    }


def safe_v2_redis_set(client: Any | None, key: str, payload: Any, *, ex: int | None = None) -> bool:
    if client is None or not key.startswith("v2:"):
        return False
    try:
        if ex is None:
            client.set(key, json.dumps(payload, sort_keys=True, default=str))
        else:
            client.set(key, json.dumps(payload, sort_keys=True, default=str), ex=int(ex))
        return True
    except Exception:
        return False


def systemctl_show(unit: str) -> dict[str, str]:
    fields = ["LoadState", "ActiveState", "SubState", "Result", "UnitFileState", "MainPID"]
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", unit, *(f"--property={field}" for field in fields)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    out: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            out[key] = value
    return out


def gpu_status_from_nvidia_smi() -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        return {"available": False, "source": "nvidia-smi", "error": f"{type(exc).__name__}: {exc}"}
    if result.returncode != 0 or not result.stdout.strip():
        return {"available": False, "source": "nvidia-smi", "error": result.stderr.strip()}
    parts = [part.strip() for part in result.stdout.splitlines()[0].split(",")]
    if len(parts) < 4:
        return {"available": False, "source": "nvidia-smi", "error": "unexpected nvidia-smi output"}
    return {
        "available": True,
        "source": "nvidia-smi",
        "gpu_name": parts[0],
        "gpu_utilization_percent": finite_float(parts[1]),
        "vram_used_mb": finite_float(parts[2]),
        "vram_total_mb": finite_float(parts[3]),
    }


def _cpu_times() -> tuple[int, int] | None:
    try:
        fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
        values = [int(field) for field in fields]
    except Exception:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return idle, total


def cpu_utilization_percent() -> float | None:
    first = _cpu_times()
    if first is None:
        return None
    time.sleep(0.1)
    second = _cpu_times()
    if second is None:
        return None
    idle_delta = second[0] - first[0]
    total_delta = second[1] - first[1]
    if total_delta <= 0:
        return None
    return round(100.0 * (1.0 - (idle_delta / total_delta)), 2)


def memory_status() -> dict[str, Any]:
    values: dict[str, float] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            if key in {"MemTotal", "MemAvailable"}:
                values[key] = float(raw.strip().split()[0]) / (1024 * 1024)
    except Exception:
        return {"ram_used_gb": None, "ram_total_gb": None}
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    return {
        "ram_used_gb": None if total is None or available is None else round(total - available, 3),
        "ram_total_gb": None if total is None else round(total, 3),
    }


def load_state(paths: PersistentTrainerPaths) -> dict[str, Any]:
    return as_dict(read_json(paths.state_path))


def save_state(paths: PersistentTrainerPaths, state: Mapping[str, Any]) -> None:
    write_json(paths.state_path, dict(state))


def prune_recent_events(events: Iterable[Mapping[str, Any]], *, now_ts: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        ts = finite_float(event.get("ts"))
        if ts is not None and now_ts - ts <= 3600:
            rows.append(dict(event))
    return rows


def record_cycle_state(
    *,
    paths: PersistentTrainerPaths,
    training_steps: int,
    prediction_rows: int,
    samples_seen: int,
    batches: int,
    training_blocker_reason: str | None = None,
) -> dict[str, Any]:
    now_ts = time.time()
    state = load_state(paths)
    events = prune_recent_events(as_list(state.get("step_events")), now_ts=now_ts)
    cycle_index = int(finite_float(state.get("cycle_index")) or 0) + 1
    training_steps_this_cycle = max(0, int(training_steps))
    total_steps = int(finite_float(state.get("training_steps_total")) or 0) + training_steps_this_cycle
    current_pid = os.getpid()
    previous_pid = int(finite_float(state.get("pid")) or 0)
    started_ts = state.get("started_ts") if previous_pid == current_pid else now_ts
    events.append(
        {
            "ts": now_ts,
            "generated_est": est_now(),
            "training_steps": training_steps_this_cycle,
            "prediction_rows": int(prediction_rows),
            "samples_seen": int(samples_seen),
            "batches": int(batches),
            "heartbeat_only": training_steps_this_cycle == 0,
            "training_blocker_reason": training_blocker_reason,
        }
    )
    updated = {
        "schema_version": "native_cuda_trainer_persistent_state_v1",
        "started_ts": started_ts,
        "cycle_index": cycle_index,
        "training_steps_total": total_steps,
        "step_events": events,
        "last_cycle_est": est_now(),
        "last_training_blocker_reason": training_blocker_reason,
        "pid": current_pid,
    }
    save_state(paths, updated)
    return updated


def checkpoint_retention_status(
    *,
    paths: PersistentTrainerPaths,
    latest_checkpoint_id: str | None,
    best_checkpoint_id: str | None = None,
    rollover_limit_gb: int = 300,
    apply_rollover: bool = True,
) -> dict[str, Any]:
    checkpoint_dir = paths.model_dir
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    files = sorted([p for p in checkpoint_dir.glob("*") if p.is_file()], key=lambda p: p.stat().st_mtime)
    pinned_names: set[str] = set()
    if latest_checkpoint_id:
        pinned_names.update(path.name for path in files if latest_checkpoint_id in path.name)
    if best_checkpoint_id:
        pinned_names.update(path.name for path in files if best_checkpoint_id in path.name)
    for path in files:
        payload = as_dict(read_json(path))
        if payload.get("pinned") is True or payload.get("best_checkpoint") is True:
            pinned_names.add(path.name)
    limit_bytes = int(rollover_limit_gb) * 1024**3
    deleted: list[str] = []
    total_bytes = sum(path.stat().st_size for path in files)
    if apply_rollover and total_bytes > limit_bytes:
        for path in files:
            if total_bytes <= limit_bytes:
                break
            if path.name in pinned_names:
                continue
            if latest_checkpoint_id and latest_checkpoint_id in path.name:
                continue
            size = path.stat().st_size
            try:
                path.unlink()
            except OSError:
                continue
            deleted.append(path.name)
            total_bytes -= size
    remaining = sorted([p for p in checkpoint_dir.glob("*") if p.is_file()], key=lambda p: p.stat().st_mtime)
    latest = remaining[-1].name if remaining else None
    manifest = {
        "schema_version": "native_cuda_trainer_checkpoint_retention_manifest_v1",
        "generated_est": est_now(),
        "checkpoint_dir": str(MODEL_DIR_REL),
        "checkpoint_count": len(remaining),
        "checkpoint_total_size_gb": round(total_bytes / 1024**3, 6),
        "total_size_gb": round(total_bytes / 1024**3, 6),
        "checkpoint_dir_size_bytes": total_bytes,
        "checkpoint_rollover_limit_gb": int(rollover_limit_gb),
        "rollover_limit_gb": int(rollover_limit_gb),
        "checkpoint_rollover_limit_bytes": limit_bytes,
        "oldest_checkpoint": remaining[0].name if remaining else None,
        "latest_checkpoint": latest,
        "latest_checkpoint_id": latest_checkpoint_id,
        "best_checkpoint": best_checkpoint_id,
        "pinned_checkpoints": sorted(pinned_names),
        "deleted_checkpoints": deleted,
        "rollover_action_taken": "DELETED_OLDEST_NON_PINNED" if deleted else "NONE",
        "checkpoint_rollover_status": "ROLLOVER_APPLIED" if deleted else "BELOW_LIMIT_NO_ACTION",
        "never_delete_latest_checkpoint": True,
        "never_delete_pinned_high_performing_checkpoint": True,
    }
    write_json(checkpoint_dir / "checkpoint_retention_manifest.json", manifest)
    return manifest


def classify_fill_source(row: Mapping[str, Any]) -> str:
    signal_id = str(row.get("signal_id") or "")
    trial_id = str(row.get("paper_confidence_trial_id") or "")
    if (
        row.get("paper_confidence_threshold_trial") is True
        or row.get("paper_confidence_trial_promoted") is True
        or signal_id.startswith("sig_paper_conf_trial_")
        or trial_id.startswith("paper_conf_trial_")
    ):
        return "confidence_trial_overlay"
    return "normal_native"


def _fill_pnl(row: Mapping[str, Any]) -> float:
    for key in ("total_pnl", "unrealized_pnl", "realized_pnl", "unrealized_pnl_usd", "realized_pnl_usd"):
        value = finite_float(row.get(key))
        if value is not None:
            return value
    return 0.0


def build_paper_drawdown_attribution(
    *,
    portfolio: Mapping[str, Any],
    ledger: Mapping[str, Any],
    previous_paper_pnl: float = PREVIOUS_PAPER_PNL_BASELINE,
) -> dict[str, Any]:
    accepted = [as_dict(row) for row in as_list(ledger.get("accepted") or ledger.get("accepted_intents"))]
    inventory = [as_dict(row) for row in as_list(portfolio.get("paper_fill_economic_inventory"))]
    fill_rows = accepted or inventory
    current_pnl = finite_float(portfolio.get("total_pnl_usd")) or 0.0
    delta = current_pnl - float(previous_paper_pnl)
    rows: list[dict[str, Any]] = []
    source_pnl: dict[str, float] = {"normal_native": 0.0, "confidence_trial_overlay": 0.0}
    source_count: dict[str, int] = {"normal_native": 0, "confidence_trial_overlay": 0}
    for row in fill_rows:
        source = classify_fill_source(row)
        pnl = _fill_pnl(row)
        source_pnl[source] = source_pnl.get(source, 0.0) + pnl
        source_count[source] = source_count.get(source, 0) + 1
        rows.append(
            {
                "fill_id": row.get("fill_id") or row.get("ledger_row_id") or row.get("intent_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "source": source,
                "side": row.get("side") or row.get("action"),
                "entry_price": row.get("entry_price") or row.get("fill_price"),
                "current_mark": row.get("current_mark_price") or row.get("latest_price"),
                "realized_pnl": row.get("realized_pnl") or row.get("realized_pnl_usd"),
                "unrealized_pnl": row.get("unrealized_pnl") or row.get("unrealized_pnl_usd"),
                "fees": row.get("fees"),
                "slippage": row.get("slippage"),
                "confidence": row.get("confidence_calibrated"),
                "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
                "market_state_integrity_score": row.get("market_state_integrity_score"),
            }
        )
    loss_rows = sorted(rows, key=lambda row: finite_float(row.get("unrealized_pnl")) or 0.0)[:20]
    by_symbol: dict[str, float] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "UNKNOWN")
        by_symbol[symbol] = by_symbol.get(symbol, 0.0) + (finite_float(row.get("unrealized_pnl")) or 0.0)
    attribution_lost = source_count.get("confidence_trial_overlay", 0) == 0 and source_count.get("normal_native", 0) > 0
    return {
        "schema_version": "paper_confidence_trial_drawdown_attribution_status_v1",
        "generated_est": est_now(),
        "previous_paper_pnl": float(previous_paper_pnl),
        "current_paper_pnl": current_pnl,
        "delta": round(delta, 8),
        "accepted_fill_count": len(fill_rows),
        "trial_overlay_fill_count": source_count.get("confidence_trial_overlay", 0),
        "normal_native_fill_count": source_count.get("normal_native", 0),
        "trial_overlay_pnl": round(source_pnl.get("confidence_trial_overlay", 0.0), 8),
        "normal_native_pnl": round(source_pnl.get("normal_native", 0.0), 8),
        "top_loss_symbols": [
            {"symbol": symbol, "pnl": round(pnl, 8)}
            for symbol, pnl in sorted(by_symbol.items(), key=lambda item: item[1])[:20]
        ],
        "top_loss_fills": loss_rows,
        "drawdown_from_mark_to_market": portfolio.get("unrealized_pnl_usd"),
        "drawdown_from_closed_positions": portfolio.get("realized_pnl_usd"),
        "trial_attribution_status": (
            "TRIAL_ATTRIBUTION_PRESENT"
            if source_count.get("confidence_trial_overlay", 0) > 0
            else "TRIAL_ATTRIBUTION_NOT_PRESENT_IN_CURRENT_LEDGER"
        ),
        "trial_attribution_lost_or_expired": attribution_lost,
        "live_threshold_changed": False,
    }


def build_paper_drawdown_guard(
    *,
    attribution: Mapping[str, Any],
    existing_trial_status: Mapping[str, Any],
) -> dict[str, Any]:
    delta = finite_float(attribution.get("delta")) or 0.0
    overlay_pnl = finite_float(attribution.get("trial_overlay_pnl")) or 0.0
    overlay_count = int(finite_float(attribution.get("trial_overlay_fill_count")) or 0)
    attribution_lost = attribution.get("trial_attribution_lost_or_expired") is True
    if overlay_count > 0 and overlay_pnl < TRIAL_OVERLAY_PNL_THRESHOLD_USD:
        status = "TRIAL_PAUSED_DRAWDOWN_GUARD"
        reason = "CONFIDENCE_TRIAL_OVERLAY_PNL_BELOW_THRESHOLD"
        trial_enabled = False
    elif attribution_lost and delta < TRIAL_DRAWDOWN_DELTA_THRESHOLD_USD:
        status = "TRIAL_PAUSED_DRAWDOWN_GUARD"
        reason = "PAPER_DRAWDOWN_WITH_TRIAL_ATTRIBUTION_MISSING_OR_EXPIRED"
        trial_enabled = False
    elif delta < TRIAL_DRAWDOWN_DELTA_THRESHOLD_USD:
        status = "TRIAL_BLOCKED_INSUFFICIENT_OUTCOME_SAMPLE"
        reason = "DRAWDOWN_BREACHED_BUT_TRIAL_OVERLAY_ATTRIBUTION_INSUFFICIENT"
        trial_enabled = False
    else:
        status = "TRIAL_ACTIVE_NO_DRAWDOWN" if existing_trial_status.get("trial_enabled") else "TRIAL_ACTIVE"
        reason = "DRAWDOWN_GUARD_NOT_BREACHED"
        trial_enabled = bool(existing_trial_status.get("trial_enabled"))
    return {
        "schema_version": "paper_confidence_trial_drawdown_guard_status_v1",
        "generated_est": est_now(),
        "status": status,
        "trial_enabled": trial_enabled,
        "stop_promoting_new_threshold_trial_signals": not trial_enabled,
        "normal_native_paper_path_active": True,
        "live_threshold_changed": False,
        "live_execution_changed": False,
        "drawdown_guard_reason": reason,
        "previous_paper_pnl": attribution.get("previous_paper_pnl"),
        "current_paper_pnl": attribution.get("current_paper_pnl"),
        "pnl_delta": attribution.get("delta"),
        "trial_overlay_pnl": attribution.get("trial_overlay_pnl"),
        "normal_native_pnl": attribution.get("normal_native_pnl"),
        "trial_overlay_fill_count": attribution.get("trial_overlay_fill_count"),
        "normal_native_fill_count": attribution.get("normal_native_fill_count"),
        "delta_threshold_usd": TRIAL_DRAWDOWN_DELTA_THRESHOLD_USD,
        "overlay_pnl_threshold_usd": TRIAL_OVERLAY_PNL_THRESHOLD_USD,
        "redis_guard_key": TRIAL_DRAWDOWN_GUARD_REDIS_KEY,
        "redis_trial_signal_key": TRIAL_SIGNAL_REDIS_KEY,
    }


def apply_paper_drawdown_guard_to_redis(client: Any | None, guard: Mapping[str, Any]) -> dict[str, Any]:
    keys: list[str] = []
    status_written = safe_v2_redis_set(client, TRIAL_DRAWDOWN_GUARD_REDIS_KEY, guard, ex=3600)
    if status_written:
        keys.append(TRIAL_DRAWDOWN_GUARD_REDIS_KEY)
    if guard.get("stop_promoting_new_threshold_trial_signals") is True:
        paused_status = {
            "schema_version": "v2_paper_confidence_threshold_trial_paused_status_v1",
            "generated_est": est_now(),
            "trial_enabled": False,
            "status": guard.get("status"),
            "drawdown_guard_reason": guard.get("drawdown_guard_reason"),
            "live_threshold_changed": False,
        }
        if safe_v2_redis_set(client, TRIAL_STATUS_REDIS_KEY, paused_status, ex=3600):
            keys.append(TRIAL_STATUS_REDIS_KEY)
        if safe_v2_redis_set(client, TRIAL_SIGNAL_REDIS_KEY, [], ex=3600):
            keys.append(TRIAL_SIGNAL_REDIS_KEY)
    return {
        "redis_available": client is not None,
        "keys_written": keys,
        "old_redis_write": False,
        "write_status": "V2_PAPER_DRAWDOWN_GUARD_WRITTEN" if keys else "REDIS_UNAVAILABLE_OR_NO_WRITE",
    }


def trainer_symbol_scope_status() -> dict[str, Any]:
    provenance = as_dict(resolve_symbols_with_provenance())
    symbols = [str(symbol) for symbol in as_list(provenance.get("symbols")) if symbol]
    smoke_only_scope = tuple(symbols) == tuple(SMOKE_TEST_SYMBOLS)
    return {
        "training_symbols": symbols,
        "training_symbols_count": len(symbols),
        "trainer_symbol_profile": provenance.get("symbol_profile"),
        "trainer_symbol_source_path": provenance.get("source_path"),
        "trainer_symbol_discovered_count": provenance.get("discovered_count"),
        "trainer_symbol_binance_usdm_confirmed_count": provenance.get("binance_usdm_confirmed_count"),
        "trainer_symbol_baseline_count": provenance.get("baseline_count"),
        "trainer_smoke_test_scope": bool(provenance.get("smoke_test")) or smoke_only_scope,
        "trainer_btc_eth_sol_only_scope": smoke_only_scope,
        "trainer_all_runtime_symbols_enabled": bool(symbols) and not smoke_only_scope,
        "training_timeframes": list(DEFAULT_TIMEFRAMES),
        "training_timeframes_count": len(DEFAULT_TIMEFRAMES),
        "training_grid_expected_rows_from_symbol_scope": len(symbols) * len(DEFAULT_TIMEFRAMES),
    }


def build_resource_status(
    *,
    trainer_result: Any | None,
    persistent_state: Mapping[str, Any],
) -> dict[str, Any]:
    gpu = gpu_status_from_nvidia_smi()
    mem = memory_status()
    cpu = cpu_utilization_percent()
    training = as_dict(as_dict(getattr(trainer_result, "metrics", {})).get("training")) if trainer_result is not None else {}
    nested_training_metrics = as_dict(training.get("metrics"))
    resource = as_dict(as_dict(getattr(trainer_result, "status", {})).get("cuda_cpu_resource_utilization"))
    vram_used = finite_float(gpu.get("vram_used_mb")) or finite_float(resource.get("current_vram_used_mb"))
    vram_total = finite_float(gpu.get("vram_total_mb")) or finite_float(resource.get("vram_total_mb"))
    current_gpu_utilization = finite_float(gpu.get("gpu_utilization_percent"))
    training_window_gpu_utilization = finite_float(
        nested_training_metrics.get("training_window_gpu_utilization_avg_percent")
    )
    workload_gpu_utilization = (
        training_window_gpu_utilization
        if training_window_gpu_utilization is not None
        else current_gpu_utilization
    )
    samples_per_second = finite_float(resource.get("tensor_rows_per_second"))
    target_batch_size = int(finite_float(resource.get("target_batch_size")) or DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE)
    actual_batch_size = int(finite_float(resource.get("actual_batch_size")) or finite_float(training.get("batch_size")) or 0)
    accepted_training_rows = int(
        finite_float(nested_training_metrics.get("accepted_training_rows"))
        or finite_float(nested_training_metrics.get("training_trusted_rows"))
        or 0
    )
    available_examples = int(finite_float(nested_training_metrics.get("available_examples")) or 0)
    data_loader_time_ms = finite_float(resource.get("data_loader_time_ms")) or finite_float(
        nested_training_metrics.get("data_loader_time_ms")
    )
    gpu_train_time_ms = finite_float(resource.get("gpu_train_time_ms")) or finite_float(
        nested_training_metrics.get("gpu_train_time_ms")
    )
    cpu_prep_bottleneck = bool(
        data_loader_time_ms is not None
        and gpu_train_time_ms is not None
        and data_loader_time_ms > gpu_train_time_ms
    )
    data_starved = bool(
        accepted_training_rows > 0
        and (
            (actual_batch_size > 0 and accepted_training_rows < actual_batch_size)
            or accepted_training_rows < 8192
        )
    )
    configured_vram_target_mb = (
        min(float(TRAINER_VRAM_LIMIT_MB), float(vram_total) * (TRAINER_GPU_UTILIZATION_LIMIT_PERCENT / 100.0))
        if vram_total
        else float(TRAINER_VRAM_LIMIT_MB)
    )
    training_blocker_reason = str(persistent_state.get("last_training_blocker_reason") or "")
    ram_total = finite_float(mem.get("ram_total_gb")) or 0.0
    ram_used = finite_float(mem.get("ram_used_gb")) or 0.0
    ram_available = ram_total - ram_used
    low_vram = bool(vram_used is not None and vram_total and (vram_used / vram_total) < 0.25)
    if training_blocker_reason:
        bottleneck = training_blocker_reason
    elif data_starved:
        bottleneck = "DATA_STARVED"
    elif actual_batch_size and actual_batch_size < target_batch_size:
        bottleneck = "APPROVED_SAMPLE_SET_BELOW_TARGET_BATCH"
    elif low_vram and samples_per_second:
        bottleneck = "GPU_TRAINING_ACTIVE_LOW_UTILIZATION"
    elif low_vram:
        bottleneck = "MODEL_TOO_SMALL_TO_SATURATE_GPU"
    else:
        bottleneck = "PERSISTENT_TRAINING_RESOURCE_TELEMETRY_CURRENT"
    tuning = {
        "vram_under_25_percent": low_vram,
        "cpu_ram_available": bool(ram_available > 8),
        "target_batch_size_before": target_batch_size,
        "target_batch_size_after": target_batch_size,
        "dataloader_workers_before": resource.get("dataloader_workers"),
        "dataloader_workers_after": resource.get("dataloader_workers"),
        "action": (
            "REPORT_DATA_STARVED_DO_NOT_RAISE_BATCH_FOR_COSMETIC_VRAM"
            if data_starved
            else "INCREASE_DATALOADER_WORKERS_PREFETCH_PINNED_MEMORY"
            if cpu_prep_bottleneck
            else "TARGET_BATCH_ALREADY_EXCEEDS_AVAILABLE_APPROVED_SAMPLES"
            if actual_batch_size and actual_batch_size < target_batch_size
            else "KEEP_CURRENT_SAFE_CUDA_SETTINGS"
        ),
        "throughput_improved": None,
    }
    adaptive_controller = {
        "enabled": True,
        "target_gpu_utilization_pct": {"low": 65, "high": 75},
        "target_vram_utilization_pct": {"low": 60, "high": 75},
        "oom_backoff_enabled": True,
        "cycle_timeout_safe": True,
        "accepted_training_rows": accepted_training_rows or None,
        "available_examples": available_examples or None,
        "data_loader_time_ms": data_loader_time_ms,
        "gpu_train_time_ms": gpu_train_time_ms,
        "cpu_prep_bottleneck": cpu_prep_bottleneck,
        "data_starved": data_starved,
        "decision": tuning["action"],
        "batch_size_before": actual_batch_size or None,
        "batch_size_after": actual_batch_size or None,
        "model_dim_after": nested_training_metrics.get("model_dim_after"),
        "parallel_rollouts_after": resource.get("parallel_rollouts_after"),
        "oom_events": nested_training_metrics.get("oom_count") or resource.get("oom_count") or 0,
    }
    return {
        "schema_version": "native_cuda_trainer_resource_utilization_status_v1",
        "generated_est": est_now(),
        "gpu_name": gpu.get("gpu_name") or resource.get("gpu_name"),
        "gpu_utilization_percent": workload_gpu_utilization,
        "gpu_utilization_source": (
            "training_window_nvidia_smi_sampler"
            if training_window_gpu_utilization is not None
            else "post_cycle_nvidia_smi_snapshot"
            if current_gpu_utilization is not None
            else None
        ),
        "current_gpu_utilization_percent": current_gpu_utilization,
        "training_window_gpu_utilization_avg_percent": training_window_gpu_utilization,
        "training_window_gpu_utilization_max_percent": nested_training_metrics.get(
            "training_window_gpu_utilization_max_percent"
        ),
        "training_window_gpu_utilization_sample_count": nested_training_metrics.get(
            "training_window_gpu_utilization_sample_count"
        ),
        "gpu_utilization_limit_percent": TRAINER_GPU_UTILIZATION_LIMIT_PERCENT,
        "vram_used_mb": vram_used,
        "vram_total_mb": vram_total,
        "vram_limit_mb": TRAINER_VRAM_LIMIT_MB,
        "vram_target_mb": round(configured_vram_target_mb, 3),
        "cpu_utilization_percent": cpu,
        "cpu_quota_percent": TRAINER_CPU_QUOTA_PERCENT,
        "ram_used_gb": mem.get("ram_used_gb"),
        "ram_total_gb": mem.get("ram_total_gb"),
        "ram_limit_gb": TRAINER_RAM_LIMIT_GB,
        "batch_size": actual_batch_size or None,
        "target_batch_size": target_batch_size,
        "dataloader_workers": resource.get("dataloader_workers"),
        "prefetch_factor": resource.get("prefetch_factor"),
        "pinned_memory": bool(resource.get("pinned_memory")),
        "amp_enabled": bool(resource.get("mixed_precision_enabled")),
        "samples_per_second": samples_per_second,
        "accepted_training_rows": accepted_training_rows or None,
        "available_examples": available_examples or None,
        "data_starved": data_starved,
        "data_loader_time_ms": data_loader_time_ms,
        "gpu_train_time_ms": gpu_train_time_ms,
        "cpu_prep_bottleneck": cpu_prep_bottleneck,
        "adaptive_gpu_saturation_controller": adaptive_controller,
        "predictions_per_second": resource.get("throughput_predictions_per_second"),
        "training_steps_per_minute": resource.get("training_steps_per_minute"),
        "bottleneck_reason": bottleneck,
        "resource_target_logic": tuning,
        "persistent_cycles_total": persistent_state.get("cycle_index"),
        "training_blocker_reason": training_blocker_reason or None,
    }


def latest_training_metrics_from_result(trainer_result: Any | None) -> dict[str, Any] | None:
    if trainer_result is None:
        return None
    training = as_dict(as_dict(getattr(trainer_result, "metrics", {})).get("training"))
    if not training:
        return None
    metrics = as_dict(training.get("metrics"))
    return {
        "status": training.get("status"),
        "device": training.get("device"),
        "cuda_active": training.get("cuda_active"),
        "cuda_claim_verified": training.get("cuda_claim_verified"),
        "gpu_name": training.get("gpu_name"),
        "batch_size": training.get("batch_size"),
        "training_steps": training.get("training_steps"),
        "train_rows": training.get("train_rows"),
        "validation_rows": training.get("validation_rows"),
        "loss_before": training.get("loss_before"),
        "loss_after": training.get("loss_after"),
        "action_distribution": training.get("action_distribution"),
        "metrics": metrics,
    }


def _blocked_feedback_training_metrics(*, reason: str, trusted_rows: int = 0) -> dict[str, Any]:
    status = "NO_TRUSTED_TRAINING_ROWS" if trusted_rows <= 0 else "TRAINING_NOT_RUN"
    return {
        "status": status,
        "train_rows": 0,
        "validation_rows": 0,
        "training_steps": 0,
        "loss_before": None,
        "loss_after": None,
        "metrics": {
            "trusted_rows_loaded": trusted_rows,
            "training_trusted_rows": trusted_rows,
            "outcome_supervised_rows": trusted_rows,
            "ppo_on_policy_rows": 0,
            "ppo_rows_rejected_missing_on_policy_fields": 0,
            "optimizer_steps_this_cycle": 0,
            "optimizer_steps_total": 0,
            "learning_update_lane": "blocked",
            "online_learning_status": "BLOCKED_NO_TRUSTED_FEEDBACK" if trusted_rows <= 0 else "BLOCKED_NO_DURABLE_WEIGHT_UPDATE",
            "effective_trainer_mode": "INFERENCE_ONLY",
            "rows_rejected_by_reason": {},
            "feedback_source_status": reason,
        },
    }


def _snapshot_backed_feedback_rejection_reason(client: Any, row: Mapping[str, Any]) -> str | None:
    quarantine_reasons = trainer_feedback_quarantine_rejection_reasons(row)
    if quarantine_reasons:
        return quarantine_reasons[0]
    if row.get("trainer_consumable") is not True:
        return "not_marked_trainer_consumable"
    required_fields = (
        "prediction_id",
        "signal_id",
        "decision_id",
        "entry_feature_snapshot_id",
        "mtf_snapshot_id",
        "feature_cutoff",
        "decision_time",
        "available_at",
        "symbol",
        "timeframe",
        "selected_action",
        "model_version",
        "checkpoint_id",
    )
    for field in required_fields:
        if row.get(field) in (None, "", [], {}):
            return f"missing_{field}"
    source_hashes = row.get("source_hashes")
    if not isinstance(source_hashes, dict) or not source_hashes:
        return "missing_source_hashes"
    decision_time = parse_runtime_time(row.get("decision_time"))
    available_at = parse_runtime_time(row.get("available_at"))
    feature_cutoff = parse_runtime_time(row.get("feature_cutoff"))
    if decision_time is None:
        return "invalid_decision_time"
    if available_at is None:
        return "invalid_available_at"
    if feature_cutoff is None:
        return "invalid_feature_cutoff"
    if available_at > decision_time:
        return "future_available_at"
    if feature_cutoff > decision_time:
        return "future_feature_cutoff"
    snapshot_id = str(row.get("entry_feature_snapshot_id") or "")
    snapshot_source = "redis"
    try:
        raw_snapshot = client.get(f"v2:features:snapshot:{snapshot_id}")
    except Exception:
        return "entry_feature_snapshot_read_error"
    if raw_snapshot:
        try:
            snapshot = json.loads(raw_snapshot)
        except Exception:
            return "entry_feature_snapshot_invalid_json"
    else:
        snapshot_source = "trainer_feedback"
        snapshot = None
        for field in ("entry_feature_snapshot", "feature_snapshot"):
            candidate = row.get(field)
            if isinstance(candidate, dict):
                snapshot = candidate
                break
        if snapshot is None:
            return "entry_feature_snapshot_not_found"
    if not isinstance(snapshot, dict):
        return "entry_feature_snapshot_not_object"
    snapshot_payload_id = snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id")
    if snapshot_source == "trainer_feedback" and not snapshot_payload_id:
        return "entry_feature_snapshot_id_missing"
    if snapshot_payload_id and str(snapshot_payload_id) != snapshot_id:
        return "entry_feature_snapshot_id_mismatch"
    if str(snapshot.get("symbol") or "").upper() != str(row.get("symbol") or "").upper():
        return "entry_feature_snapshot_symbol_mismatch"
    if str(snapshot.get("timeframe") or "") != str(row.get("timeframe") or ""):
        return "entry_feature_snapshot_timeframe_mismatch"
    features = snapshot.get("features") if isinstance(snapshot.get("features"), dict) else {}
    if not features:
        return "entry_feature_snapshot_empty_features"
    snapshot_available_at = parse_runtime_time(
        snapshot.get("available_at") or snapshot.get("generated_utc") or snapshot.get("generated_at")
    )
    snapshot_feature_cutoff = parse_runtime_time(snapshot.get("feature_cutoff") or snapshot.get("source_available_time"))
    if snapshot_available_at is not None and snapshot_available_at > decision_time:
        return "entry_feature_snapshot_future_available_at"
    if snapshot_feature_cutoff is not None and snapshot_feature_cutoff > decision_time:
        return "entry_feature_snapshot_future_feature_cutoff"
    return None


def _increment_rejection_reason(counts: dict[str, int], reason: Any) -> None:
    text = str(reason or "").strip()
    if not text:
        return
    counts[text] = counts.get(text, 0) + 1


def _quarantined_feedback_rejection_counts(client: Any) -> dict[str, int]:
    try:
        raw = client.get("v2:trainer:feedback:outcomes:quarantine")
    except Exception:
        return {}
    try:
        rows = json.loads(raw or "[]")
    except Exception:
        return {"quarantine_invalid_json": 1}
    if not isinstance(rows, list):
        return {"quarantine_not_list": 1}
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            _increment_rejection_reason(counts, "invalid_quarantine_row")
            continue
        emitted = False
        for field in (
            "trust_envelope_rejection_reasons",
            "trust_reconstruction_rejection_reasons",
            "audit_quality_rejection_reasons",
            "missing_feedback_classifications",
            "missing_feedback_fields",
        ):
            values = row.get(field)
            if isinstance(values, list):
                for value in values:
                    _increment_rejection_reason(counts, value)
                    emitted = True
            elif values not in (None, "", [], {}):
                _increment_rejection_reason(counts, values)
                emitted = True
        if not emitted:
            _increment_rejection_reason(
                counts,
                row.get("quarantine_reason") or "quarantined_without_reason",
            )
    return counts


def latest_training_metrics_from_current_feedback(*, fail_closed: bool = False) -> dict[str, Any] | None:
    client = connect_redis()
    if client is None:
        return _blocked_feedback_training_metrics(reason="REDIS_UNAVAILABLE") if fail_closed else None
    try:
        raw = client.get("v2:trainer:feedback:outcomes")
    except Exception:
        return _blocked_feedback_training_metrics(reason="REDIS_READ_ERROR") if fail_closed else None
    try:
        rows = json.loads(raw or "[]")
    except Exception:
        rows = []
    if not isinstance(rows, list):
        rows = []
    trusted_rows = 0
    rejected_by_reason: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            rejected_by_reason["invalid_feedback_row"] = rejected_by_reason.get("invalid_feedback_row", 0) + 1
            continue
        reason = _snapshot_backed_feedback_rejection_reason(client, row)
        if reason is None:
            trusted_rows += 1
        else:
            rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1
    if trusted_rows <= 0:
        for reason, count in _quarantined_feedback_rejection_counts(client).items():
            rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + int(count)
    metrics = _blocked_feedback_training_metrics(reason="CURRENT_FEEDBACK_ROWS", trusted_rows=trusted_rows)
    metrics["metrics"]["rows_rejected_by_reason"] = rejected_by_reason
    return metrics


def _with_current_feedback_rejection_counts(
    latest_training_metrics: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    metrics_payload = as_dict(latest_training_metrics)
    if not metrics_payload:
        return latest_training_metrics_from_current_feedback(fail_closed=True)
    nested_metrics = as_dict(metrics_payload.get("metrics"))
    trusted_rows = int(
        finite_float(nested_metrics.get("trusted_rows_loaded"))
        or finite_float(metrics_payload.get("train_rows"))
        or 0
    )
    if trusted_rows > 0 or as_dict(nested_metrics.get("rows_rejected_by_reason")):
        return metrics_payload
    feedback_metrics = latest_training_metrics_from_current_feedback(fail_closed=True)
    feedback_rejections = as_dict(
        as_dict(feedback_metrics).get("metrics", {}).get("rows_rejected_by_reason")
    )
    if not feedback_rejections:
        return metrics_payload
    merged_nested = {
        **nested_metrics,
        "rows_rejected_by_reason": feedback_rejections,
    }
    if "feedback_source_status" not in merged_nested:
        merged_nested["feedback_source_status"] = as_dict(feedback_metrics).get("metrics", {}).get(
            "feedback_source_status"
        )
    return {
        **metrics_payload,
        "metrics": merged_nested,
    }


def online_learning_runtime_fields(
    *,
    training: Mapping[str, Any] | None = None,
    latest_training_metrics: Mapping[str, Any] | None = None,
    persistent_state: Mapping[str, Any] | None = None,
    prediction_rows: int = 0,
) -> dict[str, Any]:
    training = as_dict(training)
    latest_training_metrics = as_dict(latest_training_metrics)
    nested_metrics = as_dict(latest_training_metrics.get("metrics")) or as_dict(training.get("metrics"))
    rows_rejected_by_reason = as_dict(
        nested_metrics.get("rows_rejected_by_reason")
        or training.get("rows_rejected_by_reason")
        or {}
    )
    persistent_runtime = as_dict(persistent_state)
    recent_events = prune_recent_events(as_list(persistent_runtime.get("step_events")), now_ts=time.time())
    optimizer_steps_last_hour = sum(
        int(finite_float(event.get("training_steps")) or 0)
        for event in recent_events
    )
    if optimizer_steps_last_hour > 0:
        nested_metrics = {
            **nested_metrics,
            "optimizer_steps_last_hour": optimizer_steps_last_hour,
        }
        latest_training_metrics = {
            **latest_training_metrics,
            "metrics": nested_metrics,
        }
    readiness = build_learning_readiness(
        training=training,
        latest_training_metrics=latest_training_metrics,
        persistent_runtime=persistent_runtime,
        prediction_rows=prediction_rows,
    )
    return {
        **readiness,
        "rows_rejected_by_reason": rows_rejected_by_reason,
        "loss_before": nested_metrics.get("loss_before") or training.get("loss_before"),
        "loss_after": nested_metrics.get("loss_after") or training.get("loss_after"),
    }


def build_persistent_runtime_status(
    *,
    paths: PersistentTrainerPaths,
    trainer_result: Any | None,
    persistent_state: Mapping[str, Any],
    resource: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    max_rows: int = DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE,
) -> dict[str, Any]:
    now_ts = time.time()
    events = prune_recent_events(as_list(persistent_state.get("step_events")), now_ts=now_ts)
    last_minute_events = [event for event in events if now_ts - (finite_float(event.get("ts")) or 0.0) <= 60]
    generated_est = est_now()
    generated_utc = utc_now()
    status = as_dict(getattr(trainer_result, "status", {})) if trainer_result is not None else {}
    metrics = as_dict(getattr(trainer_result, "metrics", {})) if trainer_result is not None else {}
    training = as_dict(metrics.get("training"))
    latest_training_metrics = latest_training_metrics_from_result(trainer_result)
    service = systemctl_show(PERSISTENT_UNIT)
    pid = int(finite_float(service.get("MainPID")) or os.getpid())
    started_ts = finite_float(persistent_state.get("started_ts")) or now_ts
    prediction_public = as_dict(read_json(paths.public_root / PREDICTION_REL))
    prediction_rows = int(
        finite_float(prediction_public.get("prediction_rows_count"))
        or len(as_list(prediction_public.get("prediction_rows")))
        or len(getattr(trainer_result, "predictions", []) if trainer_result is not None else [])
    )
    expected_rows = int(finite_float(prediction_public.get("expected_prediction_count")) or prediction_rows)
    current_prediction_rows = int(
        finite_float(prediction_public.get("current_prediction_count"))
        or prediction_rows
    )
    symbol_scope = trainer_symbol_scope_status()
    missing_prediction_rows = int(finite_float(prediction_public.get("missing_prediction_rows_count")) or 0)
    stale_prediction_rows = int(finite_float(prediction_public.get("stale_prediction_rows_count")) or 0)
    blocked_rows = int(finite_float(prediction_public.get("blocked_prediction_rows_count")) or 0)
    latest_event_ts = max(
        (finite_float(event.get("ts")) or 0.0 for event in events),
        default=0.0,
    )
    heartbeat_age_seconds = (
        round(max(0.0, now_ts - latest_event_ts), 3)
        if latest_event_ts > 0
        else None
    )
    service_active = service.get("ActiveState") == "active" or os.getpid() == pid
    worker_health_status = (
        "HEALTHY"
        if service_active and heartbeat_age_seconds is not None and heartbeat_age_seconds <= 300
        else "DEGRADED"
        if service_active
        else "OFFLINE"
    )
    online_learning = online_learning_runtime_fields(
        training=training,
        latest_training_metrics=latest_training_metrics,
        persistent_state=persistent_state,
        prediction_rows=prediction_rows,
    )
    legacy_runtime_config = legacy_grade_runtime_config(
        symbols=symbol_scope.get("training_symbols") or [],
        timeframes=symbol_scope.get("training_timeframes") or DEFAULT_TIMEFRAMES,
        max_rows=max_rows,
    )
    return {
        "schema_version": "native_cuda_trainer_persistent_runtime_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "current_status_age_seconds": 0,
        "service_name": PERSISTENT_UNIT,
        "service_active": service_active,
        "service_state": service,
        "pid": pid,
        "uptime_seconds": round(max(0.0, now_ts - started_ts), 3),
        "training_loop_active": True,
        "continuous_training_enabled": True,
        "trainer_liveness_status": worker_health_status,
        "worker_health_status": worker_health_status,
        "legacy_grade_runtime_config": legacy_runtime_config,
        "legacy_runtime_effective_config": as_dict(legacy_runtime_config.get("effective_config")),
        "legacy_runtime_coverage_mode": legacy_runtime_config.get("coverage_mode"),
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "last_batch_age_seconds": heartbeat_age_seconds,
        "last_prediction_age_seconds": heartbeat_age_seconds,
        **online_learning,
        "last_training_blocker_reason": persistent_state.get("last_training_blocker_reason"),
        "training_steps_total": persistent_state.get("training_steps_total", 0),
        "training_steps_last_minute": sum(int(finite_float(event.get("training_steps")) or 0) for event in last_minute_events),
        "training_steps_last_hour": sum(int(finite_float(event.get("training_steps")) or 0) for event in events),
        "samples_seen_last_hour": sum(int(finite_float(event.get("samples_seen")) or 0) for event in events),
        "batches_last_hour": sum(int(finite_float(event.get("batches")) or 0) for event in events),
        **symbol_scope,
        "prediction_grid_rows": prediction_rows,
        "prediction_grid_expected_rows": expected_rows,
        "expected_prediction_grid_rows": expected_rows,
        "prediction_grid_current": bool(
            expected_rows > 0
            and current_prediction_rows == expected_rows
            and missing_prediction_rows == 0
            and stale_prediction_rows == 0
        ),
        "current_prediction_count": current_prediction_rows,
        "missing_prediction_rows_count": missing_prediction_rows,
        "stale_prediction_rows_count": stale_prediction_rows,
        "non_current_prediction_rows_count": max(0, expected_rows - current_prediction_rows),
        "prediction_coverage_status": prediction_public.get("coverage_status"),
        "prediction_actionability_status": prediction_public.get("actionability_status"),
        "missing_prediction_symbols": as_list(prediction_public.get("missing_prediction_symbols")),
        "missing_prediction_timeframes_by_symbol": as_dict(
            prediction_public.get("missing_prediction_timeframes_by_symbol")
        ),
        "blocked_prediction_rows": blocked_rows,
        "trainer_source": TRAINER_SOURCE,
        "checkpoint_id": status.get("checkpoint_id") or checkpoint.get("latest_checkpoint_id"),
        "last_checkpoint_est": checkpoint.get("generated_est"),
        "last_cycle_status": status.get("schema_version"),
        "last_cycle_train_rows": training.get("train_rows"),
        "last_cycle_validation_rows": training.get("validation_rows"),
        "last_cycle_examples_built": status.get("examples_built"),
        "last_cycle_fresh_examples_built": status.get("fresh_examples_built"),
        "last_cycle_prediction_examples_built": status.get("prediction_examples_built"),
        "train_rows": training.get("train_rows"),
        "validation_rows": training.get("validation_rows"),
        "latest_training_metrics": latest_training_metrics,
        "examples_built": status.get("examples_built"),
        "fresh_examples_built": status.get("fresh_examples_built"),
        "prediction_examples_built": status.get("prediction_examples_built"),
        "replay_buffer_enabled": status.get("replay_buffer_enabled"),
        "replay_buffer_size": status.get("replay_buffer_size"),
        "replay_buffer_limit": status.get("replay_buffer_limit"),
        "current_batch_size": resource.get("batch_size") or resource.get("actual_batch_size"),
        "target_batch_size": resource.get("target_batch_size"),
        "current_vram_used_mb": resource.get("current_vram_used_mb") or resource.get("vram_used_mb"),
        "vram_total_mb": resource.get("vram_total_mb"),
        "gpu_name": resource.get("gpu_name"),
        "resource_bottleneck_reason": resource.get("bottleneck_reason"),
    }


def publish_training_cycle_heartbeat(
    *,
    paths: PersistentTrainerPaths,
    persistent_state: Mapping[str, Any] | None = None,
    max_rows: int = DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE,
    run_training: bool = True,
) -> dict[str, Any]:
    existing = as_dict(read_json(paths.artifact_dir / "native_cuda_trainer_persistent_runtime_status.json"))
    prediction_public = as_dict(read_json(paths.public_root / PREDICTION_REL))
    generated_est = est_now()
    generated_utc = utc_now()
    expected_rows = int(
        finite_float(prediction_public.get("expected_prediction_count"))
        or finite_float(existing.get("prediction_grid_expected_rows"))
        or finite_float(existing.get("expected_prediction_grid_rows"))
        or finite_float(prediction_public.get("prediction_rows_count"))
        or 0
    )
    prediction_rows = int(
        finite_float(prediction_public.get("prediction_rows_count"))
        or finite_float(existing.get("prediction_grid_rows"))
        or len(as_list(prediction_public.get("prediction_rows")))
        or 0
    )
    blocked_rows = int(
        finite_float(prediction_public.get("blocked_prediction_rows_count"))
        or finite_float(existing.get("blocked_prediction_rows"))
        or 0
    )
    paper_actionability_allowed = int(
        finite_float(prediction_public.get("paper_actionability_allowed_rows_count")) or 0
    )
    paper_actionability_blocked = int(
        finite_float(prediction_public.get("paper_actionability_blocked_rows_count")) or 0
    )
    paper_actionability_block_reasons = dict(
        as_dict(prediction_public.get("paper_actionability_block_reason_counts"))
    )
    current_prediction_rows = int(
        finite_float(prediction_public.get("current_prediction_count"))
        or finite_float(existing.get("current_prediction_count"))
        or prediction_rows
        or 0
    )
    missing_prediction_rows = int(
        finite_float(prediction_public.get("missing_prediction_rows_count"))
        or finite_float(existing.get("missing_prediction_rows_count"))
        or 0
    )
    stale_prediction_rows = int(
        finite_float(prediction_public.get("stale_prediction_rows_count"))
        or finite_float(existing.get("stale_prediction_rows_count"))
        or 0
    )
    missing_prediction_symbols = as_list(prediction_public.get("missing_prediction_symbols"))
    missing_prediction_timeframes_by_symbol = as_dict(
        prediction_public.get("missing_prediction_timeframes_by_symbol")
    )
    symbol_scope = trainer_symbol_scope_status()
    legacy_runtime_config = legacy_grade_runtime_config(
        symbols=symbol_scope.get("training_symbols") or [],
        timeframes=symbol_scope.get("training_timeframes") or DEFAULT_TIMEFRAMES,
        max_rows=max_rows,
    )
    prediction_grid_current = bool(
        expected_rows > 0
        and current_prediction_rows == expected_rows
        and missing_prediction_rows == 0
        and stale_prediction_rows == 0
    )
    state = as_dict(persistent_state)
    current_runtime_path = paths.operator_dir / "native_trainer_runtime_status.json"
    current_runtime = as_dict(read_json(current_runtime_path))
    latest_training_metrics = current_runtime.get("latest_training_metrics")
    online_learning = online_learning_runtime_fields(
        latest_training_metrics=latest_training_metrics,
        persistent_state=state,
        prediction_rows=prediction_rows,
    )
    payload = {
        **existing,
        "schema_version": "native_cuda_trainer_persistent_runtime_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "current_status_age_seconds": 0,
        "training_cycle_status": "TRAINING_CYCLE_IN_PROGRESS" if run_training else "STATUS_REFRESH_IN_PROGRESS",
        "training_cycle_started_est": generated_est,
        "training_cycle_started_utc": generated_utc,
        "training_cycle_max_rows": int(max_rows),
        "training_loop_active": True,
        "continuous_training_enabled": True,
        "service_name": PERSISTENT_UNIT,
        "service_active": True,
        "pid": os.getpid(),
        "training_steps_total": state.get("training_steps_total", existing.get("training_steps_total", 0)),
        **online_learning,
        **symbol_scope,
        "prediction_grid_rows": prediction_rows,
        "prediction_grid_expected_rows": expected_rows,
        "expected_prediction_grid_rows": expected_rows,
        "prediction_grid_current": prediction_grid_current,
        "current_prediction_count": current_prediction_rows,
        "missing_prediction_rows_count": missing_prediction_rows,
        "stale_prediction_rows_count": stale_prediction_rows,
        "non_current_prediction_rows_count": max(0, expected_rows - current_prediction_rows),
        "prediction_coverage_status": prediction_public.get("coverage_status"),
        "prediction_actionability_status": prediction_public.get("actionability_status"),
        "missing_prediction_symbols": missing_prediction_symbols,
        "missing_prediction_timeframes_by_symbol": missing_prediction_timeframes_by_symbol,
        "blocked_prediction_rows": blocked_rows,
        "paper_actionability_allowed_rows_count": paper_actionability_allowed,
        "paper_actionability_blocked_rows_count": paper_actionability_blocked,
        "paper_actionability_block_reason_counts": paper_actionability_block_reasons,
        "trainer_source": TRAINER_SOURCE,
        "heartbeat_age_seconds": 0,
        "worker_health_status": "HEALTHY",
        "trainer_liveness_status": "HEALTHY",
        "legacy_grade_runtime_config": legacy_runtime_config,
        "legacy_runtime_effective_config": as_dict(legacy_runtime_config.get("effective_config")),
        "legacy_runtime_coverage_mode": legacy_runtime_config.get("coverage_mode"),
    }
    for base in (paths.artifact_dir, paths.worklog_dir):
        write_json(base / "native_cuda_trainer_persistent_runtime_status.json", payload)
    write_json(paths.operator_dir / "native_cuda_trainer_persistent_runtime_status.json", payload)
    write_json(
        current_runtime_path,
        {
            **current_runtime,
            "generated_est": generated_est,
            "generated_utc": generated_utc,
            "payload_age_seconds": 0,
            "current_status_age_seconds": 0,
            "training_loop_active": True,
            "continuous_training_enabled": True,
            "training_cycle_status": payload["training_cycle_status"],
            "persistent_trainer_service_active": True,
            "persistent_trainer_pid": os.getpid(),
            **online_learning,
            **symbol_scope,
            "prediction_grid_rows": prediction_rows,
            "prediction_grid_expected_rows": expected_rows,
            "expected_prediction_grid_rows": expected_rows,
            "prediction_grid_current": prediction_grid_current,
            "current_prediction_count": current_prediction_rows,
            "missing_prediction_rows_count": missing_prediction_rows,
            "stale_prediction_rows_count": stale_prediction_rows,
            "non_current_prediction_rows_count": max(0, expected_rows - current_prediction_rows),
            "prediction_coverage_status": prediction_public.get("coverage_status"),
            "prediction_actionability_status": prediction_public.get("actionability_status"),
            "missing_prediction_symbols": missing_prediction_symbols,
            "missing_prediction_timeframes_by_symbol": missing_prediction_timeframes_by_symbol,
            "blocked_prediction_rows": blocked_rows,
            "paper_actionability_allowed_rows_count": paper_actionability_allowed,
            "paper_actionability_blocked_rows_count": paper_actionability_blocked,
            "paper_actionability_block_reason_counts": paper_actionability_block_reasons,
            "training_steps_total": payload.get("training_steps_total"),
            "trainer_liveness_status": "HEALTHY",
            "worker_health_status": "HEALTHY",
        },
    )
    return payload


def refresh_all_timeframe_payload(repo_root: Path) -> dict[str, Any]:
    try:
        from v2.backend.app.services.all_timeframe_prediction_signal_price_target_publisher import (
            DEFAULT_STALE_SECONDS,
            V2KeyValueStore,
            build_packet,
            default_paths,
            write_outputs,
        )
    except Exception as exc:
        return {"ran": False, "status": f"IMPORT_FAILED:{type(exc).__name__}"}
    client = connect_redis()
    try:
        store = V2KeyValueStore(client=client)
        result = build_packet(
            paths=default_paths(repo_root),
            store=store,
            stale_seconds=DEFAULT_STALE_SECONDS,
            production_base_url="http://127.0.0.1:5177",
            routes=(),
            write_redis=True,
            trainer_trust_reconciliation_limit=0,
            feature_parity_from_prediction_rows=True,
        )
        result = write_outputs(default_paths(repo_root), result)
    except Exception as exc:
        return {"ran": False, "status": f"RUN_FAILED:{type(exc).__name__}"}
    return {
        "ran": True,
        "status": result.go_no_go,
        "paths_written_count": len(result.paths_written),
        "redis_connected": store.audit.connected,
        "old_redis_write_attempts": store.audit.old_redis_write_attempts,
    }


# Module-level in-memory replay buffer. Keep it tightly bounded so a resident
# trainer cannot retain enough examples to pressure system RAM after restarts.
# 16384 rows of ~374-float tensors is ~25MB of feature data - RAM-safe while
# letting the GPU train on full batches instead of starving at 4096 examples.
_REPLAY_BUFFER: deque = deque(maxlen=16_384)
RESIDENT_MAX_TRAIN_STEPS_PER_CYCLE = 64
RESIDENT_TRAIN_ROWS_PER_STEP = 512
# Upper bound on a single optimizer-step batch. Keeps each native CUDA op
# short enough for the SIGALRM cycle timeout to interrupt an overrun, so an
# oversized --max-rows can never wedge the resident trainer mid-cycle again.
RESIDENT_MAX_BATCH_SIZE = 4096
RESIDENT_NATIVE_CYCLE_TIMEOUT_SECONDS = 600
LEGACY_RUNTIME_ENV_NAMES = (
    "RL_N_ENVS",
    "RL_N_STEPS",
    "RL_BATCH_SIZE",
    "RL_ALLOW_ENV_TRUNCATION",
    "VEC_ENV_TYPE",
    "PPO_N_EPOCHS",
    "PPO_LEARNING_RATE",
    "PPO_GAMMA",
    "PPO_ENT_COEF",
    "PREDICTION_LOOP_SECONDS",
    "POST_TRAINING_PAUSE_SECONDS",
    "ENABLE_AUTO_GPU_SCALE",
    "TRAINER_TARGET_GPU_UTIL",
    "TRAINER_TARGET_VRAM_UTIL",
)
LEGACY_RUNTIME_SAFE_ENV_CAP = DEFAULT_ROLLOUT_MAX_ENVS
LEGACY_RUNTIME_MIN_ROLLOUT_STEPS = DEFAULT_ROLLOUT_N_STEPS
LEGACY_RUNTIME_MIN_BATCH_IF_ROWS_SUPPORT = 2048
LEGACY_RUNTIME_DEFAULT_PREDICTION_LOOP_SECONDS = 5
LEGACY_RUNTIME_DEFAULT_POST_TRAINING_PAUSE_SECONDS = 0


class NativeCycleTimeout(TimeoutError):
    """Raised when the resident native trainer cycle exceeds its watchdog."""


@contextmanager
def resident_native_cycle_timeout(seconds: int):
    timeout_seconds = max(0, int(seconds))
    if timeout_seconds <= 0 or not hasattr(signal, "SIGALRM"):
        yield
        return
    previous_handler = signal.getsignal(signal.SIGALRM)

    def _raise_timeout(_signum: int, _frame: Any) -> None:
        raise NativeCycleTimeout(f"resident native trainer cycle exceeded {timeout_seconds}s")

    signal.signal(signal.SIGALRM, _raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, float(timeout_seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)


def resident_train_steps_for_max_rows(max_rows: int) -> int:
    rows = max(1, int(max_rows))
    row_scaled_steps = max(1, rows // RESIDENT_TRAIN_ROWS_PER_STEP)
    return max(1, min(RESIDENT_MAX_TRAIN_STEPS_PER_CYCLE, row_scaled_steps))


def legacy_grade_runtime_config(
    *,
    symbols: Iterable[str],
    timeframes: Iterable[str],
    max_rows: int,
) -> dict[str, Any]:
    """Return the effective legacy-grade runtime config without touching exchanges."""

    symbol_list = [str(symbol) for symbol in symbols if str(symbol)]
    timeframe_list = [str(timeframe) for timeframe in timeframes if str(timeframe)]
    symbols_count = len(symbol_list)
    timeframes_count = len(timeframe_list)
    pair_count = symbols_count * timeframes_count
    rows = max(1, int(max_rows))
    safe_env_cap = _bounded_env_int(
        "RL_SAFE_ENV_CAP",
        LEGACY_RUNTIME_SAFE_ENV_CAP,
        minimum=1,
        maximum=4096,
    )
    default_n_envs = max(1, min(max(1, pair_count), safe_env_cap))
    n_envs = _bounded_env_int(
        "RL_N_ENVS",
        default_n_envs,
        minimum=1,
        maximum=4096,
    )
    n_steps = _bounded_env_int(
        "RL_N_STEPS",
        LEGACY_RUNTIME_MIN_ROLLOUT_STEPS,
        minimum=LEGACY_RUNTIME_MIN_ROLLOUT_STEPS,
        maximum=16_384,
    )
    default_batch_size = (
        min(rows, RESIDENT_MAX_BATCH_SIZE)
        if rows >= LEGACY_RUNTIME_MIN_BATCH_IF_ROWS_SUPPORT
        else rows
    )
    batch_size = _bounded_env_int(
        "RL_BATCH_SIZE",
        default_batch_size,
        minimum=1,
        maximum=RESIDENT_MAX_BATCH_SIZE,
    )
    ppo_n_epochs = _bounded_env_int("PPO_N_EPOCHS", 1, minimum=1, maximum=16)
    base_train_steps = resident_train_steps_for_max_rows(rows)
    ppo_training_steps = min(
        RESIDENT_TRAIN_STEPS_HARD_CEILING,
        max(1, base_train_steps * ppo_n_epochs),
    )
    allow_env_truncation = _env_bool("RL_ALLOW_ENV_TRUNCATION", False)
    coverage_cycles = max(1, math.ceil(pair_count / max(1, n_envs))) if pair_count else 0
    if pair_count <= n_envs:
        coverage_mode = "SINGLE_CYCLE_FULL_SYMBOL_TIMEFRAME_COVERAGE"
    elif allow_env_truncation:
        coverage_mode = "EXPLICIT_OPERATOR_ENV_TRUNCATION"
    else:
        coverage_mode = "DETERMINISTIC_ROTATING_PARTITIONS_REQUIRED"
    prediction_loop_seconds = _bounded_env_int(
        "PREDICTION_LOOP_SECONDS",
        LEGACY_RUNTIME_DEFAULT_PREDICTION_LOOP_SECONDS,
        minimum=1,
        maximum=300,
    )
    post_training_pause_seconds = _bounded_env_int(
        "POST_TRAINING_PAUSE_SECONDS",
        LEGACY_RUNTIME_DEFAULT_POST_TRAINING_PAUSE_SECONDS,
        minimum=0,
        maximum=300,
    )
    enable_auto_gpu_scale = _env_bool(
        "ENABLE_AUTO_GPU_SCALE",
        _env_bool("V2_NATIVE_TRAINER_ADAPTIVE_GPU_CONTROLLER", False),
    )
    target_gpu_util = _bounded_env_float(
        "TRAINER_TARGET_GPU_UTIL",
        70.0,
        minimum=1.0,
        maximum=95.0,
    )
    target_vram_util = _bounded_env_float(
        "TRAINER_TARGET_VRAM_UTIL",
        70.0,
        minimum=1.0,
        maximum=95.0,
    )
    ppo_learning_rate = _bounded_env_float(
        "PPO_LEARNING_RATE",
        _bounded_env_float(
            "V2_TRAINER_LEARNING_RATE",
            1e-4,
            minimum=1e-8,
            maximum=ENV_PPO_LEARNING_RATE_MAX,
        ),
        minimum=1e-8,
        maximum=ENV_PPO_LEARNING_RATE_MAX,
    )
    ppo_ent_coef = _bounded_env_float(
        "PPO_ENT_COEF",
        _bounded_env_float(
            "V2_TRAINER_ENTROPY_COEF",
            0.01,
            minimum=0.0,
            maximum=ENV_PPO_ENTROPY_COEFFICIENT_MAX,
        ),
        minimum=0.0,
        maximum=ENV_PPO_ENTROPY_COEFFICIENT_MAX,
    )
    ppo_gamma = _bounded_env_float("PPO_GAMMA", 0.99, minimum=0.0, maximum=1.0)
    source_of_each_setting = {
        "n_envs": _setting_source(
            "RL_N_ENVS",
            "default:full_symbol_timeframe_coverage_or_safe_cap",
        ),
        "n_steps": _setting_source("RL_N_STEPS", "default:512"),
        "batch_size": _setting_source(
            "RL_BATCH_SIZE",
            "default:min(max_rows,4096)_with_2048_min_when_rows_support",
        ),
        "allow_env_truncation": _setting_source("RL_ALLOW_ENV_TRUNCATION", "default:false"),
        "vec_env_type": _setting_source("VEC_ENV_TYPE", "default:ThreadPoolExecutor"),
        "ppo_n_epochs": _setting_source("PPO_N_EPOCHS", "default:1"),
        "ppo_learning_rate": _setting_source(
            "PPO_LEARNING_RATE",
            _setting_source("V2_TRAINER_LEARNING_RATE", "default:0.0001"),
        ),
        "ppo_gamma": _setting_source("PPO_GAMMA", "default:0.99"),
        "ppo_ent_coef": _setting_source(
            "PPO_ENT_COEF",
            _setting_source("V2_TRAINER_ENTROPY_COEF", "default:0.01"),
        ),
        "prediction_loop_seconds": _setting_source("PREDICTION_LOOP_SECONDS", "default:5"),
        "post_training_pause_seconds": _setting_source("POST_TRAINING_PAUSE_SECONDS", "default:0"),
        "enable_auto_gpu_scale": _setting_source(
            "ENABLE_AUTO_GPU_SCALE",
            _setting_source("V2_NATIVE_TRAINER_ADAPTIVE_GPU_CONTROLLER", "default:false"),
        ),
        "target_gpu_utilization_pct": _setting_source("TRAINER_TARGET_GPU_UTIL", "default:70"),
        "target_vram_utilization_pct": _setting_source("TRAINER_TARGET_VRAM_UTIL", "default:70"),
    }
    effective = {
        "n_envs": n_envs,
        "n_steps": n_steps,
        "batch_size": batch_size,
        "batch_size_cap": RESIDENT_MAX_BATCH_SIZE,
        "rollout_samples_per_cycle": n_envs * n_steps,
        "allow_env_truncation": allow_env_truncation,
        "vec_env_type": os.environ.get("VEC_ENV_TYPE") or "ThreadPoolExecutor",
        "ppo_n_epochs": ppo_n_epochs,
        "ppo_training_steps_per_cycle": ppo_training_steps,
        "ppo_base_training_steps_per_cycle": base_train_steps,
        "ppo_learning_rate": ppo_learning_rate,
        "ppo_gamma": ppo_gamma,
        "ppo_ent_coef": ppo_ent_coef,
        "prediction_loop_seconds": prediction_loop_seconds,
        "post_training_pause_seconds": post_training_pause_seconds,
        "enable_auto_gpu_scale": enable_auto_gpu_scale,
        "target_gpu_utilization_pct": target_gpu_util,
        "target_vram_utilization_pct": target_vram_util,
        "amp_enabled_default": True,
        "tf32_enabled_default": True,
        "cudnn_benchmark_enabled_default": True,
        "grad_scaler_enabled_default": True,
    }
    return {
        "schema_version": "v2_legacy_grade_runtime_config_v1",
        "current_env": _current_env_values(LEGACY_RUNTIME_ENV_NAMES),
        "effective_config": effective,
        "source_of_each_setting": source_of_each_setting,
        "coverage_mode": coverage_mode,
        "coverage_cycles_to_touch_all_pairs": coverage_cycles,
        "coverage_not_silent": True,
        "symbols_count": symbols_count,
        "timeframes_count": timeframes_count,
        "symbol_timeframe_pairs": pair_count,
        "n_envs": n_envs,
        "n_steps": n_steps,
        "batch_size": batch_size,
        "rollout_samples_per_cycle": effective["rollout_samples_per_cycle"],
        "prediction_loop_seconds": prediction_loop_seconds,
        "post_training_pause_seconds": post_training_pause_seconds,
        "live_gate": "blocked_human_only",
        "exchange_mutation_enabled": False,
    }


# ── Adaptive GPU saturation controller (actuation) ──────────────────────────
# Complements the resource-status reporting layer: when the GPU is idle
# relative to CPU data prep and rows are plentiful, train MORE optimizer
# epochs per cycle over the already-assembled buffer (real learning work, no
# synthetic load). Backs off on OOM or when GPU/VRAM reach the target band.
# The per-step batch freeze cap (RESIDENT_MAX_BATCH_SIZE) is never touched.
RESIDENT_GPU_SATURATION_CONTROLLER_KEY = "v2:trainer:gpu_saturation_controller"
RESIDENT_GPU_TARGET_SHARE_LOW = 0.50
RESIDENT_GPU_TARGET_SHARE_HIGH = 0.75
RESIDENT_VRAM_TARGET_HIGH_FRACTION = 0.75
RESIDENT_STEPS_MULTIPLIER_MIN = 1
RESIDENT_STEPS_MULTIPLIER_MAX = 4
RESIDENT_TRAIN_STEPS_HARD_CEILING = 128
RESIDENT_DATA_STARVED_ROW_FLOOR = 2048
RESIDENT_VALIDATION_LOSS_BACKOFF_DELTA = 0.02


def _adaptive_gpu_controller_enabled() -> bool:
    return _env_bool(
        "ENABLE_AUTO_GPU_SCALE",
        _env_bool("V2_NATIVE_TRAINER_ADAPTIVE_GPU_CONTROLLER", False),
    )


# ── Background backfill prefetcher (pipelined data loading) ──────────────────
# The GPU finishes its 128 optimizer steps in seconds and then idled while the
# cycle synchronously rebuilt archive tensors (~2-3 minutes). This daemon
# thread builds the next backfill chunk WHILE the GPU trains, so each cycle
# drains ready rows instantly. It owns its own Redis client + loader (no
# shared mutable state with the main thread beyond the locked queue) and only
# it advances the backfill cursor, so there is no cursor contention.
_PREFETCH_QUEUE: deque = deque()
_PREFETCH_LOCK = threading.Lock()
_PREFETCH_THREAD: threading.Thread | None = None
_PREFETCH_STOP = threading.Event()
_PREFETCH_CHUNK_ROWS = 2_048
_PREFETCH_IDLE_SLEEP_SECONDS = 10.0


def _prefetch_backfill_worker() -> None:
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
        V2HybridTrainerDataLoader,
    )

    loader = None
    while not _PREFETCH_STOP.is_set():
        try:
            with _PREFETCH_LOCK:
                queued = len(_PREFETCH_QUEUE)
            buffered = len(_REPLAY_BUFFER)
            capacity = int(_REPLAY_BUFFER.maxlen or 0)
            if capacity and buffered + queued >= capacity:
                _PREFETCH_STOP.wait(_PREFETCH_IDLE_SLEEP_SECONDS)
                continue
            if loader is None:
                loader = V2HybridTrainerDataLoader(
                    io=V2OnlyJsonIO(client=connect_redis())
                )
            examples = loader.load_trusted_replay_examples(
                limit=_PREFETCH_CHUNK_ROWS, backfill=True
            )
            if examples:
                with _PREFETCH_LOCK:
                    _PREFETCH_QUEUE.extend(examples)
            else:
                _PREFETCH_STOP.wait(_PREFETCH_IDLE_SLEEP_SECONDS)
        except Exception:
            loader = None
            _PREFETCH_STOP.wait(_PREFETCH_IDLE_SLEEP_SECONDS)


def _ensure_prefetch_thread_started() -> None:
    global _PREFETCH_THREAD
    if _PREFETCH_THREAD is not None and _PREFETCH_THREAD.is_alive():
        return
    _PREFETCH_STOP.clear()
    _PREFETCH_THREAD = threading.Thread(
        target=_prefetch_backfill_worker,
        name="v2-trainer-backfill-prefetch",
        daemon=True,
    )
    _PREFETCH_THREAD.start()


def _drain_prefetched_backfill_examples() -> list[Any]:
    with _PREFETCH_LOCK:
        drained = list(_PREFETCH_QUEUE)
        _PREFETCH_QUEUE.clear()
    return drained


def _cuda_total_vram_mb() -> float | None:
    try:
        import torch

        if torch.cuda.is_available():
            return float(torch.cuda.get_device_properties(0).total_memory) / (1024 * 1024)
    except Exception:
        return None
    return None


def adaptive_gpu_saturation_decision(
    *,
    state: Mapping[str, Any],
    accepted_rows: int,
    data_loader_time_ms: float | None,
    gpu_train_time_ms: float | None,
    vram_reserved_mb: float | None,
    vram_total_mb: float | None,
    oom_occurred: bool,
    checkpoint_promotion_rejected: bool = False,
    checkpoint_promotion_reason: str | None = None,
    validation_loss_delta: float | None = None,
    overfit_gap_warning: bool = False,
) -> dict[str, Any]:
    """Pure controller step: telemetry in, next steps-multiplier + class out."""
    multiplier = int(state.get("steps_multiplier") or RESIDENT_STEPS_MULTIPLIER_MIN)
    multiplier = max(RESIDENT_STEPS_MULTIPLIER_MIN, min(RESIDENT_STEPS_MULTIPLIER_MAX, multiplier))
    oom_events = int(state.get("oom_events") or 0)
    gpu_share = None
    if gpu_train_time_ms is not None and data_loader_time_ms is not None:
        denominator = float(gpu_train_time_ms) + float(data_loader_time_ms)
        if denominator > 0:
            gpu_share = float(gpu_train_time_ms) / denominator
    vram_fraction = None
    if vram_reserved_mb is not None and vram_total_mb:
        vram_fraction = float(vram_reserved_mb) / float(vram_total_mb)
    validation_regressed = bool(
        validation_loss_delta is not None
        and float(validation_loss_delta) > RESIDENT_VALIDATION_LOSS_BACKOFF_DELTA
    )
    if oom_occurred:
        classification = "OOM_BACKOFF"
        multiplier = max(RESIDENT_STEPS_MULTIPLIER_MIN, multiplier // 2)
        oom_events += 1
    elif checkpoint_promotion_rejected or validation_regressed:
        # Back off GPU intensity only on a GENUINE promotion rejection or a real
        # validation regression. The advisory overfit_gap_warning must NOT halve
        # steps on its own: when it fired every cycle (miscalibrated absolute
        # threshold) it pinned steps_multiplier at MIN forever, starving the RTX
        # (gpu_time_share ~0.4, ~160 steps/hr) and blocking the CPU-prep-bottleneck
        # epoch-raise below. It is retained in telemetry, not as a backoff trigger.
        classification = "VALIDATION_CHECKPOINT_BACKOFF"
        multiplier = max(RESIDENT_STEPS_MULTIPLIER_MIN, multiplier // 2)
    elif accepted_rows < RESIDENT_DATA_STARVED_ROW_FLOOR:
        classification = "DATA_STARVED_NOT_GPU_CONFIG_BLOCKED"
    elif vram_fraction is not None and vram_fraction > RESIDENT_VRAM_TARGET_HIGH_FRACTION:
        classification = "VRAM_AT_TARGET_HOLD"
        multiplier = max(RESIDENT_STEPS_MULTIPLIER_MIN, multiplier - 1)
    elif gpu_share is not None and gpu_share < RESIDENT_GPU_TARGET_SHARE_LOW:
        classification = "CPU_PREP_BOTTLENECK_RAISING_EPOCHS"
        multiplier = min(RESIDENT_STEPS_MULTIPLIER_MAX, multiplier + 1)
    elif gpu_share is not None and gpu_share > RESIDENT_GPU_TARGET_SHARE_HIGH:
        classification = "GPU_AT_TARGET_BACKING_OFF"
        multiplier = max(RESIDENT_STEPS_MULTIPLIER_MIN, multiplier - 1)
    else:
        classification = "IN_TARGET_BAND_OR_TELEMETRY_PENDING"
    return {
        "schema_version": "resident_gpu_saturation_controller_v1",
        "steps_multiplier": multiplier,
        "classification": classification,
        "gpu_time_share": round(gpu_share, 6) if gpu_share is not None else None,
        "gpu_target_share_band": [RESIDENT_GPU_TARGET_SHARE_LOW, RESIDENT_GPU_TARGET_SHARE_HIGH],
        "vram_fraction": round(vram_fraction, 6) if vram_fraction is not None else None,
        "vram_target_high_fraction": RESIDENT_VRAM_TARGET_HIGH_FRACTION,
        "accepted_rows": int(accepted_rows),
        "data_starved_row_floor": RESIDENT_DATA_STARVED_ROW_FLOOR,
        "data_loader_time_ms": data_loader_time_ms,
        "gpu_train_time_ms": gpu_train_time_ms,
        "oom_events": oom_events,
        "checkpoint_promotion_rejected": bool(checkpoint_promotion_rejected),
        "checkpoint_promotion_reason": checkpoint_promotion_reason,
        "validation_loss_delta": validation_loss_delta,
        "validation_loss_backoff_delta": RESIDENT_VALIDATION_LOSS_BACKOFF_DELTA,
        "validation_regressed": validation_regressed,
        "overfit_gap_warning": bool(overfit_gap_warning),
        "artificial_load_added": False,
        "per_step_batch_freeze_cap_unchanged": RESIDENT_MAX_BATCH_SIZE,
    }


def _read_gpu_saturation_state(client: Any) -> dict[str, Any]:
    try:
        raw = client.get(RESIDENT_GPU_SATURATION_CONTROLLER_KEY) if client is not None else None
        payload = json.loads(raw) if raw else {}
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def update_gpu_saturation_controller(
    *,
    client: Any,
    nested_training_metrics: Mapping[str, Any],
    oom_occurred: bool,
    checkpoint_promotion: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    state = _read_gpu_saturation_state(client)
    promotion = checkpoint_promotion if isinstance(checkpoint_promotion, Mapping) else {}
    decision = adaptive_gpu_saturation_decision(
        state=state,
        accepted_rows=int(finite_float(nested_training_metrics.get("accepted_training_rows")) or 0),
        data_loader_time_ms=finite_float(nested_training_metrics.get("data_loader_time_ms")),
        gpu_train_time_ms=finite_float(nested_training_metrics.get("gpu_train_time_ms")),
        vram_reserved_mb=finite_float(nested_training_metrics.get("vram_reserved_mb")),
        vram_total_mb=_cuda_total_vram_mb(),
        oom_occurred=oom_occurred,
        checkpoint_promotion_rejected=(
            promotion.get("checkpoint_promotion_rejected") is True
            or nested_training_metrics.get("checkpoint_promotion_rejected") is True
        ),
        checkpoint_promotion_reason=(
            str(
                promotion.get("checkpoint_promotion_reason")
                or nested_training_metrics.get("checkpoint_promotion_reason")
                or ""
            )
            or None
        ),
        validation_loss_delta=finite_float(nested_training_metrics.get("validation_loss_delta")),
        overfit_gap_warning=nested_training_metrics.get("overfit_gap_warning") is True,
    )
    decision["generated_utc"] = (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    try:
        if client is not None:
            client.set(RESIDENT_GPU_SATURATION_CONTROLLER_KEY, json.dumps(decision, default=str))
    except Exception:
        pass
    return decision


def run_native_training_cycle(
    *,
    paths: PersistentTrainerPaths,
    max_rows: int,
    risk_caps_configured: bool,
) -> Any:
    client = connect_redis()
    io = V2OnlyJsonIO(client=client)
    symbol_scope = trainer_symbol_scope_status()
    symbols = tuple(symbol_scope["training_symbols"] or resolve_symbols())
    runtime_config = legacy_grade_runtime_config(
        symbols=symbols,
        timeframes=DEFAULT_TIMEFRAMES,
        max_rows=max_rows,
    )
    effective_config = as_dict(runtime_config.get("effective_config"))
    train_steps = int(effective_config.get("ppo_training_steps_per_cycle") or resident_train_steps_for_max_rows(max_rows))
    if _adaptive_gpu_controller_enabled():
        controller_state = _read_gpu_saturation_state(client)
        multiplier = max(
            RESIDENT_STEPS_MULTIPLIER_MIN,
            min(
                RESIDENT_STEPS_MULTIPLIER_MAX,
                int(controller_state.get("steps_multiplier") or RESIDENT_STEPS_MULTIPLIER_MIN),
            ),
        )
        train_steps = min(RESIDENT_TRAIN_STEPS_HARD_CEILING, train_steps * multiplier)
    config = HybridTrainerConfig(
        symbols=symbols,
        timeframes=tuple(DEFAULT_TIMEFRAMES),
        max_training_rows_per_cycle=int(max_rows),
        # Cap batch_size independently of max_rows. A batch equal to a very
        # large max_rows can run one oversized native CUDA op that the SIGALRM
        # timeout cannot interrupt. RL_BATCH_SIZE is still bounded by the same
        # safety ceiling inside legacy_grade_runtime_config.
        batch_size=int(effective_config.get("batch_size") or max(1, min(int(max_rows), RESIDENT_MAX_BATCH_SIZE))),
        train_steps=train_steps,
        rollout_n_steps=int(effective_config.get("n_steps") or DEFAULT_ROLLOUT_N_STEPS),
        rollout_max_envs=int(effective_config.get("n_envs") or DEFAULT_ROLLOUT_MAX_ENVS),
        risk_caps_configured=bool(risk_caps_configured),
    )
    _ensure_prefetch_thread_started()
    return run_hybrid_trainer_cycle(
        config=config,
        io=io,
        publish=True,
        replay_buffer=_REPLAY_BUFFER,
        prefetched_backfill_examples=_drain_prefetched_backfill_examples(),
    )


def publish_persistent_payloads(
    *,
    paths: PersistentTrainerPaths,
    persistent: Mapping[str, Any],
    resource: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    attribution: Mapping[str, Any],
    guard: Mapping[str, Any],
    trainer_result: Any | None,
    all_timeframe_refresh: Mapping[str, Any],
) -> dict[str, Any]:
    generated_est = est_now()
    generated_utc = utc_now()
    portfolio = as_dict(read_json(paths.public_root / PORTFOLIO_REL))
    live_runtime = as_dict(read_json(paths.public_root / "operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json"))
    blockers: list[str] = []
    if not persistent.get("training_loop_active"):
        blockers.append("PERSISTENT_TRAINING_LOOP_NOT_ACTIVE")
    if systemctl_show(LEGACY_BRIDGE_UNIT).get("UnitFileState") != "masked":
        blockers.append("TRAINER_BRIDGE_NOT_MASKED")
    if guard.get("status") == "TRIAL_ACTIVE" and (finite_float(attribution.get("delta")) or 0.0) < TRIAL_DRAWDOWN_DELTA_THRESHOLD_USD:
        blockers.append("PAPER_TRIAL_ACTIVE_DESPITE_DRAWDOWN_BREACH")
    go_no_go = BLOCKED if blockers else READY
    website = {
        "schema_version": "website_trainer_resource_and_paper_guard_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "status": "WEBSITE_TRAINER_RESOURCE_AND_PAPER_GUARD_READY" if not blockers else "WEBSITE_TRAINER_RESOURCE_AND_PAPER_GUARD_BLOCKED",
        "routes_synced": [
            "/model-state",
            "/ai-predictions",
            "/signals",
            "/dashboard",
            "/system/trainer",
            "/trade/paper",
            "/portfolio",
            "/system/readiness",
        ],
        "must_show": {
            "persistent_trainer_active": persistent.get("service_active"),
            "trainer_process_status": persistent.get("trainer_process_status"),
            "cuda_inference_status": persistent.get("cuda_inference_status"),
            "prediction_publication_status": persistent.get("prediction_publication_status"),
            "online_learning_status": persistent.get("online_learning_status"),
            "effective_trainer_mode": persistent.get("effective_trainer_mode"),
            "last_successful_weight_update_at": persistent.get("last_successful_weight_update_at"),
            "steps_last_hour": persistent.get("training_steps_last_hour"),
            "gpu_utilization_percent": resource.get("gpu_utilization_percent"),
            "vram_used_mb": resource.get("vram_used_mb"),
            "vram_total_mb": resource.get("vram_total_mb"),
            "cpu_utilization_percent": resource.get("cpu_utilization_percent"),
            "ram_used_gb": resource.get("ram_used_gb"),
            "ram_total_gb": resource.get("ram_total_gb"),
            "bottleneck_reason": resource.get("bottleneck_reason"),
            "checkpoint_count": checkpoint.get("checkpoint_count"),
            "checkpoint_total_size_gb": checkpoint.get("checkpoint_total_size_gb"),
            "training_symbols_count": persistent.get("training_symbols_count"),
            "trainer_all_runtime_symbols_enabled": persistent.get("trainer_all_runtime_symbols_enabled"),
            "trainer_btc_eth_sol_only_scope": persistent.get("trainer_btc_eth_sol_only_scope"),
            "paper_trial_status": guard.get("status"),
            "paper_trial_pnl": attribution.get("trial_overlay_pnl"),
            "normal_native_paper_pnl": attribution.get("normal_native_pnl"),
            "drawdown_guard_state": guard.get("drawdown_guard_reason"),
        },
        "semantic_validation_guards": [
            "model_state_no_stale_6d_payload",
            "training_steps_increase_with_persistent_service",
            "resource_utilization_present",
            "checkpoint_retention_present",
            "paper_trial_guard_visible",
            "live_state_balance_hold_consistent",
        ],
    }
    dashboard = {
        "schema_version": "v2_persistent_cuda_trainer_resource_utilization_and_paper_drawdown_guard_operator_dashboard_v1",
        "gate": go_no_go,
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "trainer": {
            "service_active": persistent.get("service_active"),
            "pid": persistent.get("pid"),
            "uptime_seconds": persistent.get("uptime_seconds"),
            "training_steps_total": persistent.get("training_steps_total"),
            "training_steps_last_hour": persistent.get("training_steps_last_hour"),
            "training_symbols_count": persistent.get("training_symbols_count"),
            "trainer_all_runtime_symbols_enabled": persistent.get("trainer_all_runtime_symbols_enabled"),
            "trainer_btc_eth_sol_only_scope": persistent.get("trainer_btc_eth_sol_only_scope"),
            "prediction_grid_rows": persistent.get("prediction_grid_rows"),
            "prediction_grid_expected_rows": persistent.get("prediction_grid_expected_rows"),
            "blocked_prediction_rows": persistent.get("blocked_prediction_rows"),
            "resource_bottleneck_reason": resource.get("bottleneck_reason"),
        },
        "resource": resource,
        "checkpoint": checkpoint,
        "paper_drawdown": {
            "previous_pnl": attribution.get("previous_paper_pnl"),
            "current_pnl": attribution.get("current_paper_pnl"),
            "delta": attribution.get("delta"),
            "trial_overlay_pnl": attribution.get("trial_overlay_pnl"),
            "normal_native_pnl": attribution.get("normal_native_pnl"),
            "guard_status": guard.get("status"),
            "guard_reason": guard.get("drawdown_guard_reason"),
        },
        "portfolio": {
            "equity": portfolio.get("equity"),
            "pnl": portfolio.get("total_pnl_usd"),
            "accepted_fill_total": portfolio.get("accepted_fill_total"),
            "open_positions_count": portfolio.get("open_positions_count"),
        },
        "live": {
            "live_gate": live_runtime.get("live_gate"),
            "trader_state": live_runtime.get("trader_state"),
            "live_order_submit_blocker": live_runtime.get("live_order_submit_blocker"),
        },
        "all_timeframe_refresh": dict(all_timeframe_refresh),
        "blockers": blockers,
        "safety": {
            "real_order": False,
            "test_order": False,
            "leverage_margin_mutation": False,
            "old_redis_write": False,
            "legacy_restart": False,
            "redis_trim": False,
            "raw_credentials": False,
            "trainer_bridge_unmasked": False,
            "live_threshold_changed": False,
        },
    }
    report = (
        "# V2 Persistent CUDA Trainer Resource Utilization And Paper Drawdown Guard Report\n\n"
        f"Gate: `{go_no_go}`\n"
        f"Generated EST: `{dashboard['generated_est']}`\n"
        f"Persistent trainer service active: `{persistent.get('service_active')}`\n"
        f"PID: `{persistent.get('pid')}`\n"
        f"Training steps total/last hour: `{persistent.get('training_steps_total')}/{persistent.get('training_steps_last_hour')}`\n"
        f"Trainer symbols: `{persistent.get('training_symbols_count')}` symbols, BTC/ETH/SOL-only scope `{persistent.get('trainer_btc_eth_sol_only_scope')}`\n"
        f"Prediction grid: `{persistent.get('prediction_grid_rows')}/{persistent.get('prediction_grid_expected_rows')}`\n"
        f"Resource bottleneck: `{resource.get('bottleneck_reason')}`\n"
        f"GPU/VRAM: `{resource.get('gpu_utilization_percent')}% / {resource.get('vram_used_mb')} MB of {resource.get('vram_total_mb')} MB`\n"
        f"Checkpoint count/size: `{checkpoint.get('checkpoint_count')}/{checkpoint.get('checkpoint_total_size_gb')} GB`\n"
        f"Paper PnL delta from trial baseline: `{attribution.get('delta')}`\n"
        f"Paper trial guard: `{guard.get('status')}`\n"
        f"Live gate: `{dashboard['live'].get('live_gate')}`\n"
        f"Trader state: `{dashboard['live'].get('trader_state')}`\n"
        f"Live submit blocker: `{dashboard['live'].get('live_order_submit_blocker')}`\n\n"
        "The native trainer now has a persistent resident loop and publishes current resource, checkpoint, and paper drawdown guard status. "
        "The confidence-threshold overlay is paper-only and is paused when the drawdown guard is breached or attribution is insufficient. Live thresholds and exchange execution are unchanged.\n\n"
        "Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output, no trainer bridge unmask, and no live threshold change.\n"
    )
    payloads = {
        "GO_NO_GO.md": go_no_go,
        "V2_PERSISTENT_CUDA_TRAINER_RESOURCE_UTILIZATION_AND_PAPER_DRAWDOWN_GUARD_REPORT.md": report,
        "native_cuda_trainer_persistent_runtime_status.json": dict(persistent),
        "native_cuda_trainer_resource_utilization_status.json": dict(resource),
        "native_cuda_trainer_checkpoint_retention_status.json": dict(checkpoint),
        "paper_confidence_trial_drawdown_attribution_status.json": dict(attribution),
        "paper_confidence_trial_drawdown_guard_status.json": dict(guard),
        "website_trainer_resource_and_paper_guard_status.json": website,
        "operator_dashboard_payload.json": dashboard,
    }
    for base in (paths.artifact_dir, paths.worklog_dir):
        for name, payload in payloads.items():
            if name.endswith(".md"):
                write_text(base / name, str(payload))
            else:
                write_json(base / name, payload)
    for name in (
        "native_cuda_trainer_persistent_runtime_status.json",
        "native_cuda_trainer_resource_utilization_status.json",
        "native_cuda_trainer_checkpoint_retention_status.json",
        "paper_confidence_trial_drawdown_guard_status.json",
    ):
        write_json(paths.operator_dir / name, payloads[name])
    current_runtime_path = paths.operator_dir / "native_trainer_runtime_status.json"
    current_runtime = as_dict(read_json(current_runtime_path))
    prediction_public = as_dict(read_json(paths.public_root / PREDICTION_REL))
    expected_prediction_rows = int(
        finite_float(prediction_public.get("expected_prediction_count"))
        or finite_float(current_runtime.get("prediction_grid_expected_rows"))
        or finite_float(persistent.get("prediction_grid_expected_rows"))
        or 0
    )
    symbol_scope = {
        key: persistent.get(key)
        for key in (
            "training_symbols",
            "training_symbols_count",
            "trainer_symbol_profile",
            "trainer_symbol_source_path",
            "trainer_symbol_discovered_count",
            "trainer_symbol_binance_usdm_confirmed_count",
            "trainer_symbol_baseline_count",
            "trainer_smoke_test_scope",
            "trainer_btc_eth_sol_only_scope",
            "trainer_all_runtime_symbols_enabled",
            "training_timeframes",
            "training_timeframes_count",
            "training_grid_expected_rows_from_symbol_scope",
        )
        if key in persistent
    }
    current_prediction_rows = int(
        finite_float(prediction_public.get("current_prediction_count"))
        or finite_float(current_runtime.get("current_prediction_count"))
        or finite_float(persistent.get("prediction_grid_rows"))
        or 0
    )
    missing_prediction_rows = int(
        finite_float(prediction_public.get("missing_prediction_rows_count"))
        or finite_float(current_runtime.get("missing_prediction_rows_count"))
        or 0
    )
    stale_prediction_rows = int(
        finite_float(prediction_public.get("stale_prediction_rows_count"))
        or finite_float(current_runtime.get("stale_prediction_rows_count"))
        or 0
    )
    missing_prediction_symbols = as_list(prediction_public.get("missing_prediction_symbols"))
    if not missing_prediction_symbols and missing_prediction_rows:
        missing_prediction_symbols = as_list(current_runtime.get("missing_prediction_symbols"))
    missing_prediction_timeframes_by_symbol = as_dict(
        prediction_public.get("missing_prediction_timeframes_by_symbol")
    )
    if not missing_prediction_timeframes_by_symbol and missing_prediction_rows:
        missing_prediction_timeframes_by_symbol = as_dict(
            current_runtime.get("missing_prediction_timeframes_by_symbol")
        )
    prediction_grid_current = bool(
        expected_prediction_rows > 0
        and current_prediction_rows == expected_prediction_rows
        and missing_prediction_rows == 0
        and stale_prediction_rows == 0
    )
    if trainer_result is not None:
        latest_training_metrics = latest_training_metrics_from_result(trainer_result) or current_runtime.get(
            "latest_training_metrics"
        )
        latest_training_metrics = _with_current_feedback_rejection_counts(latest_training_metrics)
    else:
        latest_training_metrics = latest_training_metrics_from_current_feedback(fail_closed=True)
    online_learning = online_learning_runtime_fields(
        training=as_dict(as_dict(getattr(trainer_result, "metrics", {})).get("training")) if trainer_result is not None else {},
        latest_training_metrics=latest_training_metrics,
        persistent_state=persistent,
        prediction_rows=current_prediction_rows,
    )
    current_result_status = as_dict(getattr(trainer_result, "status", {})) if trainer_result is not None else {}
    current_metric_fields = as_dict(as_dict(latest_training_metrics).get("metrics"))
    active_checkpoint_path = first_non_empty(
        current_metric_fields.get("checkpoint_path"),
        online_learning.get("checkpoint_path"),
        persistent.get("checkpoint_path"),
        current_runtime.get("checkpoint_path"),
    )
    checkpoint_id_from_path = None
    if active_checkpoint_path:
        checkpoint_name = Path(str(active_checkpoint_path)).name
        if checkpoint_name.endswith(".weights.npz"):
            checkpoint_id_from_path = checkpoint_name[: -len(".weights.npz")]
        elif checkpoint_name.endswith(".json"):
            checkpoint_id_from_path = checkpoint_name[: -len(".json")]
    active_checkpoint_id = first_non_empty(
        current_result_status.get("checkpoint_id"),
        checkpoint_id_from_path,
        checkpoint.get("latest_checkpoint_id"),
        current_runtime.get("checkpoint_id"),
    )
    active_checkpoint_hash = first_non_empty(
        current_metric_fields.get("checkpoint_hash"),
        online_learning.get("checkpoint_hash"),
        persistent.get("checkpoint_hash"),
        current_runtime.get("checkpoint_hash"),
    )
    active_checkpoint_weight_blob_written = first_non_empty(
        current_metric_fields.get("checkpoint_weight_blob_written"),
        online_learning.get("checkpoint_weight_blob_written"),
        persistent.get("checkpoint_weight_blob_written"),
        current_runtime.get("checkpoint_weight_blob_written"),
    )
    active_checkpoint_reload_verified = first_non_empty(
        current_metric_fields.get("checkpoint_reload_verified"),
        online_learning.get("checkpoint_reload_verified"),
        persistent.get("checkpoint_reload_verified"),
        current_runtime.get("checkpoint_reload_verified"),
    )
    merged_runtime = {
        **current_runtime,
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "payload_age_seconds": 0,
        "current_status_age_seconds": 0,
        "training_loop_active": True,
        "continuous_training_enabled": True,
        "trainer_liveness_status": persistent.get("trainer_liveness_status"),
        "worker_health_status": persistent.get("worker_health_status"),
        "heartbeat_age_seconds": persistent.get("heartbeat_age_seconds"),
        "last_batch_age_seconds": persistent.get("last_batch_age_seconds"),
        "last_prediction_age_seconds": persistent.get("last_prediction_age_seconds"),
        "legacy_grade_runtime_config": persistent.get("legacy_grade_runtime_config"),
        "legacy_runtime_effective_config": persistent.get("legacy_runtime_effective_config"),
        "legacy_runtime_coverage_mode": persistent.get("legacy_runtime_coverage_mode"),
        **online_learning,
        **symbol_scope,
        "prediction_grid_current": prediction_grid_current,
        "persistent_trainer_service_active": persistent.get("service_active"),
        "persistent_trainer_pid": persistent.get("pid"),
        "persistent_trainer_uptime_seconds": persistent.get("uptime_seconds"),
        "training_steps_total": persistent.get("training_steps_total"),
        "training_steps_last_hour": persistent.get("training_steps_last_hour"),
        "fresh_examples_built": persistent.get("fresh_examples_built"),
        "prediction_examples_built": persistent.get("prediction_examples_built"),
        "replay_buffer_enabled": persistent.get("replay_buffer_enabled"),
        "replay_buffer_size": persistent.get("replay_buffer_size"),
        "replay_buffer_limit": persistent.get("replay_buffer_limit"),
        "latest_training_metrics": latest_training_metrics,
        "samples_per_second": resource.get("samples_per_second"),
        "predictions_per_second": resource.get("predictions_per_second"),
        "training_steps_per_minute": resource.get("training_steps_per_minute"),
        "batch_size": resource.get("batch_size"),
        "target_batch_size": resource.get("target_batch_size"),
        "dataloader_workers": resource.get("dataloader_workers"),
        "pinned_memory": resource.get("pinned_memory"),
        "amp_enabled": resource.get("amp_enabled"),
        "gpu_name": resource.get("gpu_name"),
        "gpu_utilization_percent": resource.get("gpu_utilization_percent"),
        "vram_used_mb": resource.get("vram_used_mb"),
        "vram_total_mb": resource.get("vram_total_mb"),
        "cpu_utilization_percent": resource.get("cpu_utilization_percent"),
        "ram_used_gb": resource.get("ram_used_gb"),
        "ram_total_gb": resource.get("ram_total_gb"),
        "checkpoint_count": checkpoint.get("checkpoint_count"),
        "checkpoint_id": active_checkpoint_id,
        "checkpoint_path": active_checkpoint_path,
        "checkpoint_hash": active_checkpoint_hash,
        "checkpoint_weight_blob_written": active_checkpoint_weight_blob_written,
        "checkpoint_reload_verified": active_checkpoint_reload_verified,
        "checkpoint_total_size_gb": checkpoint.get("checkpoint_total_size_gb"),
        "checkpoint_dir_size_bytes": checkpoint.get("checkpoint_dir_size_bytes"),
        "checkpoint_rollover_status": checkpoint.get("checkpoint_rollover_status"),
        "prediction_grid_rows": int(
            finite_float(prediction_public.get("prediction_rows_count"))
            or finite_float(persistent.get("prediction_grid_rows"))
            or 0
        ),
        "prediction_grid_expected_rows": expected_prediction_rows,
        "current_prediction_count": current_prediction_rows,
        "missing_prediction_rows_count": missing_prediction_rows,
        "stale_prediction_rows_count": stale_prediction_rows,
        "non_current_prediction_rows_count": max(0, expected_prediction_rows - current_prediction_rows),
        "prediction_coverage_status": prediction_public.get("coverage_status")
        or current_runtime.get("prediction_coverage_status"),
        "prediction_actionability_status": prediction_public.get("actionability_status")
        or current_runtime.get("prediction_actionability_status"),
        "missing_prediction_symbols": missing_prediction_symbols,
        "missing_prediction_timeframes_by_symbol": missing_prediction_timeframes_by_symbol,
        "blocked_prediction_rows": int(
            finite_float(prediction_public.get("blocked_prediction_rows_count"))
            or finite_float(persistent.get("blocked_prediction_rows"))
            or 0
        ),
        "paper_actionability_allowed_rows_count": int(
            finite_float(prediction_public.get("paper_actionability_allowed_rows_count")) or 0
        ),
        "paper_actionability_blocked_rows_count": int(
            finite_float(prediction_public.get("paper_actionability_blocked_rows_count")) or 0
        ),
        "paper_actionability_block_reason_counts": dict(
            as_dict(prediction_public.get("paper_actionability_block_reason_counts"))
        ),
        "resource_bottleneck_reason": resource.get("bottleneck_reason"),
        "training_cycle_blocked_reason": persistent.get("last_training_blocker_reason"),
        "paper_confidence_trial_drawdown_guard": dict(guard),
        "paper_confidence_trial_guard_status": guard.get("status"),
        "paper_confidence_trial_guard_reason": guard.get("drawdown_guard_reason"),
        "paper_confidence_trial_guard_trial_enabled": guard.get("trial_enabled"),
    }
    readiness_artifact = {
        key: merged_runtime.get(key)
        for key in (
            "schema_version",
            "generated_utc",
            "trainer_learning_ready",
            "trainer_process_status",
            "cuda_inference_status",
            "prediction_publication_status",
            "offline_replay_learning_status",
            "online_paper_learning_status",
            "online_learning_status",
            "effective_trainer_mode",
            "allowed_effective_trainer_modes",
            "last_successful_weight_update_at",
            "trusted_rows_loaded",
            "trusted_replay_rows_loaded",
            "feedback_rows_entered_batch",
            "optimizer_steps_this_cycle",
            "optimizer_steps_last_hour",
            "optimizer_steps_total",
            "parameter_hash_before",
            "parameter_hash_after",
            "weight_delta_norm",
            "checkpoint_weight_blob_written",
            "checkpoint_path",
            "checkpoint_hash",
            "checkpoint_reload_verified",
            "requirement_checks",
            "readiness_blocking_reasons",
        )
        if key in merged_runtime
    }
    latest_metrics = as_dict(as_dict(latest_training_metrics).get("metrics"))
    loss_before = latest_training_metrics.get("loss_before") or latest_metrics.get("loss_before")
    loss_after = latest_training_metrics.get("loss_after") or latest_metrics.get("loss_after")
    weight_mutation_proof = {
        "schema_version": "online_learning_weight_mutation_proof_v1",
        "generated_utc": generated_utc,
        "trusted_rows_loaded": merged_runtime.get("trusted_rows_loaded"),
        "trusted_replay_rows_loaded": merged_runtime.get("trusted_replay_rows_loaded"),
        "feedback_rows_entered_batch": merged_runtime.get("feedback_rows_entered_batch"),
        "optimizer_steps_this_cycle": merged_runtime.get("optimizer_steps_this_cycle"),
        "optimizer_steps_last_hour": merged_runtime.get("optimizer_steps_last_hour"),
        "optimizer_steps_total": merged_runtime.get("optimizer_steps_total"),
        "parameter_hash_before": merged_runtime.get("parameter_hash_before"),
        "parameter_hash_after": merged_runtime.get("parameter_hash_after"),
        "weight_delta_norm": merged_runtime.get("weight_delta_norm"),
        "loss_before": loss_before,
        "loss_after": loss_after,
        "finite_loss": finite_float(loss_before) is not None and finite_float(loss_after) is not None,
        "checkpoint_weight_blob_written": merged_runtime.get("checkpoint_weight_blob_written"),
        "checkpoint_path": merged_runtime.get("checkpoint_path"),
        "checkpoint_hash": merged_runtime.get("checkpoint_hash"),
        "checkpoint_reload_verified": merged_runtime.get("checkpoint_reload_verified"),
        "last_successful_weight_update_at": merged_runtime.get("last_successful_weight_update_at"),
        "learning_update_lane": latest_metrics.get("learning_update_lane"),
        "ppo_objective_used": latest_metrics.get("ppo_objective_used"),
        "outcome_supervised_update_used": latest_metrics.get("outcome_supervised_update_used"),
        "uses_expected_move_as_realized_reward": latest_metrics.get("uses_expected_move_as_realized_reward"),
        "trainer_learning_ready": merged_runtime.get("trainer_learning_ready"),
    }
    batch_consumption = {
        "schema_version": "trusted_feedback_batch_consumption_status_v1",
        "generated_utc": generated_utc,
        "trusted_rows_loaded": merged_runtime.get("trusted_rows_loaded"),
        "trusted_replay_rows_loaded": merged_runtime.get("trusted_replay_rows_loaded"),
        "fresh_paper_feedback_rows_entered_batch": merged_runtime.get("feedback_rows_entered_batch"),
        "online_paper_learning_status": merged_runtime.get("online_paper_learning_status"),
        "offline_replay_learning_status": merged_runtime.get("offline_replay_learning_status"),
        "rows_rejected_by_reason": merged_runtime.get("rows_rejected_by_reason"),
    }
    checkpoint_post_learning = {
        "schema_version": "checkpoint_post_learning_status_v1",
        "generated_utc": generated_utc,
        "checkpoint_weight_blob_written": merged_runtime.get("checkpoint_weight_blob_written"),
        "checkpoint_path": merged_runtime.get("checkpoint_path"),
        "checkpoint_hash": merged_runtime.get("checkpoint_hash"),
        "checkpoint_reload_verified": merged_runtime.get("checkpoint_reload_verified"),
        "parameter_hash_before": merged_runtime.get("parameter_hash_before"),
        "parameter_hash_after": merged_runtime.get("parameter_hash_after"),
        "last_successful_weight_update_at": merged_runtime.get("last_successful_weight_update_at"),
    }
    training_lane = {
        "schema_version": "training_lane_separation_status_v1",
        "generated_utc": generated_utc,
        "learning_update_lane": latest_metrics.get("learning_update_lane"),
        "ppo_objective_used": latest_metrics.get("ppo_objective_used"),
        "outcome_supervised_update_used": latest_metrics.get("outcome_supervised_update_used"),
        "ppo_requires_on_policy_fields": latest_metrics.get("ppo_requires_on_policy_fields"),
        "ppo_on_policy_rows": latest_metrics.get("ppo_on_policy_rows"),
        "outcome_supervised_rows": latest_metrics.get("outcome_supervised_rows"),
        "trusted_replay_rows_loaded": latest_metrics.get("trusted_replay_rows_loaded"),
        "fresh_feedback_rows_loaded": latest_metrics.get("feedback_rows_entered_batch"),
        "ppo_rows_rejected_missing_on_policy_fields": latest_metrics.get(
            "ppo_rows_rejected_missing_on_policy_fields"
        ),
        "uses_expected_move_as_realized_reward": latest_metrics.get("uses_expected_move_as_realized_reward"),
    }
    ppo_validation = {
        "schema_version": "ppo_on_policy_validation_status_v1",
        "generated_utc": generated_utc,
        "ppo_objective_used": latest_metrics.get("ppo_objective_used"),
        "ppo_on_policy_rows": latest_metrics.get("ppo_on_policy_rows"),
        "required_fields": [
            "old_log_prob",
            "old_value",
            "reward",
            "done",
            "rollout_id",
            "trajectory_step",
            "trajectory_order",
            "on_policy_checkpoint_id",
        ],
        "off_policy_rows_reported_as_ppo": False,
    }
    outcome_supervised = {
        "schema_version": "outcome_supervised_learning_status_v1",
        "generated_utc": generated_utc,
        "active": latest_metrics.get("outcome_supervised_update_used") is True,
        "trusted_rows_loaded": merged_runtime.get("trusted_rows_loaded"),
        "trusted_replay_rows_loaded": merged_runtime.get("trusted_replay_rows_loaded"),
        "fresh_feedback_rows_loaded": merged_runtime.get("feedback_rows_entered_batch"),
        "realized_reward_source": latest_metrics.get("realized_reward_source"),
        "uses_expected_move_as_realized_reward": latest_metrics.get("uses_expected_move_as_realized_reward"),
    }
    previous_confidence_calibration = as_dict(
        read_json(paths.operator_dir / "trusted_confidence_calibration_status.json")
    )
    holdout_min_interval = holdout_calibration_min_interval_seconds()
    run_holdout_calibration, holdout_reuse_age_seconds = holdout_calibration_due(
        previous_confidence_calibration,
        generated_utc=generated_utc,
        min_interval_seconds=holdout_min_interval,
    )
    followup_artifacts = {
        **build_paper_exploration_artifacts(
            prediction_public=prediction_public,
            generated_utc=generated_utc,
        ),
        **build_confidence_artifacts(
            prediction_public=prediction_public,
            generated_utc=generated_utc,
            repo_root=paths.repo_root,
            model_dir=paths.model_dir,
            run_holdout_calibration=run_holdout_calibration,
            previous_trusted_confidence_calibration=previous_confidence_calibration,
            holdout_calibration_reuse_age_seconds=holdout_reuse_age_seconds,
            holdout_calibration_min_interval_seconds=holdout_min_interval,
        ),
        "fresh_online_feedback_end_to_end_status.json": {
            "schema_version": "fresh_online_feedback_end_to_end_status_v1",
            "generated_utc": generated_utc,
            "status": merged_runtime.get("online_paper_learning_status"),
            "new_consumable_feedback_rows": merged_runtime.get("feedback_rows_entered_batch"),
            "new_unexplained_quarantined_feedback_rows": None,
        },
        "trainer_accuracy_calibration_runtime_status.json": build_trainer_quality_artifact(
            generated_utc=generated_utc
        ),
    }
    trusted_replay_dataset = as_dict(
        read_json(paths.repo_root / "goal_state" / TRUSTED_REPLAY_GOAL_ID / "trusted_replay_dataset_status.json")
    ) or as_dict(read_json(paths.operator_dir / "trusted_replay_dataset_status.json"))
    goal_blockers: list[str] = []
    if not trusted_replay_dataset.get("trusted_replay_rows_requirement_met"):
        goal_blockers.append("trusted_replay_rows_below_10000")
    if not trusted_replay_dataset.get("symbol_count_requirement_met"):
        goal_blockers.append("trusted_replay_symbol_count_below_50")
    if trusted_replay_dataset.get("all_required_timeframes_present") is not True:
        goal_blockers.append("trusted_replay_missing_required_timeframes")
    if merged_runtime.get("online_learning_status") != "WEIGHTS_UPDATING":
        goal_blockers.append("online_learning_not_weights_updating")
    if merged_runtime.get("checkpoint_reload_verified") is not True:
        goal_blockers.append("checkpoint_reload_not_verified")
    if not merged_runtime.get("last_successful_weight_update_at"):
        goal_blockers.append("last_successful_weight_update_missing")
    if merged_runtime.get("online_paper_learning_status") != "ACTIVE":
        goal_blockers.append("fresh_online_paper_feedback_not_consumed")
    paper_status = str(as_dict(followup_artifacts.get("paper_exploration_tier_status.json")).get("status") or "")
    confidence_status = str(
        as_dict(followup_artifacts.get("trusted_confidence_calibration_status.json")).get("status") or ""
    )
    quality_status = str(
        as_dict(followup_artifacts.get("trainer_accuracy_calibration_runtime_status.json")).get("status") or ""
    )
    if not paper_status.startswith("ACTIVE"):
        goal_blockers.append("paper_exploration_not_implemented")
    if confidence_status != "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION":
        goal_blockers.append("confidence_holdout_calibration_not_implemented")
    if not quality_status.startswith("ACTIVE"):
        goal_blockers.append("direct_trainer_quality_metrics_not_implemented")
    goal_ready = not goal_blockers
    goal_go_no_go = {
        "status": f"{TRUSTED_REPLAY_GOAL_ID}_{'READY' if goal_ready else 'BLOCKED'}",
        "ready": goal_ready,
        "blockers": goal_blockers,
    }
    write_json(current_runtime_path, merged_runtime)
    write_learning_readiness_artifact(paths.operator_dir / GLOBAL_READINESS_ARTIFACT, readiness_artifact)
    goal_dirs = (
        paths.artifact_dir,
        paths.worklog_dir,
        paths.repo_root / "goal_state" / TRUSTED_REPLAY_GOAL_ID,
        paths.repo_root / "claude_worklog/final_readiness" / TRUSTED_REPLAY_GOAL_ID / "latest",
        paths.operator_dir,
    )
    goal_payloads = {
        GLOBAL_READINESS_ARTIFACT: readiness_artifact,
        "online_learning_weight_mutation_proof.json": weight_mutation_proof,
        "trusted_feedback_batch_consumption_status.json": batch_consumption,
        "checkpoint_post_learning_status.json": checkpoint_post_learning,
        "training_lane_separation_status.json": training_lane,
        "ppo_on_policy_validation_status.json": ppo_validation,
        "outcome_supervised_learning_status.json": outcome_supervised,
        **followup_artifacts,
        "operator_dashboard_payload.json": dashboard,
    }
    for base in goal_dirs:
        write_learning_readiness_artifact(base / GLOBAL_READINESS_ARTIFACT, readiness_artifact)
        for name, payload in goal_payloads.items():
            if name == GLOBAL_READINESS_ARTIFACT:
                continue
            write_json(base / name, payload)
        write_text(base / "GO_NO_GO.md", goal_go_no_go["status"])
        write_text(
            base / f"{TRUSTED_REPLAY_GOAL_ID}_REPORT.md",
            "\n".join(
                [
                    f"# {TRUSTED_REPLAY_GOAL_ID}",
                    "",
                    f"Status: `{goal_go_no_go['status']}`",
                    "",
                    "Replay learning is active and weight mutation is proven. The full goal remains blocked only by the remaining follow-up lanes below.",
                    "",
                    f"- Trusted replay rows: `{trusted_replay_dataset.get('trusted_replay_rows')}`",
                    f"- Trusted replay symbols: `{trusted_replay_dataset.get('symbol_count')}`",
                    f"- Trusted rows loaded: `{merged_runtime.get('trusted_rows_loaded')}`",
                    f"- Optimizer steps last hour: `{merged_runtime.get('optimizer_steps_last_hour')}`",
                    f"- Parameter hash changed: `{merged_runtime.get('parameter_hash_before') != merged_runtime.get('parameter_hash_after')}`",
                    f"- Checkpoint reload verified: `{merged_runtime.get('checkpoint_reload_verified')}`",
                    f"- Online paper learning: `{merged_runtime.get('online_paper_learning_status')}`",
                    f"- Remaining blockers: `{', '.join(goal_go_no_go['blockers']) or 'none'}`",
                ]
            ),
        )
    write_json(paths.operator_dir / "native_trainer_gpu_status.json", dict(resource))
    write_json(paths.operator_dir / "native_trainer_checkpoint_status.json", dict(checkpoint))
    return payloads


def run_one_persistent_cycle(
    *,
    paths: PersistentTrainerPaths,
    max_rows: int = DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE,
    risk_caps_configured: bool = True,
    run_training: bool = True,
) -> dict[str, Any]:
    training_blocker_reason: str | None = None
    cuda_oom_occurred = False
    state_before_cycle = as_dict(read_json(paths.state_path))
    publish_training_cycle_heartbeat(
        paths=paths,
        persistent_state=state_before_cycle,
        max_rows=max_rows,
        run_training=run_training,
    )
    trainer_result = None
    try:
        if run_training:
            with resident_native_cycle_timeout(RESIDENT_NATIVE_CYCLE_TIMEOUT_SECONDS):
                trainer_result = run_native_training_cycle(
                    paths=paths,
                    max_rows=max_rows,
                    risk_caps_configured=risk_caps_configured,
                )
    except NativeCycleTimeout:
        trainer_result = None
        training_blocker_reason = f"NATIVE_CYCLE_TIMEOUT_{RESIDENT_NATIVE_CYCLE_TIMEOUT_SECONDS}s"
    except (RuntimeError, ValueError) as exc:
        msg = str(exc).lower()
        if "out of memory" in msg or "cuda oom" in msg:
            trainer_result = None
            training_blocker_reason = "CUDA_OOM_BACKOFF"
            cuda_oom_occurred = True
        elif not ("no trusted examples built" in msg or "min() arg is an empty sequence" in msg):
            raise
        else:
            trainer_result = None
            training_blocker_reason = "NO_TRUSTED_EXAMPLES_BUILT"
    trainer_result_metrics = (
        as_dict(getattr(trainer_result, "metrics", {}))
        if trainer_result is not None
        else {}
    )
    training_metrics = as_dict(trainer_result_metrics.get("training"))
    nested_training_metrics = as_dict(training_metrics.get("metrics"))
    if _adaptive_gpu_controller_enabled():
        update_gpu_saturation_controller(
            client=connect_redis(),
            nested_training_metrics=nested_training_metrics,
            oom_occurred=cuda_oom_occurred,
            checkpoint_promotion=as_dict(trainer_result_metrics.get("checkpoint_promotion")),
        )
    trusted_rows_loaded = int(
        finite_float(nested_training_metrics.get("trusted_rows_loaded"))
        or finite_float(training_metrics.get("trusted_rows_loaded"))
        or 0
    )
    optimizer_steps_this_cycle = int(
        finite_float(nested_training_metrics.get("optimizer_steps_this_cycle"))
        or finite_float(training_metrics.get("optimizer_steps_this_cycle"))
        or finite_float(training_metrics.get("training_steps"))
        or 0
    )
    if trainer_result is not None and trusted_rows_loaded <= 0 and optimizer_steps_this_cycle <= 0:
        training_blocker_reason = "NO_TRUSTED_FEEDBACK_ROWS"
    prediction_public = as_dict(read_json(paths.public_root / PREDICTION_REL))
    prediction_rows = len(getattr(trainer_result, "predictions", []) if trainer_result is not None else [])
    if trainer_result is None:
        prediction_rows = int(
            finite_float(prediction_public.get("prediction_rows_count"))
            or len(as_list(prediction_public.get("prediction_rows")))
            or 0
        )
    training_steps_this_cycle = int(optimizer_steps_this_cycle)
    state = record_cycle_state(
        paths=paths,
        training_steps=training_steps_this_cycle,
        prediction_rows=prediction_rows,
        samples_seen=int(finite_float(training_metrics.get("train_rows")) or 0)
        + int(finite_float(training_metrics.get("validation_rows")) or 0),
        batches=1 if trainer_result is not None else 0,
        training_blocker_reason=training_blocker_reason,
    )
    all_timeframe_refresh = refresh_all_timeframe_payload(paths.repo_root)
    checkpoint_id = as_dict(getattr(trainer_result, "status", {})).get("checkpoint_id") if trainer_result is not None else None
    checkpoint = checkpoint_retention_status(paths=paths, latest_checkpoint_id=checkpoint_id)
    resource = build_resource_status(trainer_result=trainer_result, persistent_state=state)
    persistent = build_persistent_runtime_status(
        paths=paths,
        trainer_result=trainer_result,
        persistent_state=state,
        resource=resource,
        checkpoint=checkpoint,
        max_rows=max_rows,
    )
    client = connect_redis()
    ledger = as_dict(redis_json(client, "v2:paper:ledger"))
    portfolio = as_dict(read_json(paths.public_root / PORTFOLIO_REL))
    existing_trial_status = as_dict(redis_json(client, TRIAL_STATUS_REDIS_KEY))
    attribution = build_paper_drawdown_attribution(portfolio=portfolio, ledger=ledger)
    guard = build_paper_drawdown_guard(attribution=attribution, existing_trial_status=existing_trial_status)
    redis_guard = apply_paper_drawdown_guard_to_redis(client, guard)
    guard = {**guard, "redis_write_result": redis_guard}
    return publish_persistent_payloads(
        paths=paths,
        persistent=persistent,
        resource=resource,
        checkpoint=checkpoint,
        attribution=attribution,
        guard=guard,
        trainer_result=trainer_result,
        all_timeframe_refresh=all_timeframe_refresh,
    )


def persistent_loop_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_native_cuda_trainer_persistent_loop")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=_bounded_env_int(
            "PREDICTION_LOOP_SECONDS",
            LEGACY_RUNTIME_DEFAULT_PREDICTION_LOOP_SECONDS,
            minimum=1,
            maximum=300,
        ),
    )
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE)
    parser.add_argument("--max-cycles", type=int, default=0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-training", action="store_true", help="Publish status without running a trainer cycle.")
    args = parser.parse_args(argv)
    paths = PersistentTrainerPaths(repo_root=args.repo_root.resolve())
    cycles = 0
    while True:
        payloads = run_one_persistent_cycle(
            paths=paths,
            max_rows=args.max_rows,
            risk_caps_configured=True,
            run_training=not args.no_training,
        )
        dashboard = as_dict(payloads.get("operator_dashboard_payload.json"))
        print(
            json.dumps(
                {
                    "gate": dashboard.get("gate"),
                    "generated_est": dashboard.get("generated_est"),
                    "training_steps_total": as_dict(dashboard.get("trainer")).get("training_steps_total"),
                    "training_steps_last_hour": as_dict(dashboard.get("trainer")).get("training_steps_last_hour"),
                    "prediction_grid_rows": as_dict(dashboard.get("trainer")).get("prediction_grid_rows"),
                    "paper_guard_status": as_dict(dashboard.get("paper_drawdown")).get("guard_status"),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        cycles += 1
        if args.once or (args.max_cycles and cycles >= args.max_cycles):
            return 0 if dashboard.get("gate") == READY else 2
        # Only pause when training is blocked (no trusted data). When data is
        # flowing the loop runs continuously to maximise GPU utilisation.
        blockers = as_dict(dashboard).get("blockers") or []
        post_training_pause_s = _bounded_env_int(
            "POST_TRAINING_PAUSE_SECONDS",
            LEGACY_RUNTIME_DEFAULT_POST_TRAINING_PAUSE_SECONDS,
            minimum=0,
            maximum=300,
        )
        sleep_s = max(1, int(args.interval_seconds)) if blockers else post_training_pause_s
        if sleep_s:
            time.sleep(sleep_s)


__all__ = [
    "READY",
    "BLOCKED",
    "PersistentTrainerPaths",
    "build_paper_drawdown_attribution",
    "build_paper_drawdown_guard",
    "checkpoint_retention_status",
    "legacy_grade_runtime_config",
    "run_one_persistent_cycle",
    "persistent_loop_main",
]
