"""Persistent native CUDA trainer runtime and paper drawdown guard.

This module keeps the V2 native PPO/MASA CUDA trainer resident without using
the legacy trainer bridge or wrapper. It publishes V2-owned runtime artifacts,
checkpoint-retention status, resource telemetry, and a paper-only confidence
trial drawdown guard. It never touches live execution or exchange mutation
paths.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import heapq
import json
import math
import os
import signal
import socket
import sqlite3
import subprocess
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    default_archive_root as default_behavior_receipt_archive_root,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    default_archive_path as default_canonical_5m_label_archive_path,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    SnapshotArchiveError,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    content_sha256 as legacy_snapshot_content_sha256,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    default_archive_root as default_trusted_replay_archive_root,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    load_snapshot as load_durable_feature_snapshot,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    DurableFeatureSnapshotLedger,
    FeatureSnapshotIntegrityReport,
    FeatureSnapshotLedgerError,
    FeatureSnapshotValidationError,
    FixedCutoffFeatureSnapshot,
    feature_abi_contract,
    feature_requirement_classes_for_names,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    MAX_QUERY_ROWS as FEATURE_LEDGER_MAX_QUERY_ROWS,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    default_ledger_path as default_feature_snapshot_ledger_path,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    CheckpointManifest,
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (
    VERIFIED_SERVING_LINEAGE,
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
    _verified_serving_checkpoint_evidence,
    run_hybrid_trainer_cycle,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import V2OnlyJsonIO
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.training_sample_identity import (
    OPTIONAL_MISSING_EVIDENCE_SEMANTICS,
    SAMPLE_IDENTITY_DOMAIN as TRAINING_SAMPLE_IDENTITY_DOMAIN,
    TrainingSampleIdentityError,
    feature_ledger_fixed_observation_high_water,
    label_archive_fixed_observation_high_water,
    read_published_checkpoint_partition_manifest,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.training_state import (
    PPO_CONSUMPTION_LEDGER_SCHEMA_VERSION,
    training_partition_digest,
)
from v2.backend.app.services.native_trainer.learning_readiness import (
    GLOBAL_READINESS_ARTIFACT,
    build_learning_readiness,
    write_learning_readiness_artifact,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    HORIZON_SECONDS,
    TRUSTED_REPLAY_COST_EVIDENCE_SCHEMA_VERSION,
    TRUSTED_REPLAY_LABEL_POLICY_VERSION,
    build_trusted_replay_row,
    target_action_index,
    timeframe_seconds,
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
HOLDOUT_MANIFEST_SCHEMA_VERSION = (
    "trusted_replay_train_validation_holdout_manifest_v2"
)
HOLDOUT_OBSERVATION_POLICY = (
    "AUTHENTICATED_MANIFEST_FEATURE_AND_EVALUATION_LABEL_FIXED_PREFIX_V3"
)
HOLDOUT_SAMPLING_POLICY = (
    "COMPLETE_AUTHENTICATED_WINDOW_CONTENT_MINHASH_THEN_CAUSAL_ORDER_V2"
)
HOLDOUT_FEATURE_HIGH_WATER_SCHEMA_VERSION = (
    "durable_feature_snapshot_ledger_high_water_v1"
)
HOLDOUT_LABEL_HIGH_WATER_SCHEMA_VERSION = (
    "durable_canonical_5m_label_archive_high_water_v1"
)
HOLDOUT_PARTITION_SCHEMA_VERSION = (
    "trusted_replay_checkpoint_holdout_partition_v1"
)
HOLDOUT_SAMPLE_IDENTITY_DOMAIN = (
    "durable_feature_snapshot_record_holdout_identity_v1"
)
HOLDOUT_MANIFEST_MAX_BYTES = 1024 * 1024
HOLDOUT_FEATURE_MANIFEST_LINE_MAX_BYTES = 1024 * 1024
CANONICAL_REPO_ROOT = Path(__file__).resolve().parents[5]


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

    @property
    def trusted_replay_archive_root(self) -> Path:
        return default_trusted_replay_archive_root(self.repo_root).resolve()

    @property
    def behavior_receipt_archive_root(self) -> Path:
        return default_behavior_receipt_archive_root(self.repo_root).resolve()


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
        try:
            number = float(value)
        except (OverflowError, ValueError):
            return None
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _first_present_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
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
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
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
        realized = finite_float(
            _first_present_value(
                row.get("realized_net_pnl_bps"),
                row.get("realized_pnl_bps"),
            )
        )
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
    # The goal-state projection is the sole activation pointer.  Public and
    # worklog copies are operator projections, never fallback authority: a
    # crash while refreshing a secondary must leave the prior primary active.
    path = (
        repo_root
        / "goal_state"
        / TRUSTED_REPLAY_GOAL_ID
        / "trusted_replay_train_validation_holdout_manifest.json"
    )
    payload = as_dict(read_json(path))
    holdout = as_dict(payload.get("holdout_window"))
    if holdout.get("start_decision_time") and holdout.get("end_decision_time"):
        return {**payload, "manifest_path": str(path)}
    return {}


def _authoritative_serving_activation(
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read only the atomically replaced primary checkpoint activation."""

    status: dict[str, Any] = {
        "schema_version": "checkpoint_primary_activation_status_v1",
        "status": "BLOCKED_PRIMARY_ACTIVATION_MANIFEST_UNAVAILABLE",
        "primary_activation_manifest_verified": False,
        "checkpoint_binding_verified": False,
        "checkpoint_id": None,
        "rejection_reasons": [],
    }
    try:
        manifest = read_published_checkpoint_partition_manifest(
            repo_root=Path(repo_root),
        )
    except (OSError, TrainingSampleIdentityError, TypeError, ValueError) as exc:
        status["rejection_reasons"] = [str(exc)[:512]]
        return {}, status
    binding = manifest.get("checkpoint_binding")
    if not isinstance(binding, Mapping):
        status["rejection_reasons"] = [
            "HOLDOUT_MANIFEST_CHECKPOINT_BINDING_MISSING"
        ]
        return {}, status
    copied = dict(binding)
    status.update(
        {
            "status": "PRIMARY_ACTIVATION_MANIFEST_VERIFIED",
            "primary_activation_manifest_verified": True,
            "checkpoint_id": copied.get("checkpoint_id"),
            "manifest_payload_sha256": manifest.get("manifest_payload_sha256"),
        }
    )
    return copied, status


def _holdout_window(manifest: Mapping[str, Any]) -> tuple[datetime | None, datetime | None, int]:
    holdout = as_dict(manifest.get("holdout_window"))
    start = parse_runtime_time(holdout.get("start_decision_time"))
    end = parse_runtime_time(holdout.get("end_decision_time"))
    rows = int(finite_float(holdout.get("rows")) or 0)
    return start, end, rows


def _trusted_replay_holdout_target_action(
    trust_row: Mapping[str, Any],
) -> str | None:
    """Resolve only the exact adaptive label contract used for training."""

    if (
        trust_row.get("trusted_replay_label_policy_version")
        != TRUSTED_REPLAY_LABEL_POLICY_VERSION
        or trust_row.get("cost_evidence_schema_version")
        != TRUSTED_REPLAY_COST_EVIDENCE_SCHEMA_VERSION
        or trust_row.get("flat_round_trip_cost_fallback_used") is not False
        or trust_row.get("static_action_threshold_used") is not False
    ):
        return None
    cost_hash = str(trust_row.get("cost_evidence_hash") or "").strip().lower()
    if len(cost_hash) != 64 or any(
        character not in "0123456789abcdef" for character in cost_hash
    ):
        return None
    dead_zone = finite_float(trust_row.get("action_dead_zone_bps"))
    if dead_zone is None or dead_zone < 0.0:
        return None
    action = str(trust_row.get("target_action") or "").strip().lower()
    expected_index = target_action_index(action)
    row_index = finite_float(trust_row.get("target_action_index"))
    if (
        expected_index is None
        or row_index is None
        or not float(row_index).is_integer()
        or int(row_index) != expected_index
    ):
        return None
    return action


def _selected_action_outcome(
    selected_action: Any,
    trust_row: Mapping[str, Any],
) -> float | None:
    """Score directional confidence only; HOLD has no confidence semantics."""

    target_action = _trusted_replay_holdout_target_action(trust_row)
    action = str(selected_action or "").strip().lower()
    if target_action not in {"long", "short"} or action not in {
        "long",
        "short",
    }:
        return None
    return 1.0 if action == target_action else 0.0


def _expected_after_cost_bps(
    expected_move_bps: Any,
    trust_row: Mapping[str, Any],
) -> float | None:
    """Validate and return the model head's already-after-cost prediction.

    The expected-move head is trained directly on
    ``label_expected_move_after_cost_bps``. Subtracting a fixed or adaptive
    cost again during holdout would double-charge costs and break train/eval
    parity.
    """

    if _trusted_replay_holdout_target_action(trust_row) is None:
        return None
    return finite_float(expected_move_bps)


def _directional_accuracy_hit(
    selected_action: Any,
    trust_row: Mapping[str, Any],
) -> bool | None:
    outcome = _selected_action_outcome(selected_action, trust_row)
    return None if outcome is None else bool(outcome)


def _stable_json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _reject_nonfinite_json(value: Any) -> None:
    stack = [value]
    visited = 0
    while stack:
        current = stack.pop()
        visited += 1
        if visited > 250_000:
            raise ValueError("json_node_count_exceeded")
        if isinstance(current, float) and not math.isfinite(current):
            raise ValueError("nonfinite_json_number")
        if type(current) is dict:
            stack.extend(current.values())
        elif type(current) is list:
            stack.extend(current)


def _strict_json_object(raw: bytes) -> dict[str, Any]:
    def _constant(value: str) -> None:
        raise ValueError(f"noncanonical_json_constant:{value}")

    def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError("duplicate_json_key")
            payload[key] = value
        return payload

    payload = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_object,
        parse_constant=_constant,
    )
    if not isinstance(payload, dict):
        raise ValueError("json_root_not_object")
    _reject_nonfinite_json(payload)
    return payload


def _valid_sha256_text(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        return None
    return normalized


def _holdout_temporal_partition_reasons(
    payload: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    parsed: dict[str, tuple[datetime | None, datetime | None, int]] = {}
    for name in ("training", "validation", "holdout"):
        window = as_dict(payload.get(f"{name}_window"))
        raw_rows = window.get("rows")
        rows = (
            raw_rows
            if type(raw_rows) is int and raw_rows >= 0
            else -1
        )
        start = parse_runtime_time(window.get("start_decision_time"))
        end = parse_runtime_time(window.get("end_decision_time"))
        if rows < 0:
            reasons.append(f"{name.upper()}_WINDOW_ROWS_INVALID")
        if rows > 0 and (start is None or end is None):
            reasons.append(f"{name.upper()}_WINDOW_CLOCKS_MISSING")
        if start is not None and end is not None and start > end:
            reasons.append(f"{name.upper()}_WINDOW_REVERSED")
        parsed[name] = (start, end, rows)
    training_start, training_end, training_rows = parsed["training"]
    validation_start, validation_end, validation_rows = parsed["validation"]
    holdout_start, holdout_end, holdout_rows = parsed["holdout"]
    _ = training_start, holdout_end
    if (
        training_rows > 0
        and validation_rows > 0
        and training_end is not None
        and validation_start is not None
        and training_end >= validation_start
    ):
        reasons.append("TRAINING_VALIDATION_TEMPORAL_OVERLAP")
    if (
        validation_rows > 0
        and holdout_rows > 0
        and validation_end is not None
        and holdout_start is not None
        and validation_end >= holdout_start
    ):
        reasons.append("VALIDATION_HOLDOUT_TEMPORAL_OVERLAP")
    if (
        validation_rows == 0
        and training_rows > 0
        and holdout_rows > 0
        and training_end is not None
        and holdout_start is not None
        and training_end >= holdout_start
    ):
        reasons.append("TRAINING_HOLDOUT_TEMPORAL_OVERLAP")
    return reasons


def _holdout_manifest_identity(
    *,
    repo_root: Path,
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    raw_path = manifest.get("manifest_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, ["HOLDOUT_MANIFEST_PATH_MISSING"]
    path = Path(raw_path)
    try:
        resolved_path = path.resolve(strict=True)
        resolved_path.relative_to(repo_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        return None, ["HOLDOUT_MANIFEST_PATH_OUTSIDE_REPO_OR_MISSING"]
    try:
        size_bytes = resolved_path.stat().st_size
        if size_bytes <= 0 or size_bytes > HOLDOUT_MANIFEST_MAX_BYTES:
            return None, ["HOLDOUT_MANIFEST_BYTES_OUT_OF_BOUNDS"]
        raw = resolved_path.read_bytes()
        if len(raw) != size_bytes or len(raw) > HOLDOUT_MANIFEST_MAX_BYTES:
            raise ValueError("holdout_manifest_changed_while_reading")
        file_payload = _strict_json_object(raw)
    except (
        OSError,
        OverflowError,
        RecursionError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
    ):
        return None, ["HOLDOUT_MANIFEST_UNREADABLE_OR_INVALID"]
    supplied_payload = {
        str(key): value
        for key, value in manifest.items()
        if str(key) != "manifest_path"
    }
    if file_payload != supplied_payload:
        reasons.append("HOLDOUT_MANIFEST_FILE_PAYLOAD_MISMATCH")
    if file_payload.get("schema_version") != HOLDOUT_MANIFEST_SCHEMA_VERSION:
        reasons.append("HOLDOUT_MANIFEST_SCHEMA_INVALID")
    unsigned_payload = {
        str(key): value
        for key, value in file_payload.items()
        if str(key) != "manifest_payload_sha256"
    }
    try:
        observed_unsigned_digest = _stable_json_sha256(unsigned_payload)
    except (OverflowError, RecursionError, TypeError, ValueError):
        observed_unsigned_digest = None
    if (
        _valid_sha256_text(file_payload.get("manifest_payload_sha256")) is None
        or file_payload.get("manifest_payload_sha256")
        != observed_unsigned_digest
    ):
        reasons.append("HOLDOUT_MANIFEST_PAYLOAD_DIGEST_MISMATCH")
    if file_payload.get("split_method") != (
        "STRICT_TEMPORAL_ORDER_NO_RANDOM_ROW_SPLIT"
    ):
        reasons.append("HOLDOUT_MANIFEST_SPLIT_METHOD_INVALID")
    if file_payload.get("temporal_overlap") is not False:
        reasons.append("HOLDOUT_MANIFEST_TEMPORAL_OVERLAP_NOT_FALSE")
    reasons.extend(_holdout_temporal_partition_reasons(file_payload))
    if not isinstance(file_payload.get("feature_ledger_high_water"), Mapping):
        reasons.append("FEATURE_LEDGER_HIGH_WATER_MISSING")
    if not isinstance(file_payload.get("label_archive_high_water"), Mapping):
        reasons.append("LABEL_ARCHIVE_HIGH_WATER_MISSING")
    if not isinstance(file_payload.get("partition_evidence"), Mapping):
        reasons.append("HOLDOUT_PARTITION_EVIDENCE_MISSING")
    checkpoint_binding = file_payload.get("checkpoint_binding")
    if not isinstance(checkpoint_binding, Mapping):
        reasons.append("HOLDOUT_MANIFEST_CHECKPOINT_BINDING_MISSING")
    else:
        checkpoint_id = checkpoint_binding.get("checkpoint_id")
        if (
            type(checkpoint_id) is not str
            or not checkpoint_id
            or Path(checkpoint_id).name != checkpoint_id
        ):
            reasons.append("HOLDOUT_MANIFEST_CHECKPOINT_ID_INVALID")
        for field_name in (
            "checkpoint_evidence_digest",
            "training_partition_digest",
            "training_sample_identity_set_sha256",
            "validation_sample_identity_set_sha256",
            "training_feature_identity_set_sha256",
            "validation_feature_identity_set_sha256",
        ):
            if _valid_sha256_text(checkpoint_binding.get(field_name)) is None:
                reasons.append(
                    "HOLDOUT_MANIFEST_CHECKPOINT_BINDING_"
                    f"{field_name.upper()}_INVALID"
                )
    if reasons:
        return None, sorted(set(reasons))
    try:
        payload_sha256 = _stable_json_sha256(file_payload)
    except (OverflowError, RecursionError, TypeError, ValueError):
        return None, ["HOLDOUT_MANIFEST_UNREADABLE_OR_INVALID"]
    return {
        "path": str(resolved_path),
        "size_bytes": size_bytes,
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "payload_sha256": payload_sha256,
        "payload": file_payload,
    }, []


def _identity_set_sha256(
    identities: Iterable[str],
    *,
    domain: str,
) -> str:
    ordered = sorted(set(str(value) for value in identities))
    if any(_valid_sha256_text(value) != value for value in ordered):
        raise ValueError("sample_identity_sha256_invalid")
    return _stable_json_sha256(
        {
            "schema_version": domain,
            "ordered_sample_identity_sha256s": ordered,
        }
    )


def _sample_identity_set_sha256(identities: Iterable[str]) -> str:
    return _identity_set_sha256(
        identities,
        domain=HOLDOUT_SAMPLE_IDENTITY_DOMAIN,
    )


def _training_sample_identity_set_sha256(
    identities: Iterable[str],
) -> str:
    return _identity_set_sha256(
        identities,
        domain=TRAINING_SAMPLE_IDENTITY_DOMAIN,
    )


def _feature_ledger_integrity_checkpoint(
    *,
    ledger: DurableFeatureSnapshotLedger,
    report: FeatureSnapshotIntegrityReport,
    observation_cutoff: datetime,
    scan_limit: int,
) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        return (
            feature_ledger_fixed_observation_high_water(
                ledger=ledger,
                report=report,
                observation_cutoff=observation_cutoff,
                scan_limit=scan_limit,
            ),
            [],
        )
    except TrainingSampleIdentityError as exc:
        return None, [str(exc)]


def _label_archive_integrity_checkpoint(
    *,
    archive: DurableCanonical5mLabelArchive,
    integrity: Mapping[str, Any],
    observation_cutoff: datetime,
    scan_limit: int,
) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        return (
            label_archive_fixed_observation_high_water(
                archive=archive,
                integrity=integrity,
                observation_cutoff=observation_cutoff,
                scan_limit=scan_limit,
            ),
            [],
        )
    except TrainingSampleIdentityError as exc:
        return None, [str(exc)]


def _holdout_feature_sample_identity(
    item: FixedCutoffFeatureSnapshot,
) -> tuple[dict[str, Any], str]:
    record = item.record
    envelope = as_dict(record.get("frozen_envelope"))
    identity = {
        "schema_version": HOLDOUT_SAMPLE_IDENTITY_DOMAIN,
        "durable_snapshot_id": record.get("durable_snapshot_id"),
        "record_sha256": record.get("record_sha256"),
        "original_tensor_id": envelope.get("original_tensor_id"),
        "symbol": envelope.get("symbol"),
        "timeframe": envelope.get("timeframe"),
        "ppo_decision_time": envelope.get("ppo_decision_time"),
    }
    return identity, _stable_json_sha256(identity)


def _holdout_partition_reasons(
    *,
    manifest_payload: Mapping[str, Any],
    candidate_identity_sha256s: list[str],
    manifest_rows: int,
) -> list[str]:
    partition = as_dict(manifest_payload.get("partition_evidence"))
    reasons: list[str] = []
    if partition.get("schema_version") != HOLDOUT_PARTITION_SCHEMA_VERSION:
        reasons.append("HOLDOUT_PARTITION_SCHEMA_INVALID")
    if partition.get("identity_domain") != HOLDOUT_SAMPLE_IDENTITY_DOMAIN:
        reasons.append("HOLDOUT_PARTITION_IDENTITY_DOMAIN_INVALID")
    if partition.get("training_holdout_disjoint") is not True:
        reasons.append("HOLDOUT_PARTITION_DISJOINTNESS_NOT_ATTESTED")
    if partition.get("validation_holdout_disjoint") is not True:
        reasons.append("HOLDOUT_PARTITION_VALIDATION_DISJOINTNESS_NOT_ATTESTED")
    if partition.get("training_validation_disjoint") is not True:
        reasons.append("HOLDOUT_PARTITION_TRAINING_VALIDATION_DISJOINTNESS_NOT_ATTESTED")
    if type(partition.get("holdout_sample_count")) is not int:
        reasons.append("HOLDOUT_PARTITION_SAMPLE_COUNT_INVALID")
    elif int(partition["holdout_sample_count"]) != len(
        candidate_identity_sha256s
    ):
        reasons.append("HOLDOUT_PARTITION_SAMPLE_COUNT_MISMATCH")
    if manifest_rows != len(candidate_identity_sha256s):
        reasons.append("HOLDOUT_MANIFEST_ROWS_DO_NOT_MATCH_AUTHENTICATED_WINDOW")
    if len(candidate_identity_sha256s) != len(set(candidate_identity_sha256s)):
        reasons.append("HOLDOUT_PARTITION_SAMPLE_IDENTITIES_NOT_UNIQUE")
    try:
        observed_set_sha256 = _sample_identity_set_sha256(
            candidate_identity_sha256s
        )
    except ValueError:
        observed_set_sha256 = None
        reasons.append("HOLDOUT_PARTITION_SAMPLE_IDENTITY_INVALID")
    if partition.get("holdout_sample_identity_set_sha256") != (
        observed_set_sha256
    ):
        reasons.append("HOLDOUT_PARTITION_SAMPLE_IDENTITY_SET_MISMATCH")
    for field in (
        "training_partition_digest",
        "training_sample_identity_set_sha256",
        "validation_sample_identity_set_sha256",
        "training_feature_identity_set_sha256",
        "validation_feature_identity_set_sha256",
        "holdout_sample_identity_set_sha256",
    ):
        if _valid_sha256_text(partition.get(field)) is None:
            reasons.append(f"HOLDOUT_PARTITION_{field.upper()}_INVALID")
    if (
        type(partition.get("training_sample_count")) is not int
        or partition["training_sample_count"] < 0
    ):
        reasons.append("HOLDOUT_PARTITION_TRAINING_SAMPLE_COUNT_INVALID")
    for field_name in (
        "validation_sample_count",
        "training_feature_identity_count",
        "validation_feature_identity_count",
    ):
        value = partition.get(field_name)
        if type(value) is not int or value < 0:
            reasons.append(
                f"HOLDOUT_PARTITION_{field_name.upper()}_INVALID"
            )
    if partition.get("training_sample_identity_domain") != (
        TRAINING_SAMPLE_IDENTITY_DOMAIN
    ):
        reasons.append("HOLDOUT_PARTITION_TRAINING_SAMPLE_IDENTITY_DOMAIN_INVALID")
    if partition.get("validation_sample_identity_domain") != (
        TRAINING_SAMPLE_IDENTITY_DOMAIN
    ):
        reasons.append("HOLDOUT_PARTITION_VALIDATION_SAMPLE_IDENTITY_DOMAIN_INVALID")
    if partition.get("optional_missing_evidence_semantics") != (
        OPTIONAL_MISSING_EVIDENCE_SEMANTICS
    ):
        reasons.append("HOLDOUT_PARTITION_OPTIONAL_MISSING_SEMANTICS_INVALID")
    if partition.get("optional_missing_typed_negative_receipts_verified") is not False:
        reasons.append("HOLDOUT_PARTITION_OPTIONAL_TYPED_NEGATIVE_CLAIM_INVALID")
    if partition.get("optional_missing_observed_zero_claimed") is not False:
        reasons.append("HOLDOUT_PARTITION_OPTIONAL_ZERO_CLAIM_INVALID")
    return sorted(set(reasons))


def _exact_timeframe_finality_contract(
    envelope: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    lineage = as_dict(envelope.get("source_lineage_material"))
    finality_by_timeframe = lineage.get("timeframe_finality")
    reasons: list[str] = []
    if not isinstance(finality_by_timeframe, Mapping):
        return None, ["TIMEFRAME_FINALITY_LINEAGE_MISSING"]
    if set(finality_by_timeframe) != set(DEFAULT_TIMEFRAMES):
        reasons.append("TIMEFRAME_FINALITY_LINEAGE_SET_MISMATCH")
    mtf_snapshot_id = str(lineage.get("mtf_snapshot_id") or "")
    if not mtf_snapshot_id:
        reasons.append("MTF_SNAPSHOT_ID_MISSING")
    receipts = {
        str(receipt.get("receipt_sha256")): receipt
        for receipt in as_list(envelope.get("source_read_receipts"))
        if isinstance(receipt, Mapping)
        and _valid_sha256_text(receipt.get("receipt_sha256")) is not None
    }
    decision_time = parse_runtime_time(envelope.get("tensor_decision_time"))
    global_cutoff = parse_runtime_time(envelope.get("feature_cutoff"))
    used_receipts: list[str] = []
    exact_entries: dict[str, Any] = {}
    for timeframe in DEFAULT_TIMEFRAMES:
        raw_entry = finality_by_timeframe.get(timeframe)
        if not isinstance(raw_entry, Mapping):
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_MISSING")
            continue
        entry = dict(raw_entry)
        if entry.get("timeframe") != timeframe:
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_IDENTITY_MISMATCH")
        if entry.get("candle_closed_confirmed") is not True:
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_NOT_CLOSED")
        receipt_sha256 = _valid_sha256_text(
            entry.get("source_read_receipt_sha256")
        )
        receipt = receipts.get(str(receipt_sha256)) if receipt_sha256 else None
        if receipt is None:
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_RECEIPT_MISSING")
            continue
        used_receipts.append(str(receipt_sha256))
        finality = as_dict(receipt.get("finality_evidence"))
        comparisons = {
            "source_label": receipt.get("source_label"),
            "event_time": receipt.get("event_time"),
            "available_at": receipt.get("available_at"),
            "consumer_observed_at": receipt.get("consumer_observed_at"),
            "feature_cutoff": receipt.get("feature_cutoff"),
            "finality_cutoff": finality.get("finality_cutoff"),
            "finality_verified_at": finality.get("finality_verified_at"),
        }
        if any(entry.get(field) != expected for field, expected in comparisons.items()):
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_RECEIPT_MISMATCH")
        if finality.get("finality_type") != "CLOSED_INTERVAL":
            reasons.append(
                f"TIMEFRAME_FINALITY_{timeframe.upper()}_TYPE_INVALID"
            )
        if finality.get("event_final") is not True:
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_EVENT_NOT_FINAL")
        open_time = parse_runtime_time(entry.get("candle_open_time"))
        close_time = parse_runtime_time(entry.get("candle_close_time"))
        event_time = parse_runtime_time(entry.get("event_time"))
        available_at = parse_runtime_time(entry.get("available_at"))
        observed_at = parse_runtime_time(entry.get("consumer_observed_at"))
        receipt_cutoff = parse_runtime_time(entry.get("feature_cutoff"))
        finality_cutoff = parse_runtime_time(entry.get("finality_cutoff"))
        finality_verified_at = parse_runtime_time(entry.get("finality_verified_at"))
        if any(
            value is None
            for value in (
                open_time,
                close_time,
                event_time,
                available_at,
                observed_at,
                receipt_cutoff,
                finality_cutoff,
                finality_verified_at,
                decision_time,
                global_cutoff,
            )
        ):
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_CLOCK_INVALID")
            continue
        assert open_time is not None
        assert close_time is not None
        assert event_time is not None
        assert available_at is not None
        assert observed_at is not None
        assert receipt_cutoff is not None
        assert finality_cutoff is not None
        assert finality_verified_at is not None
        assert decision_time is not None
        assert global_cutoff is not None
        expected_interval = timedelta(
            seconds=timeframe_seconds(timeframe),
            milliseconds=-1,
        )
        if close_time - open_time != expected_interval:
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_INTERVAL_INVALID")
        if event_time != close_time:
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_EVENT_CLOSE_MISMATCH")
        if not (
            close_time
            <= finality_cutoff
            <= finality_verified_at
            <= observed_at
            <= decision_time
        ):
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_ORDER_INVALID")
        if available_at > observed_at or receipt_cutoff > global_cutoff:
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_CUTOFF_INVALID")
        if not str(entry.get("candle_id") or ""):
            reasons.append(f"TIMEFRAME_FINALITY_{timeframe.upper()}_CANDLE_ID_MISSING")
        exact_entries[timeframe] = entry
    if len(used_receipts) != len(set(used_receipts)):
        reasons.append("TIMEFRAME_FINALITY_RECEIPTS_NOT_DISTINCT")
    if reasons:
        return None, sorted(set(reasons))
    proof = {
        "schema_version": "exact_per_timeframe_finality_lineage_v1",
        "mtf_snapshot_id": mtf_snapshot_id,
        "required_timeframes": list(DEFAULT_TIMEFRAMES),
        "timeframe_finality": exact_entries,
    }
    return {**proof, "timeframe_finality_sha256": _stable_json_sha256(proof)}, []


def _exact_feature_requirement_contract(
    *,
    ordered_feature_names: Any,
    missing_mask: Any,
    stale_mask: Any,
    source_availability_mask: Any,
    feature_abi: Any,
    feature_source_receipt_sha256s: Any,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Verify the code-owned ABI and structural receipt bindings.

    This does not authenticate an external source's semantics. Production
    callers reach it only after the fixed-cutoff durable-ledger query has
    validated the complete receipt graph and its append/postcommit chain.
    """

    reasons: list[str] = []
    if (
        type(ordered_feature_names) is not list
        or not ordered_feature_names
        or any(
            type(feature_name) is not str or not feature_name
            for feature_name in ordered_feature_names
        )
        or len(set(ordered_feature_names)) != len(ordered_feature_names)
    ):
        return None, ["ORDERED_FEATURE_NAMES_INVALID"]
    names = list(ordered_feature_names)

    def binary_vector(value: Any, *, reason: str) -> list[int] | None:
        if type(value) is not list or len(value) != len(names):
            reasons.append(f"{reason}_DIMENSION_MISMATCH")
            return None
        if any(type(flag) is not int or flag not in (0, 1) for flag in value):
            reasons.append(f"{reason}_NOT_BINARY")
            return None
        return list(value)

    missing = binary_vector(missing_mask, reason="MISSING_MASK")
    stale = binary_vector(stale_mask, reason="STALE_MASK")
    availability = binary_vector(
        source_availability_mask,
        reason="SOURCE_AVAILABILITY_MASK",
    )
    if type(feature_source_receipt_sha256s) is not list or len(
        feature_source_receipt_sha256s
    ) != len(names):
        reasons.append("FEATURE_SOURCE_RECEIPT_SHA256S_DIMENSION_MISMATCH")
        bindings: list[str | None] = []
    else:
        bindings = list(feature_source_receipt_sha256s)
        if any(
            binding is not None
            and (
                type(binding) is not str
                or _valid_sha256_text(binding) != binding
            )
            for binding in bindings
        ):
            reasons.append("FEATURE_SOURCE_RECEIPT_SHA256_INVALID")
    if type(feature_abi) is not dict:
        reasons.append("FEATURE_ABI_CONTRACT_INVALID")
        abi: dict[str, Any] = {}
    else:
        abi = dict(feature_abi)
    policy_id = abi.get("feature_requirement_policy_id")
    if policy_id != FEATURE_REQUIREMENT_POLICY_ID:
        reasons.append("FEATURE_REQUIREMENT_POLICY_ID_MISMATCH")
    requirements = abi.get("ordered_feature_requirement_classes")
    if type(requirements) is not list or len(requirements) != len(names):
        reasons.append("FEATURE_REQUIREMENT_CLASSES_DIMENSION_MISMATCH")
        requirement_classes: list[str] = []
    else:
        requirement_classes = list(requirements)
    try:
        expected_requirements = list(feature_requirement_classes_for_names(names))
    except FeatureSnapshotValidationError as exc:
        reasons.extend(exc.reasons)
        return None, sorted(set(reasons))
    try:
        expected_abi = feature_abi_contract(
            names,
            feature_requirement_policy_id=(
                policy_id if type(policy_id) is str else ""
            ),
            ordered_feature_requirement_classes=requirement_classes,
        )
    except FeatureSnapshotValidationError as exc:
        reasons.extend(exc.reasons)
        expected_abi = None
    if requirement_classes != expected_requirements:
        reasons.append("FEATURE_REQUIREMENT_CLASSES_POLICY_MISMATCH")
    if expected_abi is None or abi != expected_abi:
        reasons.append("FEATURE_ABI_CONTRACT_MISMATCH")
    if (
        missing is not None
        and availability is not None
        and any(
            available != 1 - missing_flag
            for available, missing_flag in zip(
                availability,
                missing,
                strict=True,
            )
        )
    ):
        reasons.append("SOURCE_AVAILABILITY_MISSING_MASK_MISMATCH")
    if reasons:
        return None, sorted(set(reasons))
    assert missing is not None
    assert stale is not None
    assert availability is not None
    required_missing_names = [
        name
        for name, flag, requirement in zip(
            names, missing, expected_requirements, strict=True
        )
        if flag == 1 and requirement == "REQUIRED"
    ]
    optional_missing_names = [
        name
        for name, flag, requirement in zip(
            names, missing, expected_requirements, strict=True
        )
        if flag == 1 and requirement == "OPTIONAL_EVENT_DEPENDENT"
    ]
    stale_names = [
        name for name, flag in zip(names, stale, strict=True) if flag == 1
    ]
    if any(
        flag == 1
        and requirement == "OPTIONAL_EVENT_DEPENDENT"
        and binding is None
        for flag, requirement, binding in zip(
            missing, expected_requirements, bindings, strict=True
        )
    ):
        return None, ["OPTIONAL_FEATURE_SOURCE_EVIDENCE_MISSING"]
    return {
        "ordered_feature_names": names,
        "missing_mask": missing,
        "stale_mask": stale,
        "source_availability_mask": availability,
        "feature_abi": abi,
        "feature_requirement_policy_id": FEATURE_REQUIREMENT_POLICY_ID,
        "ordered_feature_requirement_classes": expected_requirements,
        "feature_source_receipt_sha256s": bindings,
        "required_missing_names": required_missing_names,
        "optional_missing_names": optional_missing_names,
        "stale_names": stale_names,
    }, []


def _snapshot_feature_requirement_contract(
    snapshot: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    names = snapshot.get("ordered_feature_names")
    if (
        type(names) is not list
        or not names
        or any(type(name) is not str or not name for name in names)
        or len(set(names)) != len(names)
    ):
        return None, ["ORDERED_FEATURE_NAMES_INVALID"]

    def ordered_binary_map(value: Any) -> list[int] | None:
        if type(value) is not dict or set(value) != set(names):
            return None
        ordered: list[int] = []
        for name in names:
            flag = value.get(name)
            if type(flag) is not bool:
                return None
            ordered.append(int(flag))
        return ordered

    missing = ordered_binary_map(snapshot.get("missing_mask"))
    stale = ordered_binary_map(snapshot.get("stale_mask"))
    availability = ordered_binary_map(snapshot.get("source_availability"))
    map_reasons: list[str] = []
    if missing is None:
        map_reasons.append("FEATURE_MISSING_MASK_INVALID")
    if stale is None:
        map_reasons.append("FEATURE_STALE_MASK_INVALID")
    if availability is None:
        map_reasons.append("FEATURE_SOURCE_AVAILABILITY_MASK_INVALID")
    if map_reasons:
        return None, map_reasons
    return _exact_feature_requirement_contract(
        ordered_feature_names=names,
        missing_mask=missing,
        stale_mask=stale,
        source_availability_mask=availability,
        feature_abi=snapshot.get("feature_abi"),
        feature_source_receipt_sha256s=snapshot.get(
            "feature_source_receipt_sha256s"
        ),
    )


def _snapshot_from_feature_ledger_item(
    item: FixedCutoffFeatureSnapshot,
) -> tuple[dict[str, Any] | None, FeatureTensorRecord | None, list[str]]:
    record = item.record
    envelope = as_dict(record.get("frozen_envelope"))
    finality_proof, finality_reasons = _exact_timeframe_finality_contract(
        envelope
    )
    if finality_proof is None:
        return None, None, finality_reasons
    requirement_contract, requirement_reasons = (
        _exact_feature_requirement_contract(
            ordered_feature_names=envelope.get("ordered_feature_names"),
            missing_mask=envelope.get("missing_mask"),
            stale_mask=envelope.get("stale_mask"),
            source_availability_mask=envelope.get(
                "source_availability_mask"
            ),
            feature_abi=envelope.get("feature_abi"),
            feature_source_receipt_sha256s=envelope.get(
                "feature_source_receipt_sha256s"
            ),
        )
    )
    if requirement_contract is None:
        return None, None, requirement_reasons
    if (
        envelope.get("strict_training_eligible") is not True
        or envelope.get("strict_training_ineligibility_reasons") != []
    ):
        return None, None, ["FEATURE_LEDGER_STRICT_TRAINING_ELIGIBILITY_INVALID"]
    names = requirement_contract["ordered_feature_names"]
    missing = requirement_contract["missing_mask"]
    stale = requirement_contract["stale_mask"]
    availability = requirement_contract["source_availability_mask"]
    values_raw = envelope.get("feature_values")
    source_labels_raw = envelope.get("ordered_feature_source_labels")
    if (
        type(values_raw) is not list
        or type(source_labels_raw) is not list
        or len(values_raw) != len(names)
        or len(source_labels_raw) != len(names)
        or any(
            type(source_label) is not str
            for source_label in source_labels_raw
        )
    ):
        return None, None, ["FEATURE_LEDGER_TENSOR_DIMENSION_MISMATCH"]
    parsed_values = [finite_float(value) for value in values_raw]
    if any(value is None for value in parsed_values):
        return None, None, ["FEATURE_LEDGER_VALUE_NONFINITE"]
    values = [float(value) for value in parsed_values if value is not None]
    source_labels = list(source_labels_raw)
    if requirement_contract["required_missing_names"]:
        return None, None, ["FEATURE_LEDGER_REQUIRED_INPUT_MISSING"]
    if requirement_contract["stale_names"]:
        return None, None, ["FEATURE_LEDGER_INPUT_STALE"]
    optional_missing_names = list(
        requirement_contract["optional_missing_names"]
    )
    features = dict(zip(names, values, strict=True))
    snapshot: dict[str, Any] = {
        "snapshot_id": record.get("durable_snapshot_id"),
        "feature_snapshot_id": envelope.get("feature_snapshot_id"),
        "symbol": envelope.get("symbol"),
        "timeframe": envelope.get("timeframe"),
        "features": features,
        "missing_mask": {
            str(name): bool(flag) for name, flag in zip(names, missing, strict=True)
        },
        "stale_mask": {
            str(name): bool(flag) for name, flag in zip(names, stale, strict=True)
        },
        "source_availability": {
            str(name): bool(flag)
            for name, flag in zip(names, availability, strict=True)
        },
        "ordered_feature_names": list(names),
        "feature_abi": dict(requirement_contract["feature_abi"]),
        "feature_requirement_policy_id": requirement_contract[
            "feature_requirement_policy_id"
        ],
        "ordered_feature_requirement_classes": list(
            requirement_contract["ordered_feature_requirement_classes"]
        ),
        "feature_requirement_by_name": dict(
            zip(
                names,
                requirement_contract[
                    "ordered_feature_requirement_classes"
                ],
                strict=True,
            )
        ),
        "feature_source_receipt_sha256s": list(
            requirement_contract["feature_source_receipt_sha256s"]
        ),
        "required_missing_feature_names": [],
        "optional_missing_feature_names": optional_missing_names,
        "feature_cutoff": envelope.get("feature_cutoff"),
        "masa_feature_cutoff": envelope.get("masa_feature_cutoff"),
        "ppo_feature_cutoff": envelope.get("ppo_feature_cutoff"),
        "tensor_decision_time": envelope.get("tensor_decision_time"),
        "ppo_decision_time": envelope.get("ppo_decision_time"),
        "decision_time": envelope.get("ppo_decision_time"),
        "generated_at": envelope.get("generated_at"),
        "available_at": envelope.get("generated_at"),
        "mtf_snapshot_id": finality_proof["mtf_snapshot_id"],
        "candle_closed_confirmed": True,
        "source_hashes": {
            "durable_record_sha256": record.get("record_sha256"),
            "frozen_envelope_sha256": record.get("frozen_envelope_sha256"),
            "source_lineage_sha256": envelope.get("source_lineage_sha256"),
            "timeframe_finality_sha256": finality_proof[
                "timeframe_finality_sha256"
            ],
            "append_receipt_sha256": item.append_receipt_sha256,
            "postcommit_receipt_sha256": item.postcommit_receipt_sha256,
        },
        "durable_feature_snapshot_ledger": True,
        "append_transaction_id": item.append_transaction_id,
        "append_receipt_sha256": item.append_receipt_sha256,
        "postcommit_receipt_sha256": item.postcommit_receipt_sha256,
        "postcommit_readback_at": item.postcommit_readback_at,
        "timeframe_finality_lineage": finality_proof,
    }
    snapshot["content_sha256"] = legacy_snapshot_content_sha256(snapshot)
    tensor = FeatureTensorRecord(
        tensor_id=str(envelope.get("original_tensor_id") or ""),
        symbol=str(envelope.get("symbol") or "").upper(),
        timeframe=str(envelope.get("timeframe") or ""),
        feature_snapshot_id=str(envelope.get("feature_snapshot_id") or ""),
        values=tuple(float(value) for value in values),
        missing_mask=tuple(int(value) for value in missing),
        stale_mask=tuple(int(value) for value in stale),
        source_availability=tuple(int(value) for value in availability),
        feature_names=tuple(str(value) for value in names),
        source_labels=tuple(str(value) for value in source_labels),
        missing_feature_names=tuple(optional_missing_names),
        stale_feature_names=(),
        data_coverage_percent=(
            100.0 * (len(names) - sum(missing)) / len(names)
        ),
        source_availability_vector=tuple(int(value) for value in availability),
        decision_time=str(envelope.get("tensor_decision_time") or ""),
        source_lineage_hash=str(envelope.get("source_lineage_sha256") or ""),
        temporal_rejection_reasons=tuple(
            str(value)
            for value in (envelope.get("temporal_rejection_reasons") or ())
        ),
    )
    return snapshot, tensor, []


def _holdout_snapshot_clock_contract(
    snapshot: Mapping[str, Any],
) -> tuple[dict[str, datetime] | None, list[str]]:
    reasons: list[str] = []
    feature_cutoff = parse_runtime_time(snapshot.get("feature_cutoff"))
    masa_cutoff = parse_runtime_time(snapshot.get("masa_feature_cutoff"))
    ppo_cutoff = parse_runtime_time(snapshot.get("ppo_feature_cutoff"))
    tensor_decision_time = parse_runtime_time(
        snapshot.get("tensor_decision_time")
    )
    ppo_decision_time = parse_runtime_time(snapshot.get("ppo_decision_time"))
    decision_time = parse_runtime_time(snapshot.get("decision_time"))
    generated_at = parse_runtime_time(snapshot.get("generated_at"))
    available_at = parse_runtime_time(snapshot.get("available_at"))
    for name, clock in (
        ("FEATURE_CUTOFF", feature_cutoff),
        ("MASA_FEATURE_CUTOFF", masa_cutoff),
        ("PPO_FEATURE_CUTOFF", ppo_cutoff),
        ("TENSOR_DECISION_TIME", tensor_decision_time),
        ("PPO_DECISION_TIME", ppo_decision_time),
        ("DECISION_TIME", decision_time),
        ("GENERATED_AT", generated_at),
        ("AVAILABLE_AT", available_at),
    ):
        if clock is None:
            reasons.append(f"{name}_MISSING_OR_INVALID")
    if (
        decision_time is not None
        and ppo_decision_time is not None
        and decision_time != ppo_decision_time
    ):
        reasons.append("DECISION_TIME_NOT_EXACT_PPO_DECISION_TIME")
    ordered_clocks = (
        feature_cutoff,
        masa_cutoff,
        ppo_cutoff,
        generated_at,
        tensor_decision_time,
        ppo_decision_time,
    )
    if all(value is not None for value in ordered_clocks):
        concrete = [value for value in ordered_clocks if value is not None]
        if concrete != sorted(concrete):
            reasons.append("FEATURE_MASA_PPO_GENERATED_DECISION_CLOCK_ORDER_INVALID")
    if (
        available_at is not None
        and tensor_decision_time is not None
        and available_at > tensor_decision_time
    ):
        reasons.append("AVAILABLE_AT_AFTER_TENSOR_DECISION_TIME")
    if (
        masa_cutoff is not None
        and ppo_decision_time is not None
        and masa_cutoff > ppo_decision_time
    ):
        reasons.append("MASA_FEATURE_CUTOFF_AFTER_PPO_DECISION_TIME")
    if snapshot.get("candle_closed_confirmed") is not True:
        reasons.append("OPEN_OR_UNCONFIRMED_FEATURE_CANDLE")
    if not isinstance(snapshot.get("source_hashes"), Mapping) or not snapshot.get(
        "source_hashes"
    ):
        reasons.append("FEATURE_SOURCE_HASHES_MISSING")
    requirement_contract, requirement_reasons = (
        _snapshot_feature_requirement_contract(snapshot)
    )
    if requirement_contract is None:
        reasons.extend(requirement_reasons)
    elif requirement_contract["required_missing_names"]:
        reasons.append("FEATURE_MISSING_AT_DECISION")
    if (
        requirement_contract is not None
        and requirement_contract["stale_names"]
    ):
        reasons.append("FEATURE_STALE_AT_DECISION")
    if reasons:
        return None, sorted(set(reasons))
    assert feature_cutoff is not None
    assert decision_time is not None
    assert tensor_decision_time is not None
    assert ppo_decision_time is not None
    assert available_at is not None
    assert masa_cutoff is not None
    assert ppo_cutoff is not None
    assert generated_at is not None
    return {
        "feature_cutoff": feature_cutoff,
        "decision_time": decision_time,
        "tensor_decision_time": tensor_decision_time,
        "ppo_decision_time": ppo_decision_time,
        "available_at": available_at,
        "generated_at": generated_at,
        "masa_feature_cutoff": masa_cutoff,
        "ppo_feature_cutoff": ppo_cutoff,
    }, []


def _holdout_example_from_verified_sources(
    *,
    snapshot: Mapping[str, Any],
    tensor: FeatureTensorRecord,
    feature_item: FixedCutoffFeatureSnapshot,
    holdout_sample_identity_sha256: str,
    clocks: Mapping[str, datetime],
    candle_rows: list[dict[str, Any]],
    label_path_proof: Mapping[str, Any],
    observation_cutoff: datetime,
) -> tuple[TrainingExample | None, list[str]]:
    label_path_sha256 = str(label_path_proof.get("label_path_sha256") or "")
    if len(label_path_sha256) != 64:
        return None, ["DURABLE_CANONICAL_5M_LABEL_PATH_HASH_INVALID"]
    label_source_key = (
        "durable_canonical_5m_label_archive:"
        f"{label_path_proof.get('archive_path')}:{label_path_sha256}"
    )
    replay_row, reasons = build_trusted_replay_row(
        snapshot,
        candles=candle_rows,
        training_observed_at=observation_cutoff,
        label_candle_source_key=label_source_key,
    )
    if replay_row is None:
        return None, list(reasons or ["TRUSTED_REPLAY_ROW_NOT_BUILT"])
    features = snapshot.get("features")
    if not isinstance(features, Mapping) or not features:
        return None, ["FEATURES_EMPTY"]
    symbol = str(snapshot.get("symbol") or "").upper()
    timeframe = str(snapshot.get("timeframe") or "")
    tensor_reasons: list[str] = []
    requirement_contract, requirement_reasons = (
        _snapshot_feature_requirement_contract(snapshot)
    )
    if requirement_contract is None:
        tensor_reasons.extend(requirement_reasons)
    if not tensor.values or len(
        {
            len(tensor.values),
            len(tensor.missing_mask),
            len(tensor.stale_mask),
            len(tensor.source_availability),
            len(tensor.source_availability_vector),
            len(tensor.feature_names),
            len(tensor.source_labels),
        }
    ) != 1:
        tensor_reasons.append("FEATURE_TENSOR_SHAPE_OR_CONTENT_INVALID")
    elif requirement_contract is not None:
        if (
            tuple(requirement_contract["ordered_feature_names"])
            != tensor.feature_names
            or tuple(requirement_contract["missing_mask"])
            != tensor.missing_mask
            or tuple(requirement_contract["stale_mask"])
            != tensor.stale_mask
            or tuple(requirement_contract["source_availability_mask"])
            != tensor.source_availability
            or tensor.source_availability != tensor.source_availability_vector
            or tuple(requirement_contract["optional_missing_names"])
            != tensor.missing_feature_names
            or tuple(requirement_contract["stale_names"])
            != tensor.stale_feature_names
        ):
            tensor_reasons.append("FEATURE_TENSOR_REQUIREMENT_BINDING_MISMATCH")
        if requirement_contract["required_missing_names"]:
            tensor_reasons.append("FEATURE_TENSOR_HAS_MISSING_REQUIRED_INPUT")
        if requirement_contract["stale_names"]:
            tensor_reasons.append("FEATURE_TENSOR_HAS_STALE_INPUT")
    if tensor_reasons:
        return None, sorted(set(tensor_reasons))
    assert requirement_contract is not None
    optional_missing_names = list(
        requirement_contract["optional_missing_names"]
    )
    action_index = target_action_index(replay_row.get("target_action"))
    if action_index is None:
        return None, ["ADAPTIVE_TARGET_ACTION_INVALID"]
    trust_row = dict(replay_row)
    trust_row.update(
        {
            "row_source": "trusted_replay_holdout_calibration",
            "trusted_replay_row": True,
            "historical_replay_row": True,
            "evaluation_only": True,
            "row_classification": "TRAINABLE",
            "feature_vector_hash": tensor.tensor_id,
            "masa_feature_cutoff": clocks["masa_feature_cutoff"].isoformat(),
            "ppo_feature_cutoff": clocks["ppo_feature_cutoff"].isoformat(),
            "tensor_decision_time": clocks["tensor_decision_time"].isoformat(),
            "ppo_decision_time": clocks["ppo_decision_time"].isoformat(),
            "holdout_sample_identity_sha256": (
                holdout_sample_identity_sha256
            ),
            "missing_feature_names": optional_missing_names,
            "missing_feature_count": len(optional_missing_names),
            "stale_feature_names": [],
            "stale_feature_count": 0,
            "source_lineage": {
                "durable_feature_snapshot_ledger": True,
                "legacy_feature_snapshot_archive_used": False,
                "feature_snapshot_id": snapshot.get("snapshot_id"),
                "feature_snapshot_content_sha256": snapshot.get("content_sha256"),
                "durable_feature_record_sha256": feature_item.record.get(
                    "record_sha256"
                ),
                "feature_append_receipt_sha256": (
                    feature_item.append_receipt_sha256
                ),
                "feature_postcommit_receipt_sha256": (
                    feature_item.postcommit_receipt_sha256
                ),
                "feature_postcommit_readback_at": (
                    feature_item.postcommit_readback_at
                ),
                "timeframe_finality_lineage_sha256": as_dict(
                    snapshot.get("timeframe_finality_lineage")
                ).get("timeframe_finality_sha256"),
                "durable_canonical_5m_label_archive": True,
                "durable_canonical_5m_label_path_sha256": label_path_sha256,
                "cursor_free_evaluation": True,
            },
        }
    )
    example = TrainingExample(
        symbol=symbol,
        timeframe=timeframe,
        tensor=tensor,
        label_action_index=action_index,
        label_expected_move_after_cost_bps=float(
            replay_row["future_return_after_cost_bps"]
        ),
        payload_keys=(
            f"durable_feature_snapshot_ledger:{snapshot.get('snapshot_id')}",
            str(replay_row.get("sample_id") or ""),
            label_source_key,
        ),
        row_classification="TRAINABLE",
        trust_row=trust_row,
        decision_time=str(replay_row["decision_time"]),
        label_available_at=str(replay_row["label_available_at"]),
    )
    label_available_at = parse_runtime_time(example.label_available_at)
    if (
        example.label_timing_valid is not True
        or label_available_at is None
        or label_available_at > observation_cutoff
    ):
        return None, ["LABEL_NOT_AVAILABLE_BY_FIXED_OBSERVATION_CUTOFF"]
    return example, []


def _legacy_v1_trusted_replay_holdout_examples_disabled(
    *,
    repo_root: Path,
    manifest: Mapping[str, Any],
    scan_limit: int,
    eval_limit: int,
) -> dict[str, Any]:
    return {
        "status": "BLOCKED_LEGACY_V1_HOLDOUT_PROVENANCE_UNSUPPORTED",
        "examples": [],
        "legacy_v1_feature_snapshot_admitted": False,
        "rows_rejected_by_reason": {
            "LEGACY_V1_FEATURE_SNAPSHOT_LACKS_IMMUTABLE_RECEIPT_PROOF": 1
        },
    }

    # Retained temporarily as unreachable migration context. No caller can
    # enter the self-attested v1 archive path.
    start, end, manifest_rows = _holdout_window(manifest)
    if start is None or end is None or start > end:
        return {
            "status": "BLOCKED_NO_TRUSTED_REPLAY_HOLDOUT_WINDOW",
            "examples": [],
            "rows_rejected_by_reason": {"holdout_window_missing": 1},
        }
    root = Path(repo_root).resolve()
    bounded_scan_limit = max(1, min(int(scan_limit), 250_000))
    bounded_eval_limit = max(1, min(int(eval_limit), 5_000))
    base_status: dict[str, Any] = {
        "examples": [],
        "snapshots_scanned": 0,
        "manifest_holdout_rows": manifest_rows,
        "holdout_window": {
            "start_decision_time": start.isoformat(),
            "end_decision_time": end.isoformat(),
        },
        "scan_limit": bounded_scan_limit,
        "eval_limit": bounded_eval_limit,
        "required_label_source": (
            "DURABLE_TIME_INDEXED_CANONICAL_FINALIZED_5M_CANDLE_ARCHIVE"
        ),
        "immutable_feature_snapshot_archive_used": True,
        "same_timeframe_label_fallback_used": False,
        "mutable_redis_history_used_for_historical_labels": False,
        "network_label_fallback_used": False,
        "production_replay_cursor_read": False,
        "production_replay_cursor_written": False,
        "cursor_free_evaluation": True,
        "observation_policy": HOLDOUT_OBSERVATION_POLICY,
        "sampling_policy": HOLDOUT_SAMPLING_POLICY,
    }
    manifest_identity, manifest_reasons = _holdout_manifest_identity(
        repo_root=root,
        manifest=manifest,
    )
    if manifest_identity is None:
        return {
            **base_status,
            "status": "BLOCKED_TRUSTED_REPLAY_HOLDOUT_MANIFEST_UNVERIFIED",
            "rows_rejected_by_reason": {
                reason: 1 for reason in manifest_reasons
            },
        }
    manifest_payload = manifest_identity["payload"]
    observation_cutoff = parse_runtime_time(manifest_payload.get("generated_utc"))
    if observation_cutoff is None or observation_cutoff <= end:
        return {
            **base_status,
            "status": "BLOCKED_HOLDOUT_OBSERVATION_CUTOFF_INVALID",
            "holdout_manifest_file_sha256": manifest_identity["file_sha256"],
            "holdout_manifest_payload_sha256": manifest_identity["payload_sha256"],
            "rows_rejected_by_reason": {
                "MANIFEST_GENERATED_UTC_NOT_AFTER_HOLDOUT_END": 1
            },
        }
    window_identity = {
        "schema_version": manifest_payload.get("schema_version"),
        "split_method": manifest_payload.get("split_method"),
        "temporal_overlap": manifest_payload.get("temporal_overlap"),
        "holdout_window": manifest_payload.get("holdout_window"),
        "observation_policy": HOLDOUT_OBSERVATION_POLICY,
        "observation_cutoff": observation_cutoff.isoformat(),
    }
    base_status.update(
        {
            "holdout_manifest_path": manifest_identity["path"],
            "holdout_manifest_file_sha256": manifest_identity["file_sha256"],
            "holdout_manifest_payload_sha256": manifest_identity["payload_sha256"],
            "holdout_window_observation_sha256": _stable_json_sha256(
                window_identity
            ),
            "training_observed_at": observation_cutoff.isoformat(),
        }
    )

    label_archive_path = default_canonical_5m_label_archive_path(root)
    base_status["durable_canonical_5m_label_archive_path"] = str(
        label_archive_path
    )
    if not label_archive_path.is_file():
        return {
            **base_status,
            "status": "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED",
            "rows_rejected_by_reason": {
                "DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED": max(
                    1, manifest_rows
                )
            },
        }
    label_archive = DurableCanonical5mLabelArchive(label_archive_path)
    try:
        archive_integrity = label_archive.verify_integrity()
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        return {
            **base_status,
            "status": "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_INTEGRITY_CHECK_FAILED",
            "rows_rejected_by_reason": {
                "DURABLE_INDEXED_5M_LABEL_ARCHIVE_INTEGRITY_CHECK_FAILED:"
                f"{type(exc).__name__}": 1
            },
        }
    base_status["durable_canonical_5m_label_archive_integrity"] = archive_integrity
    if archive_integrity.get("archive_integrity_verified") is not True:
        archive_reasons = list(archive_integrity.get("rejection_reasons") or ())
        return {
            **base_status,
            "status": "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_INTEGRITY_UNVERIFIED",
            "rows_rejected_by_reason": {
                str(reason): 1
                for reason in archive_reasons
            }
            or {"DURABLE_INDEXED_5M_LABEL_ARCHIVE_INTEGRITY_UNVERIFIED": 1},
        }
    archive_checkpoint = {
        "archive_chain_sha256": archive_integrity.get("archive_chain_sha256"),
        "verified_rows": archive_integrity.get("verified_rows"),
        "verified_max_sequence": archive_integrity.get("verified_max_sequence"),
        "verified_append_receipts": archive_integrity.get(
            "verified_append_receipts"
        ),
        "verified_postcommit_readback_receipts": archive_integrity.get(
            "verified_postcommit_readback_receipts"
        ),
    }
    base_status.update(
        {
            "durable_canonical_5m_label_archive_integrity_verified": True,
            "label_archive_integrity_checkpoint": archive_checkpoint,
            "label_archive_integrity_checkpoint_sha256": _stable_json_sha256(
                archive_checkpoint
            ),
        }
    )

    feature_archive_root = default_trusted_replay_archive_root(root).resolve()
    feature_manifest = feature_archive_root / "manifest.jsonl"
    base_status["durable_feature_snapshot_archive_root"] = str(
        feature_archive_root
    )
    if not feature_manifest.is_file():
        return {
            **base_status,
            "status": "BLOCKED_DURABLE_FEATURE_SNAPSHOT_MANIFEST_REQUIRED",
            "rows_rejected_by_reason": {
                "DURABLE_FEATURE_SNAPSHOT_MANIFEST_REQUIRED": 1
            },
        }
    try:
        manifest_stat_before = feature_manifest.stat()
    except OSError:
        return {
            **base_status,
            "status": "BLOCKED_DURABLE_FEATURE_SNAPSHOT_MANIFEST_UNREADABLE",
            "rows_rejected_by_reason": {
                "DURABLE_FEATURE_SNAPSHOT_MANIFEST_UNREADABLE": 1
            },
        }
    manifest_size_at_scan_start = manifest_stat_before.st_size

    rejections: dict[str, int] = {}
    selected_heap: list[tuple[int, str, dict[str, Any], dict[str, datetime]]] = []
    selected_identity_by_snapshot: dict[str, str] = {}
    feature_manifest_prefix_hash = hashlib.sha256()
    snapshots_scanned = 0
    holdout_candidates_found = 0
    manifest_scan_truncated = False
    fatal_feature_archive_error = False
    scanned_prefix_bytes = 0
    try:
        with feature_manifest.open("rb") as handle:
            while (
                snapshots_scanned < bounded_scan_limit
                and handle.tell() < manifest_size_at_scan_start
            ):
                remaining_at_scan_start = (
                    manifest_size_at_scan_start - handle.tell()
                )
                raw_line = handle.readline(
                    min(
                        HOLDOUT_FEATURE_MANIFEST_LINE_MAX_BYTES + 1,
                        remaining_at_scan_start,
                    )
                )
                if not raw_line:
                    break
                snapshots_scanned += 1
                feature_manifest_prefix_hash.update(raw_line)
                if (
                    len(raw_line) > HOLDOUT_FEATURE_MANIFEST_LINE_MAX_BYTES
                    or not raw_line.endswith(b"\n")
                ):
                    reason = "FEATURE_ARCHIVE_MANIFEST_LINE_INVALID_OR_TORN"
                    rejections[reason] = rejections.get(reason, 0) + 1
                    fatal_feature_archive_error = True
                    continue
                try:
                    index_record = _strict_json_object(raw_line)
                    snapshot_id = str(index_record.get("snapshot_id") or "")
                    manifest_content_sha256 = str(
                        index_record.get("content_sha256") or ""
                    )
                    if not snapshot_id or len(manifest_content_sha256) != 64:
                        raise ValueError("feature_manifest_identity_invalid")
                    snapshot = load_durable_feature_snapshot(
                        snapshot_id,
                        root=feature_archive_root,
                        verify=True,
                    )
                    if snapshot is None:
                        raise SnapshotArchiveError("ARCHIVE_SNAPSHOT_MISSING")
                    if str(snapshot.get("content_sha256") or "") != (
                        manifest_content_sha256
                    ):
                        raise SnapshotArchiveError(
                            "MANIFEST_SNAPSHOT_CONTENT_SHA256_MISMATCH"
                        )
                except (
                    OSError,
                    SnapshotArchiveError,
                    TypeError,
                    ValueError,
                    UnicodeDecodeError,
                ) as exc:
                    reason = f"FEATURE_ARCHIVE_RECORD_UNVERIFIED:{type(exc).__name__}"
                    rejections[reason] = rejections.get(reason, 0) + 1
                    fatal_feature_archive_error = True
                    continue
                clocks, clock_reasons = _holdout_snapshot_clock_contract(snapshot)
                if clocks is None:
                    for reason in clock_reasons:
                        rejections[reason] = rejections.get(reason, 0) + 1
                    continue
                decision_time = clocks["decision_time"]
                if decision_time < start or decision_time > end:
                    continue
                holdout_candidates_found += 1
                identity = {
                    "snapshot_id": snapshot_id,
                    "content_sha256": manifest_content_sha256,
                    "symbol": str(snapshot.get("symbol") or "").upper(),
                    "timeframe": str(snapshot.get("timeframe") or ""),
                    "decision_time": decision_time.isoformat(),
                }
                identity_sha256 = _stable_json_sha256(identity)
                prior_identity = selected_identity_by_snapshot.get(snapshot_id)
                if prior_identity is not None:
                    reason = (
                        "FEATURE_ARCHIVE_DUPLICATE_SNAPSHOT_ID_CONFLICT"
                        if prior_identity != identity_sha256
                        else "FEATURE_ARCHIVE_DUPLICATE_SNAPSHOT_ID"
                    )
                    rejections[reason] = rejections.get(reason, 0) + 1
                    if prior_identity != identity_sha256:
                        fatal_feature_archive_error = True
                    continue
                selected_identity_by_snapshot[snapshot_id] = identity_sha256
                priority_material = {
                    "sampling_policy": HOLDOUT_SAMPLING_POLICY,
                    "holdout_window_observation_sha256": base_status[
                        "holdout_window_observation_sha256"
                    ],
                    "sample_identity": identity,
                }
                priority = int(_stable_json_sha256(priority_material), 16)
                heap_item = (-priority, identity_sha256, dict(snapshot), clocks)
                if len(selected_heap) < bounded_eval_limit:
                    heapq.heappush(selected_heap, heap_item)
                elif priority < -selected_heap[0][0]:
                    heapq.heapreplace(selected_heap, heap_item)
            scanned_prefix_bytes = handle.tell()
            manifest_scan_truncated = (
                scanned_prefix_bytes < manifest_size_at_scan_start
            )
    except OSError as exc:
        reason = f"FEATURE_ARCHIVE_MANIFEST_SCAN_FAILED:{type(exc).__name__}"
        rejections[reason] = rejections.get(reason, 0) + 1
        fatal_feature_archive_error = True
    try:
        manifest_stat_after = feature_manifest.stat()
    except OSError:
        manifest_stat_after = None
    manifest_identity_stable = bool(
        manifest_stat_after is not None
        and manifest_stat_before.st_dev == manifest_stat_after.st_dev
        and manifest_stat_before.st_ino == manifest_stat_after.st_ino
        and manifest_stat_after.st_size >= manifest_size_at_scan_start
    )
    prefix_hash_at_completion: str | None = None
    if manifest_identity_stable:
        try:
            completion_hash = hashlib.sha256()
            with feature_manifest.open("rb") as handle:
                opened_stat = os.fstat(handle.fileno())
                if (
                    opened_stat.st_dev != manifest_stat_before.st_dev
                    or opened_stat.st_ino != manifest_stat_before.st_ino
                    or opened_stat.st_size < scanned_prefix_bytes
                ):
                    raise OSError("feature_manifest_identity_changed")
                remaining = scanned_prefix_bytes
                while remaining:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise OSError("feature_manifest_prefix_short_read")
                    completion_hash.update(chunk)
                    remaining -= len(chunk)
            path_stat_at_completion = feature_manifest.stat()
            if (
                path_stat_at_completion.st_dev != manifest_stat_before.st_dev
                or path_stat_at_completion.st_ino != manifest_stat_before.st_ino
                or path_stat_at_completion.st_size < manifest_size_at_scan_start
            ):
                raise OSError("feature_manifest_path_identity_changed")
            prefix_hash_at_completion = completion_hash.hexdigest()
        except OSError:
            manifest_identity_stable = False
    manifest_prefix_stable = bool(
        manifest_identity_stable
        and prefix_hash_at_completion == feature_manifest_prefix_hash.hexdigest()
    )
    if not manifest_prefix_stable:
        rejections["FEATURE_ARCHIVE_MANIFEST_CHANGED_DURING_SCAN"] = 1
        fatal_feature_archive_error = True
    feature_scan_identity = {
        "sampling_policy": HOLDOUT_SAMPLING_POLICY,
        "manifest_path": str(feature_manifest),
        "manifest_size_bytes_at_scan_start": manifest_size_at_scan_start,
        "scanned_prefix_bytes": scanned_prefix_bytes,
        "scanned_manifest_rows": snapshots_scanned,
        "scan_limit": bounded_scan_limit,
        "scan_truncated": manifest_scan_truncated,
        "scanned_prefix_sha256": feature_manifest_prefix_hash.hexdigest(),
    }
    base_status.update(
        {
            "snapshots_scanned": snapshots_scanned,
            "feature_manifest_scan_truncated": manifest_scan_truncated,
            "feature_manifest_scanned_prefix_sha256": (
                feature_manifest_prefix_hash.hexdigest()
            ),
            "feature_manifest_scan_identity_sha256": _stable_json_sha256(
                feature_scan_identity
            ),
            "holdout_candidates_found": holdout_candidates_found,
        }
    )
    if fatal_feature_archive_error:
        return {
            **base_status,
            "status": "BLOCKED_DURABLE_FEATURE_SNAPSHOT_ARCHIVE_UNVERIFIED",
            "rows_rejected_by_reason": dict(sorted(rejections.items())),
        }

    selected = sorted(
        selected_heap,
        key=lambda item: (
            item[3]["decision_time"],
            str(item[2].get("symbol") or ""),
            str(item[2].get("timeframe") or ""),
            str(item[2].get("snapshot_id") or ""),
            item[1],
        ),
    )
    selected_sample_order = [
        {
            "snapshot_id": item[2].get("snapshot_id"),
            "content_sha256": item[2].get("content_sha256"),
            "symbol": item[2].get("symbol"),
            "timeframe": item[2].get("timeframe"),
            "decision_time": item[3]["decision_time"].isoformat(),
        }
        for item in selected
    ]
    selected_order_sha256 = _stable_json_sha256(selected_sample_order)
    tensor_loader = V2HybridTrainerDataLoader(
        io=V2OnlyJsonIO(client=None),
        trusted_replay_archive_root=feature_archive_root,
        canonical_5m_label_archive_path=label_archive_path,
    )
    examples: list[TrainingExample] = []
    label_path_identities: list[dict[str, Any]] = []
    for _priority, _identity_hash, snapshot, clocks in selected:
        try:
            candle_rows, label_path_proof = label_archive.verified_label_path(
                symbol=str(snapshot.get("symbol") or "").upper(),
                decision_time=clocks["decision_time"],
                training_observed_at=observation_cutoff,
                horizon_seconds=HORIZON_SECONDS["4h"],
                archive_integrity_proof=archive_integrity,
            )
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            reason = f"DURABLE_CANONICAL_5M_LABEL_PATH_READ_FAILED:{type(exc).__name__}"
            rejections[reason] = rejections.get(reason, 0) + 1
            continue
        if candle_rows is None:
            for reason in label_path_proof.get("rejection_reasons") or (
                "DURABLE_CANONICAL_5M_LABEL_PATH_UNVERIFIED",
            ):
                rejections[str(reason)] = rejections.get(str(reason), 0) + 1
            continue
        example, example_reasons = _holdout_example_from_verified_sources(
            snapshot=snapshot,
            clocks=clocks,
            candle_rows=candle_rows,
            label_path_proof=label_path_proof,
            observation_cutoff=observation_cutoff,
            tensor_loader=tensor_loader,
        )
        if example is None:
            for reason in example_reasons:
                rejections[str(reason)] = rejections.get(str(reason), 0) + 1
            continue
        examples.append(example)
        label_path_identities.append(
            {
                "sample_id": as_dict(example.trust_row).get("sample_id"),
                "decision_time": as_dict(example.trust_row).get("decision_time"),
                "label_path_sha256": label_path_proof.get("label_path_sha256"),
                "range_sha256": as_dict(label_path_proof.get("range_proof")).get(
                    "range_sha256"
                ),
                "label_available_at_ms": label_path_proof.get(
                    "label_available_at_ms"
                ),
            }
        )
    try:
        archive_proof_current_at_completion = (
            label_archive.integrity_proof_is_current(archive_integrity)
        )
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        archive_proof_current_at_completion = False
        reason = (
            "LABEL_ARCHIVE_FULL_INTEGRITY_PROOF_CURRENT_CHECK_FAILED:"
            f"{type(exc).__name__}"
        )
        rejections[reason] = rejections.get(reason, 0) + 1
    if not archive_proof_current_at_completion:
        rejections["LABEL_ARCHIVE_FULL_INTEGRITY_PROOF_STALE_AT_COMPLETION"] = 1
        examples = []
        label_path_identities = []
    completion_manifest_identity, _completion_manifest_reasons = (
        _holdout_manifest_identity(
            repo_root=root,
            manifest=manifest,
        )
    )
    holdout_manifest_current_at_completion = bool(
        completion_manifest_identity is not None
        and completion_manifest_identity["file_sha256"]
        == manifest_identity["file_sha256"]
        and completion_manifest_identity["payload_sha256"]
        == manifest_identity["payload_sha256"]
    )
    if not holdout_manifest_current_at_completion:
        rejections["HOLDOUT_MANIFEST_CHANGED_DURING_EVALUATION"] = 1
        examples = []
        label_path_identities = []
    evaluated_order = [
        {
            "sample_id": as_dict(example.trust_row).get("sample_id"),
            "feature_snapshot_id": example.tensor.feature_snapshot_id,
            "decision_time": example.decision_time,
            "tensor_id": example.tensor.tensor_id,
        }
        for example in examples
    ]
    status = (
        "VERIFIED_CURSOR_FREE_TRUSTED_REPLAY_HOLDOUT_EXAMPLES"
        if examples
        else "BLOCKED_NO_USABLE_HOLDOUT_EXAMPLES"
    )
    if not archive_proof_current_at_completion:
        status = "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_PROOF_STALE"
    elif not holdout_manifest_current_at_completion:
        status = "BLOCKED_TRUSTED_REPLAY_HOLDOUT_MANIFEST_STALE"
    return {
        **base_status,
        "status": status,
        "examples": examples,
        "selected_holdout_candidates": len(selected),
        "selected_holdout_sample_order_sha256": selected_order_sha256,
        "holdout_sample_identity_hash": _stable_json_sha256(evaluated_order),
        "evaluated_example_order_sha256": _stable_json_sha256(evaluated_order),
        "durable_label_path_identity_sha256": _stable_json_sha256(
            label_path_identities
        ),
        "durable_label_ranges_verified": len(label_path_identities),
        "archive_integrity_proof_current_at_completion": (
            archive_proof_current_at_completion
        ),
        "holdout_manifest_current_at_completion": (
            holdout_manifest_current_at_completion
        ),
        "rows_rejected_by_reason": dict(sorted(rejections.items())),
    }


def _trusted_replay_holdout_examples(
    *,
    repo_root: Path,
    manifest: Mapping[str, Any],
    scan_limit: int,
    eval_limit: int,
) -> dict[str, Any]:
    """Build one fail-closed holdout from two immutable ledger prefixes.

    Feature evidence is fixed at checkpoint-manifest publication.  Label
    evidence is independently fixed when evaluation begins, allowing causal
    outcomes to mature without moving the feature or partition boundary.
    """

    evaluation_started_at = datetime.now(timezone.utc)
    start, end, manifest_rows = _holdout_window(manifest)
    if start is None or end is None or start > end:
        return {
            "status": "BLOCKED_NO_TRUSTED_REPLAY_HOLDOUT_WINDOW",
            "examples": [],
            "rows_rejected_by_reason": {"holdout_window_missing": 1},
        }
    root = Path(repo_root).resolve()
    bounded_scan_limit = max(1, min(int(scan_limit), 250_000))
    bounded_eval_limit = max(1, min(int(eval_limit), 5_000))
    base_status: dict[str, Any] = {
        "examples": [],
        "snapshots_scanned": 0,
        "manifest_holdout_rows": manifest_rows,
        "holdout_window": {
            "start_decision_time": start.isoformat(),
            "end_decision_time": end.isoformat(),
        },
        "scan_limit": bounded_scan_limit,
        "eval_limit": bounded_eval_limit,
        "required_label_source": (
            "DURABLE_TIME_INDEXED_CANONICAL_FINALIZED_5M_CANDLE_ARCHIVE"
        ),
        "immutable_feature_snapshot_archive_used": False,
        "durable_feature_snapshot_ledger_used": True,
        "legacy_v1_feature_snapshot_admitted": False,
        "same_timeframe_label_fallback_used": False,
        "mutable_redis_history_used_for_historical_labels": False,
        "network_label_fallback_used": False,
        "production_replay_cursor_read": False,
        "production_replay_cursor_written": False,
        "cursor_free_evaluation": True,
        "observation_policy": HOLDOUT_OBSERVATION_POLICY,
        "sampling_policy": HOLDOUT_SAMPLING_POLICY,
        "feature_manifest_scan_truncated": False,
    }
    manifest_identity, manifest_reasons = _holdout_manifest_identity(
        repo_root=root,
        manifest=manifest,
    )
    if manifest_identity is None:
        return {
            **base_status,
            "status": "BLOCKED_TRUSTED_REPLAY_HOLDOUT_MANIFEST_UNVERIFIED",
            "rows_rejected_by_reason": {
                reason: 1 for reason in manifest_reasons
            },
        }
    manifest_payload = manifest_identity["payload"]
    feature_observation_cutoff = parse_runtime_time(
        manifest_payload.get("generated_utc")
    )
    if (
        feature_observation_cutoff is None
        or feature_observation_cutoff <= end
        or feature_observation_cutoff > evaluation_started_at
    ):
        cutoff_reason = (
            "MANIFEST_GENERATED_UTC_IN_FUTURE"
            if feature_observation_cutoff is not None
            and feature_observation_cutoff > evaluation_started_at
            else "MANIFEST_GENERATED_UTC_NOT_AFTER_HOLDOUT_END"
        )
        return {
            **base_status,
            "status": "BLOCKED_HOLDOUT_OBSERVATION_CUTOFF_INVALID",
            "holdout_manifest_file_sha256": manifest_identity["file_sha256"],
            "holdout_manifest_payload_sha256": manifest_identity[
                "payload_sha256"
            ],
            "rows_rejected_by_reason": {cutoff_reason: 1},
        }
    # Features are frozen at checkpoint-manifest publication, while labels
    # are allowed to mature until this evaluation begins.  Query the strict
    # predecessor of each boundary so a receipt stamped exactly at a boundary
    # cannot be admitted ambiguously.
    try:
        feature_strict_prior_cutoff = feature_observation_cutoff - timedelta(
            microseconds=1
        )
        label_evaluation_cutoff = evaluation_started_at
        label_strict_prior_cutoff = label_evaluation_cutoff - timedelta(
            microseconds=1
        )
    except OverflowError:
        return {
            **base_status,
            "status": "BLOCKED_HOLDOUT_OBSERVATION_CUTOFF_INVALID",
            "holdout_manifest_file_sha256": manifest_identity["file_sha256"],
            "holdout_manifest_payload_sha256": manifest_identity[
                "payload_sha256"
            ],
            "rows_rejected_by_reason": {
                "HOLDOUT_STRICT_PRIOR_OBSERVATION_CUTOFF_UNREPRESENTABLE": 1
            },
        }
    window_identity = {
        "schema_version": manifest_payload.get("schema_version"),
        "split_method": manifest_payload.get("split_method"),
        "temporal_overlap": manifest_payload.get("temporal_overlap"),
        "holdout_window": manifest_payload.get("holdout_window"),
        "feature_ledger_high_water_sha256": as_dict(
            manifest_payload.get("feature_ledger_high_water")
        ).get("high_water_sha256"),
        "label_archive_high_water_sha256": as_dict(
            manifest_payload.get("label_archive_high_water")
        ).get("high_water_sha256"),
        "holdout_partition_identity_set_sha256": as_dict(
            manifest_payload.get("partition_evidence")
        ).get("holdout_sample_identity_set_sha256"),
        "observation_policy": HOLDOUT_OBSERVATION_POLICY,
        "observation_cutoff": feature_observation_cutoff.isoformat(),
        "feature_observation_cutoff": (
            feature_observation_cutoff.isoformat()
        ),
    }
    base_status.update(
        {
            "holdout_manifest_path": manifest_identity["path"],
            "holdout_manifest_file_sha256": manifest_identity["file_sha256"],
            "holdout_manifest_payload_sha256": manifest_identity[
                "payload_sha256"
            ],
            "holdout_window_observation_sha256": _stable_json_sha256(
                window_identity
            ),
            # Compatibility field: labels, and therefore the completed
            # evaluation examples, are observed at evaluation start.
            "training_observed_at": label_evaluation_cutoff.isoformat(),
            "feature_observation_cutoff": (
                feature_observation_cutoff.isoformat()
            ),
            "feature_strict_prior_observation_cutoff": (
                feature_strict_prior_cutoff.isoformat()
            ),
            "label_evaluation_cutoff": label_evaluation_cutoff.isoformat(),
            "label_strict_prior_evaluation_cutoff": (
                label_strict_prior_cutoff.isoformat()
            ),
            "feature_and_label_observation_clocks_distinguished": True,
        }
    )

    label_archive_path = default_canonical_5m_label_archive_path(root)
    base_status["durable_canonical_5m_label_archive_path"] = str(
        label_archive_path
    )
    if not label_archive_path.is_file():
        return {
            **base_status,
            "status": "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED",
            "rows_rejected_by_reason": {
                "DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED": max(
                    1, manifest_rows
                )
            },
        }
    label_archive = DurableCanonical5mLabelArchive(label_archive_path)
    try:
        label_integrity = label_archive.verify_integrity()
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        return {
            **base_status,
            "status": (
                "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_INTEGRITY_CHECK_FAILED"
            ),
            "rows_rejected_by_reason": {
                "DURABLE_INDEXED_5M_LABEL_ARCHIVE_INTEGRITY_CHECK_FAILED:"
                f"{type(exc).__name__}": 1
            },
        }
    if label_integrity.get("archive_integrity_verified") is not True:
        reasons = list(label_integrity.get("rejection_reasons") or ())
        return {
            **base_status,
            "status": (
                "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_INTEGRITY_UNVERIFIED"
            ),
            "durable_canonical_5m_label_archive_integrity": label_integrity,
            "rows_rejected_by_reason": {
                str(reason): 1 for reason in reasons
            }
            or {"DURABLE_INDEXED_5M_LABEL_ARCHIVE_INTEGRITY_UNVERIFIED": 1},
        }
    manifest_label_high_water, manifest_label_high_water_reasons = (
        _label_archive_integrity_checkpoint(
            archive=label_archive,
            integrity=label_integrity,
            observation_cutoff=feature_observation_cutoff,
            scan_limit=bounded_scan_limit,
        )
    )
    if manifest_label_high_water is None:
        return {
            **base_status,
            "status": "BLOCKED_LABEL_ARCHIVE_HIGH_WATER_UNVERIFIED",
            "rows_rejected_by_reason": {
                reason: 1 for reason in manifest_label_high_water_reasons
            },
        }
    if as_dict(manifest_payload.get("label_archive_high_water")) != (
        manifest_label_high_water
    ):
        return {
            **base_status,
            "status": "BLOCKED_LABEL_ARCHIVE_HIGH_WATER_MISMATCH",
            "observed_label_archive_high_water": manifest_label_high_water,
            "observed_manifest_label_archive_high_water": (
                manifest_label_high_water
            ),
            "expected_manifest_label_archive_high_water": as_dict(
                manifest_payload.get("label_archive_high_water")
            ),
            "rows_rejected_by_reason": {
                "LABEL_ARCHIVE_HIGH_WATER_MISMATCH": 1
            },
        }
    evaluation_label_high_water, evaluation_label_high_water_reasons = (
        _label_archive_integrity_checkpoint(
            archive=label_archive,
            integrity=label_integrity,
            observation_cutoff=label_evaluation_cutoff,
            scan_limit=bounded_scan_limit,
        )
    )
    if evaluation_label_high_water is None:
        return {
            **base_status,
            "status": "BLOCKED_EVALUATION_LABEL_ARCHIVE_HIGH_WATER_UNVERIFIED",
            "rows_rejected_by_reason": {
                reason: 1 for reason in evaluation_label_high_water_reasons
            },
        }
    base_status.update(
        {
            "durable_canonical_5m_label_archive_integrity": label_integrity,
            "durable_canonical_5m_label_archive_integrity_verified": True,
            # Compatibility names retain the checkpoint-manifest prefix.
            "label_archive_integrity_checkpoint": manifest_label_high_water,
            "label_archive_integrity_checkpoint_sha256": (
                manifest_label_high_water["high_water_sha256"]
            ),
            "manifest_label_archive_high_water": manifest_label_high_water,
            "manifest_label_archive_high_water_sha256": (
                manifest_label_high_water["high_water_sha256"]
            ),
            "evaluation_label_archive_high_water": (
                evaluation_label_high_water
            ),
            "evaluation_label_archive_high_water_sha256": (
                evaluation_label_high_water["high_water_sha256"]
            ),
            "manifest_label_prefix_reproduced_at_feature_cutoff": True,
            "evaluation_label_prefix_frozen_at_evaluation_start": True,
            "label_path_full_tail_integrity_proof_reused": False,
        }
    )

    feature_ledger_path = default_feature_snapshot_ledger_path(root)
    base_status["durable_feature_snapshot_ledger_path"] = str(
        feature_ledger_path
    )
    if not feature_ledger_path.is_file():
        return {
            **base_status,
            "status": "BLOCKED_DURABLE_FEATURE_SNAPSHOT_LEDGER_REQUIRED",
            "rows_rejected_by_reason": {
                "DURABLE_FEATURE_SNAPSHOT_LEDGER_REQUIRED": 1
            },
        }
    feature_ledger = DurableFeatureSnapshotLedger(feature_ledger_path)
    try:
        feature_integrity = feature_ledger.verify_integrity_streaming()
    except (
        OSError,
        sqlite3.Error,
        FeatureSnapshotLedgerError,
        TypeError,
        ValueError,
    ) as exc:
        return {
            **base_status,
            "status": "BLOCKED_DURABLE_FEATURE_SNAPSHOT_LEDGER_UNVERIFIED",
            "rows_rejected_by_reason": {
                f"FEATURE_LEDGER_INTEGRITY_FAILED:{type(exc).__name__}": 1
            },
        }
    feature_high_water, feature_high_water_reasons = (
        _feature_ledger_integrity_checkpoint(
            ledger=feature_ledger,
            report=feature_integrity,
            observation_cutoff=feature_observation_cutoff,
            scan_limit=bounded_scan_limit,
        )
    )
    if feature_high_water is None:
        return {
            **base_status,
            "status": "BLOCKED_FEATURE_LEDGER_HIGH_WATER_UNVERIFIED",
            "rows_rejected_by_reason": {
                reason: 1 for reason in feature_high_water_reasons
            },
        }
    if as_dict(manifest_payload.get("feature_ledger_high_water")) != (
        feature_high_water
    ):
        return {
            **base_status,
            "status": "BLOCKED_FEATURE_LEDGER_HIGH_WATER_MISMATCH",
            "observed_feature_ledger_high_water": feature_high_water,
            "rows_rejected_by_reason": {
                "FEATURE_LEDGER_HIGH_WATER_MISMATCH": 1
            },
        }
    base_status.update(
        {
            "feature_ledger_integrity_checkpoint": feature_high_water,
            "feature_ledger_integrity_checkpoint_sha256": feature_high_water[
                "high_water_sha256"
            ],
        }
    )

    scanned: list[FixedCutoffFeatureSnapshot] = []
    after_sequence = 0
    try:
        while len(scanned) <= bounded_scan_limit:
            page = feature_ledger.query_fixed_cutoff(
                decision_time_cutoff=end.isoformat(),
                training_observed_at=(
                    feature_strict_prior_cutoff.isoformat()
                ),
                limit=min(
                    FEATURE_LEDGER_MAX_QUERY_ROWS,
                    bounded_scan_limit + 1 - len(scanned),
                ),
                after_sequence=after_sequence,
            )
            if not page:
                break
            scanned.extend(page)
            after_sequence = page[-1].sequence
            if len(scanned) > bounded_scan_limit:
                break
    except (
        OSError,
        sqlite3.Error,
        FeatureSnapshotLedgerError,
        TypeError,
        ValueError,
    ) as exc:
        return {
            **base_status,
            "status": "BLOCKED_DURABLE_FEATURE_SNAPSHOT_LEDGER_QUERY_FAILED",
            "rows_rejected_by_reason": {
                f"FEATURE_LEDGER_FIXED_CUTOFF_QUERY_FAILED:{type(exc).__name__}": 1
            },
        }
    base_status["snapshots_scanned"] = len(scanned)
    if len(scanned) > bounded_scan_limit:
        return {
            **base_status,
            "status": "BLOCKED_FEATURE_LEDGER_SCAN_TRUNCATED",
            "feature_manifest_scan_truncated": True,
            "rows_rejected_by_reason": {
                "FEATURE_LEDGER_SCAN_TRUNCATED_NO_PREFIX_ADMISSION": 1
            },
        }

    rejections: dict[str, int] = {}
    candidates: list[
        tuple[
            int,
            str,
            FixedCutoffFeatureSnapshot,
            dict[str, Any],
            FeatureTensorRecord,
            dict[str, datetime],
        ]
    ] = []
    candidate_identity_sha256s: list[str] = []
    fatal_candidate_error = False
    for item in scanned:
        envelope = as_dict(item.record.get("frozen_envelope"))
        decision = parse_runtime_time(envelope.get("ppo_decision_time"))
        if decision is None:
            rejections["PPO_DECISION_TIME_MISSING_OR_INVALID"] = (
                rejections.get("PPO_DECISION_TIME_MISSING_OR_INVALID", 0) + 1
            )
            fatal_candidate_error = True
            continue
        if decision < start or decision > end:
            continue
        identity, identity_sha256 = _holdout_feature_sample_identity(item)
        snapshot, tensor, conversion_reasons = (
            _snapshot_from_feature_ledger_item(item)
        )
        if snapshot is None or tensor is None:
            for reason in conversion_reasons:
                rejections[reason] = rejections.get(reason, 0) + 1
            fatal_candidate_error = True
            continue
        clocks, clock_reasons = _holdout_snapshot_clock_contract(snapshot)
        if clocks is None:
            for reason in clock_reasons:
                rejections[reason] = rejections.get(reason, 0) + 1
            fatal_candidate_error = True
            continue
        candidate_identity_sha256s.append(identity_sha256)
        priority = int(
            _stable_json_sha256(
                {
                    "sampling_policy": HOLDOUT_SAMPLING_POLICY,
                    "holdout_window_observation_sha256": base_status[
                        "holdout_window_observation_sha256"
                    ],
                    "sample_identity": identity,
                }
            ),
            16,
        )
        candidates.append(
            (
                priority,
                identity_sha256,
                item,
                snapshot,
                tensor,
                clocks,
            )
        )
    base_status["holdout_candidates_found"] = len(candidates)
    partition_reasons = _holdout_partition_reasons(
        manifest_payload=manifest_payload,
        candidate_identity_sha256s=candidate_identity_sha256s,
        manifest_rows=manifest_rows,
    )
    if fatal_candidate_error or partition_reasons:
        for reason in partition_reasons:
            rejections[reason] = rejections.get(reason, 0) + 1
        return {
            **base_status,
            "status": "BLOCKED_AUTHENTICATED_HOLDOUT_PARTITION_UNVERIFIED",
            "holdout_partition_sample_identity_set_sha256": (
                _sample_identity_set_sha256(candidate_identity_sha256s)
            ),
            "rows_rejected_by_reason": dict(sorted(rejections.items())),
        }

    selected_by_priority = sorted(candidates, key=lambda item: (item[0], item[1]))[
        :bounded_eval_limit
    ]
    selected = sorted(
        selected_by_priority,
        key=lambda item: (
            item[5]["ppo_decision_time"],
            str(item[3].get("symbol") or ""),
            str(item[3].get("timeframe") or ""),
            str(item[3].get("snapshot_id") or ""),
            item[1],
        ),
    )
    selected_sample_order = [
        {
            "snapshot_id": item[3].get("snapshot_id"),
            "content_sha256": item[3].get("content_sha256"),
            "record_sha256": item[2].record.get("record_sha256"),
            "symbol": item[3].get("symbol"),
            "timeframe": item[3].get("timeframe"),
            "ppo_decision_time": item[5]["ppo_decision_time"].isoformat(),
            "holdout_sample_identity_sha256": item[1],
        }
        for item in selected
    ]
    selected_order_sha256 = _stable_json_sha256(selected_sample_order)
    examples: list[TrainingExample] = []
    label_path_identities: list[dict[str, Any]] = []
    fatal_label_error = False
    for (
        _priority,
        identity_sha256,
        feature_item,
        snapshot,
        tensor,
        clocks,
    ) in selected:
        try:
            candle_rows, label_path_proof = label_archive.verified_label_path(
                symbol=str(snapshot.get("symbol") or "").upper(),
                decision_time=clocks["ppo_decision_time"],
                training_observed_at=label_strict_prior_cutoff,
                horizon_seconds=HORIZON_SECONDS["4h"],
                # A full-tail proof captured before this range read would be
                # invalidated by an unrelated valid suffix append.  The range
                # reader establishes a fresh local snapshot/proof instead.
                archive_integrity_proof=None,
                require_receipt_committed_by_observation=True,
            )
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            reason = (
                "DURABLE_CANONICAL_5M_LABEL_PATH_READ_FAILED:"
                f"{type(exc).__name__}"
            )
            rejections[reason] = rejections.get(reason, 0) + 1
            fatal_label_error = True
            continue
        if candle_rows is None:
            for reason in label_path_proof.get("rejection_reasons") or (
                "DURABLE_CANONICAL_5M_LABEL_PATH_UNVERIFIED",
            ):
                rejections[str(reason)] = rejections.get(str(reason), 0) + 1
            fatal_label_error = True
            continue
        example, example_reasons = _holdout_example_from_verified_sources(
            snapshot=snapshot,
            tensor=tensor,
            feature_item=feature_item,
            holdout_sample_identity_sha256=identity_sha256,
            clocks=clocks,
            candle_rows=candle_rows,
            label_path_proof=label_path_proof,
            observation_cutoff=label_evaluation_cutoff,
        )
        if example is None:
            for reason in example_reasons:
                rejections[str(reason)] = rejections.get(str(reason), 0) + 1
            fatal_label_error = True
            continue
        examples.append(example)
        label_path_identities.append(
            {
                "holdout_sample_identity_sha256": identity_sha256,
                "sample_id": as_dict(example.trust_row).get("sample_id"),
                "decision_time": as_dict(example.trust_row).get(
                    "decision_time"
                ),
                "label_path_sha256": label_path_proof.get(
                    "label_path_sha256"
                ),
                "range_sha256": as_dict(
                    label_path_proof.get("range_proof")
                ).get("range_sha256"),
                "label_available_at_ms": label_path_proof.get(
                    "label_available_at_ms"
                ),
            }
        )
    if fatal_label_error:
        examples = []
        label_path_identities = []

    label_current = False
    manifest_label_prefix_current = False
    evaluation_label_prefix_current = False
    label_full_integrity_verified_at_completion = False
    feature_current = False
    feature_full_integrity_verified_at_completion = False
    try:
        completion_label_integrity = label_archive.verify_integrity()
        label_full_integrity_verified_at_completion = bool(
            completion_label_integrity.get("archive_integrity_verified")
            is True
        )
        completion_manifest_label_high_water, _ = (
            _label_archive_integrity_checkpoint(
                archive=label_archive,
                integrity=completion_label_integrity,
                observation_cutoff=feature_observation_cutoff,
                scan_limit=bounded_scan_limit,
            )
        )
        completion_evaluation_label_high_water, _ = (
            _label_archive_integrity_checkpoint(
                archive=label_archive,
                integrity=completion_label_integrity,
                observation_cutoff=label_evaluation_cutoff,
                scan_limit=bounded_scan_limit,
            )
        )
        manifest_label_prefix_current = bool(
            label_full_integrity_verified_at_completion
            and completion_manifest_label_high_water
            == manifest_label_high_water
            and completion_manifest_label_high_water
            == as_dict(manifest_payload.get("label_archive_high_water"))
        )
        evaluation_label_prefix_current = bool(
            label_full_integrity_verified_at_completion
            and completion_evaluation_label_high_water
            == evaluation_label_high_water
        )
        label_current = bool(
            manifest_label_prefix_current
            and evaluation_label_prefix_current
        )
    except (OSError, sqlite3.Error, TypeError, ValueError):
        label_current = False
    try:
        completion_feature_integrity = (
            feature_ledger.verify_integrity_streaming()
        )
        feature_full_integrity_verified_at_completion = bool(
            completion_feature_integrity.integrity_verified is True
        )
        completion_feature_high_water, _ = (
            _feature_ledger_integrity_checkpoint(
                ledger=feature_ledger,
                report=completion_feature_integrity,
                observation_cutoff=feature_observation_cutoff,
                scan_limit=bounded_scan_limit,
            )
        )
        feature_current = bool(
            feature_full_integrity_verified_at_completion
            and completion_feature_high_water == feature_high_water
            and completion_feature_high_water
            == as_dict(manifest_payload.get("feature_ledger_high_water"))
        )
    except (
        OSError,
        sqlite3.Error,
        FeatureSnapshotLedgerError,
        TypeError,
        ValueError,
    ):
        feature_current = False
    completion_manifest_identity, _ = _holdout_manifest_identity(
        repo_root=root,
        manifest=manifest,
    )
    manifest_current = bool(
        completion_manifest_identity is not None
        and completion_manifest_identity["file_sha256"]
        == manifest_identity["file_sha256"]
        and completion_manifest_identity["payload_sha256"]
        == manifest_identity["payload_sha256"]
    )
    if not label_current:
        rejections["LABEL_ARCHIVE_HIGH_WATER_CHANGED_DURING_EVALUATION"] = 1
    if not feature_current:
        rejections["FEATURE_LEDGER_HIGH_WATER_CHANGED_DURING_EVALUATION"] = 1
    if not manifest_current:
        rejections["HOLDOUT_MANIFEST_CHANGED_DURING_EVALUATION"] = 1
    if not label_current or not feature_current or not manifest_current:
        examples = []
        label_path_identities = []

    evaluated_order = [
        {
            "sample_id": as_dict(example.trust_row).get("sample_id"),
            "holdout_sample_identity_sha256": as_dict(example.trust_row).get(
                "holdout_sample_identity_sha256"
            ),
            "feature_snapshot_id": example.tensor.feature_snapshot_id,
            "decision_time": example.decision_time,
            "tensor_id": example.tensor.tensor_id,
        }
        for example in examples
    ]
    status = (
        "VERIFIED_CURSOR_FREE_TRUSTED_REPLAY_HOLDOUT_EXAMPLES"
        if examples and not fatal_label_error
        else "BLOCKED_NO_USABLE_HOLDOUT_EXAMPLES"
    )
    if not label_current:
        status = "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_PROOF_STALE"
    elif not feature_current:
        status = "BLOCKED_DURABLE_FEATURE_SNAPSHOT_LEDGER_PROOF_STALE"
    elif not manifest_current:
        status = "BLOCKED_TRUSTED_REPLAY_HOLDOUT_MANIFEST_STALE"
    return {
        **base_status,
        "status": status,
        "examples": examples,
        "selected_holdout_candidates": len(selected),
        "selected_holdout_sample_order_sha256": selected_order_sha256,
        "holdout_sample_identity_hash": _stable_json_sha256(evaluated_order),
        "evaluated_example_order_sha256": _stable_json_sha256(evaluated_order),
        "durable_label_path_identity_sha256": _stable_json_sha256(
            label_path_identities
        ),
        "durable_label_ranges_verified": len(label_path_identities),
        # Backward-compatible proof-current names now mean that a fresh full
        # integrity verification succeeded and every immutable cutoff prefix
        # reproduced exactly; the initial mutable tail proof is never reused.
        "archive_integrity_proof_current_at_completion": label_current,
        "label_archive_fixed_prefixes_current_at_completion": label_current,
        "manifest_label_archive_prefix_current_at_completion": (
            manifest_label_prefix_current
        ),
        "evaluation_label_archive_prefix_current_at_completion": (
            evaluation_label_prefix_current
        ),
        "label_archive_full_integrity_verified_at_completion": (
            label_full_integrity_verified_at_completion
        ),
        "feature_ledger_integrity_proof_current_at_completion": (
            feature_current
        ),
        "feature_ledger_fixed_prefix_current_at_completion": feature_current,
        "feature_ledger_full_integrity_verified_at_completion": (
            feature_full_integrity_verified_at_completion
        ),
        "initial_full_tail_integrity_proof_reused": False,
        "holdout_manifest_current_at_completion": manifest_current,
        "holdout_partition_sample_identity_set_sha256": (
            _sample_identity_set_sha256(candidate_identity_sha256s)
        ),
        "_holdout_sample_identity_sha256s": candidate_identity_sha256s,
        "rows_rejected_by_reason": dict(sorted(rejections.items())),
    }


def _checkpoint_holdout_partition_contract(
    *,
    manifest_payload: Mapping[str, Any],
    checkpoint: CheckpointManifest,
    holdout_sample_identity_sha256s: Iterable[str],
) -> tuple[dict[str, Any] | None, list[str]]:
    partition = as_dict(manifest_payload.get("partition_evidence"))
    evidence = as_dict(checkpoint.checkpoint_evidence)
    reasons: list[str] = []

    def identity_inventory(
        *,
        lane: str,
        kind: str,
        expected_domain: str,
    ) -> tuple[list[str], str | None]:
        prefix = f"{lane.lower()}_{kind.lower()}_identity"
        display = f"{lane}_{kind}_IDENTITY"
        raw = evidence.get(f"{prefix}_sha256s")
        if type(raw) is not list:
            identities: list[str] = []
            reasons.append(f"CHECKPOINT_{display}_INVENTORY_MISSING")
        else:
            identities = [str(value) for value in raw]
        if len(identities) > 250_000:
            reasons.append(f"CHECKPOINT_{display}_INVENTORY_EXCEEDS_BOUND")
        if any(_valid_sha256_text(value) is None for value in identities):
            reasons.append(f"CHECKPOINT_{display}_INVALID")
        if identities != sorted(identities):
            reasons.append(f"CHECKPOINT_{display}S_NOT_SORTED")
        if len(identities) != len(set(identities)):
            reasons.append(f"CHECKPOINT_{display}S_NOT_UNIQUE")
        if evidence.get(f"{prefix}_inventory_complete") is not True:
            reasons.append(f"CHECKPOINT_{display}_INVENTORY_INCOMPLETE")
        if evidence.get(f"{prefix}_domain") != expected_domain:
            reasons.append(f"CHECKPOINT_{display}_DOMAIN_INVALID")
        try:
            identity_set_sha256 = _identity_set_sha256(
                identities,
                domain=expected_domain,
            )
        except ValueError:
            identity_set_sha256 = None
            reasons.append(f"CHECKPOINT_{display}_INVALID")
        if evidence.get(f"{prefix}_set_sha256") != identity_set_sha256:
            reasons.append(f"CHECKPOINT_{display}_SET_MISMATCH")
        count_field = (
            f"{lane.lower()}_sample_count"
            if kind == "SAMPLE"
            else f"{lane.lower()}_feature_identity_count"
        )
        if (
            type(evidence.get(count_field)) is not int
            or evidence[count_field] != len(identities)
        ):
            reasons.append(f"CHECKPOINT_{display}_COUNT_MISMATCH")
        return identities, identity_set_sha256

    training_identities, training_set_sha256 = identity_inventory(
        lane="TRAINING",
        kind="SAMPLE",
        expected_domain=TRAINING_SAMPLE_IDENTITY_DOMAIN,
    )
    validation_identities, validation_set_sha256 = identity_inventory(
        lane="VALIDATION",
        kind="SAMPLE",
        expected_domain=TRAINING_SAMPLE_IDENTITY_DOMAIN,
    )
    training_feature_identities, training_feature_set_sha256 = (
        identity_inventory(
            lane="TRAINING",
            kind="FEATURE",
            expected_domain=HOLDOUT_SAMPLE_IDENTITY_DOMAIN,
        )
    )
    validation_feature_identities, validation_feature_set_sha256 = (
        identity_inventory(
            lane="VALIDATION",
            kind="FEATURE",
            expected_domain=HOLDOUT_SAMPLE_IDENTITY_DOMAIN,
        )
    )
    if len(training_identities) != len(training_feature_identities):
        reasons.append("CHECKPOINT_TRAINING_SAMPLE_FEATURE_COUNT_MISMATCH")
    if len(validation_identities) != len(validation_feature_identities):
        reasons.append("CHECKPOINT_VALIDATION_SAMPLE_FEATURE_COUNT_MISMATCH")
    try:
        raw_holdout_identities = [
            str(value) for value in holdout_sample_identity_sha256s
        ]
        if len(raw_holdout_identities) > 250_000:
            reasons.append("HOLDOUT_SAMPLE_IDENTITY_INVENTORY_EXCEEDS_BOUND")
        if len(raw_holdout_identities) != len(set(raw_holdout_identities)):
            reasons.append("HOLDOUT_SAMPLE_IDENTITIES_NOT_UNIQUE")
        holdout_identities = sorted(raw_holdout_identities)
        holdout_set_sha256 = _sample_identity_set_sha256(holdout_identities)
    except ValueError:
        holdout_set_sha256 = None
        holdout_identities = []
        reasons.append("CHECKPOINT_OR_HOLDOUT_SAMPLE_IDENTITY_INVALID")
    try:
        expected_partition_digest = training_partition_digest(
            list(checkpoint.consumed_ppo_update_keys)
        )
    except ValueError:
        expected_partition_digest = None
        reasons.append("CHECKPOINT_TRAINING_PARTITION_UPDATE_KEYS_INVALID")
    if checkpoint.training_partition_digest != expected_partition_digest:
        reasons.append("CHECKPOINT_TRAINING_PARTITION_DIGEST_INVALID")
    if evidence.get("training_partition_digest") != (
        checkpoint.training_partition_digest
    ):
        reasons.append("CHECKPOINT_EVIDENCE_TRAINING_PARTITION_DIGEST_MISMATCH")
    if evidence.get("optional_missing_evidence_semantics") != (
        OPTIONAL_MISSING_EVIDENCE_SEMANTICS
    ):
        reasons.append("CHECKPOINT_OPTIONAL_MISSING_SEMANTICS_INVALID")
    if evidence.get("optional_missing_typed_negative_receipts_verified") is not False:
        reasons.append("CHECKPOINT_OPTIONAL_TYPED_NEGATIVE_CLAIM_INVALID")
    if evidence.get("optional_missing_observed_zero_claimed") is not False:
        reasons.append("CHECKPOINT_OPTIONAL_ZERO_CLAIM_INVALID")
    manifest_bindings = {
        "training_partition_digest": checkpoint.training_partition_digest,
        "training_sample_identity_set_sha256": training_set_sha256,
        "training_sample_count": len(training_identities),
        "validation_sample_identity_set_sha256": validation_set_sha256,
        "validation_sample_count": len(validation_identities),
        "training_feature_identity_set_sha256": training_feature_set_sha256,
        "training_feature_identity_count": len(training_feature_identities),
        "validation_feature_identity_set_sha256": validation_feature_set_sha256,
        "validation_feature_identity_count": len(validation_feature_identities),
        "holdout_sample_identity_set_sha256": holdout_set_sha256,
        "holdout_sample_count": len(holdout_identities),
    }
    if any(
        partition.get(field) != expected
        for field, expected in manifest_bindings.items()
    ):
        reasons.append("MANIFEST_CHECKPOINT_PARTITION_BINDING_MISMATCH")
    if set(training_feature_identities) & set(validation_feature_identities):
        reasons.append("CHECKPOINT_TRAINING_VALIDATION_FEATURE_IDENTITY_OVERLAP")
    if set(training_feature_identities) & set(holdout_identities):
        reasons.append("CHECKPOINT_TRAINING_HOLDOUT_SAMPLE_OVERLAP")
    if set(validation_feature_identities) & set(holdout_identities):
        reasons.append("CHECKPOINT_VALIDATION_HOLDOUT_SAMPLE_OVERLAP")
    if partition.get("training_validation_disjoint") is not True:
        reasons.append("MANIFEST_TRAINING_VALIDATION_DISJOINTNESS_NOT_TRUE")
    if partition.get("training_holdout_disjoint") is not True:
        reasons.append("MANIFEST_TRAINING_HOLDOUT_DISJOINTNESS_NOT_TRUE")
    if partition.get("validation_holdout_disjoint") is not True:
        reasons.append("MANIFEST_VALIDATION_HOLDOUT_DISJOINTNESS_NOT_TRUE")
    checkpoint_binding = as_dict(manifest_payload.get("checkpoint_binding"))
    exact_checkpoint_bindings = {
        "checkpoint_id": checkpoint.checkpoint_id,
        "checkpoint_evidence_digest": checkpoint.checkpoint_evidence_digest,
        "training_partition_digest": checkpoint.training_partition_digest,
        "training_sample_identity_set_sha256": training_set_sha256,
        "validation_sample_identity_set_sha256": validation_set_sha256,
        "training_feature_identity_set_sha256": training_feature_set_sha256,
        "validation_feature_identity_set_sha256": validation_feature_set_sha256,
    }
    if any(
        checkpoint_binding.get(field) != expected
        for field, expected in exact_checkpoint_bindings.items()
    ):
        reasons.append("MANIFEST_CHECKPOINT_EXACT_BINDING_MISMATCH")
    if reasons:
        return None, sorted(set(reasons))
    proof = {
        "schema_version": "checkpoint_holdout_disjointness_proof_v1",
        "checkpoint_id": checkpoint.checkpoint_id,
        "checkpoint_evidence_digest": checkpoint.checkpoint_evidence_digest,
        **manifest_bindings,
        "training_sample_identity_inventory_complete": True,
        "validation_sample_identity_inventory_complete": True,
        "training_feature_identity_inventory_complete": True,
        "validation_feature_identity_inventory_complete": True,
        "training_validation_intersection_count": 0,
        "training_holdout_intersection_count": 0,
        "validation_holdout_intersection_count": 0,
        "training_validation_disjoint_verified": True,
        "training_holdout_disjoint_verified": True,
        "validation_holdout_disjoint_verified": True,
        "checkpoint_binding_verified": True,
    }
    return {**proof, "proof_sha256": _stable_json_sha256(proof)}, []


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
    examples = [
        example
        for example in as_list(loaded.get("examples"))
        if isinstance(example, TrainingExample)
    ]
    loaded_evidence = {
        key: loaded.get(key)
        for key in (
            "required_label_source",
            "immutable_feature_snapshot_archive_used",
            "durable_feature_snapshot_ledger_used",
            "legacy_v1_feature_snapshot_admitted",
            "same_timeframe_label_fallback_used",
            "mutable_redis_history_used_for_historical_labels",
            "network_label_fallback_used",
            "production_replay_cursor_read",
            "production_replay_cursor_written",
            "cursor_free_evaluation",
            "observation_policy",
            "sampling_policy",
            "training_observed_at",
            "feature_observation_cutoff",
            "feature_strict_prior_observation_cutoff",
            "label_evaluation_cutoff",
            "label_strict_prior_evaluation_cutoff",
            "feature_and_label_observation_clocks_distinguished",
            "holdout_manifest_file_sha256",
            "holdout_manifest_payload_sha256",
            "holdout_window_observation_sha256",
            "holdout_manifest_current_at_completion",
            "feature_manifest_scan_identity_sha256",
            "feature_manifest_scanned_prefix_sha256",
            "feature_manifest_scan_truncated",
            "feature_ledger_integrity_checkpoint",
            "feature_ledger_integrity_checkpoint_sha256",
            "feature_ledger_integrity_proof_current_at_completion",
            "feature_ledger_fixed_prefix_current_at_completion",
            "feature_ledger_full_integrity_verified_at_completion",
            "label_archive_integrity_checkpoint",
            "label_archive_integrity_checkpoint_sha256",
            "manifest_label_archive_high_water",
            "manifest_label_archive_high_water_sha256",
            "evaluation_label_archive_high_water",
            "evaluation_label_archive_high_water_sha256",
            "manifest_label_prefix_reproduced_at_feature_cutoff",
            "evaluation_label_prefix_frozen_at_evaluation_start",
            "label_path_full_tail_integrity_proof_reused",
            "archive_integrity_proof_current_at_completion",
            "label_archive_fixed_prefixes_current_at_completion",
            "manifest_label_archive_prefix_current_at_completion",
            "evaluation_label_archive_prefix_current_at_completion",
            "label_archive_full_integrity_verified_at_completion",
            "initial_full_tail_integrity_proof_reused",
            "selected_holdout_sample_order_sha256",
            "evaluated_example_order_sha256",
            "holdout_sample_identity_hash",
            "holdout_partition_sample_identity_set_sha256",
            "durable_label_path_identity_sha256",
            "durable_label_ranges_verified",
            "holdout_candidates_found",
            "selected_holdout_candidates",
        )
        if key in loaded
    }
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
            "snapshots_scanned": int(
                finite_float(loaded.get("snapshots_scanned")) or 0
            ),
            "required_label_source": loaded.get("required_label_source"),
            "same_timeframe_label_fallback_used": loaded.get(
                "same_timeframe_label_fallback_used"
            )
            is True,
            "mutable_redis_history_used_for_historical_labels": loaded.get(
                "mutable_redis_history_used_for_historical_labels"
            )
            is True,
            **loaded_evidence,
            "rows_rejected_by_reason": as_dict(loaded.get("rows_rejected_by_reason")),
            "reason": (
                "no PIT-safe trusted replay holdout examples could be "
                "materialized from a durable indexed finalized-5m label source"
            ),
        }
    input_dim = len(examples[0].tensor.model_vector)
    try:
        model = V2HybridPolicyModel(input_dim=input_dim)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_CHECKPOINT_MODEL_INITIALIZATION_FAILED",
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "manifest_holdout_rows": manifest_rows,
            "evaluated_rows": 0,
            "holdout_source_evidence": loaded_evidence,
            "reason": f"checkpoint model initialization failed closed: {type(exc).__name__}",
        }
    checkpoint_manager = V2HybridCheckpointManager(Path(model_dir))
    try:
        serving_manifests = checkpoint_manager.manifests(
            input_dim=input_dim,
            model_id=model.model_id,
            allowed_lineage_kinds=frozenset({VERIFIED_SERVING_LINEAGE}),
            require_weight_blob=True,
            verify_lineage_artifacts=False,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_CHECKPOINT_MANIFEST_SCAN_INVALID",
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "manifest_holdout_rows": manifest_rows,
            "evaluated_rows": 0,
            "holdout_source_evidence": loaded_evidence,
            "reason": f"serving checkpoint manifest scan failed closed: {type(exc).__name__}",
        }
    checkpoint_binding = as_dict(manifest.get("checkpoint_binding"))
    bound_checkpoint_id = checkpoint_binding.get("checkpoint_id")
    manifest_checkpoint = next(
        (
            candidate
            for candidate in serving_manifests
            if candidate.checkpoint_id == bound_checkpoint_id
        ),
        None,
    )
    if manifest_checkpoint is None:
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_NO_VERIFIED_SERVING_CHECKPOINT_WEIGHT_BLOB",
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "manifest_holdout_rows": manifest_rows,
            "evaluated_rows": 0,
            "holdout_source_evidence": loaded_evidence,
            "reason": (
                "the durable holdout manifest's exact checkpoint binding has "
                "no compatible verified-serving checkpoint with a safe npz "
                "weight blob"
            ),
        }
    if manifest_checkpoint.lineage_kind != VERIFIED_SERVING_LINEAGE:
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_CHECKPOINT_LINEAGE_INVALID",
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "manifest_holdout_rows": manifest_rows,
            "evaluated_rows": 0,
            "checkpoint_id": manifest_checkpoint.checkpoint_id,
            "holdout_source_evidence": loaded_evidence,
            "reason": "holdout evaluation requires VERIFIED_SERVING_POLICY lineage",
        }
    partition_proof, partition_reasons = _checkpoint_holdout_partition_contract(
        manifest_payload={
            str(key): value
            for key, value in manifest.items()
            if str(key) != "manifest_path"
        },
        checkpoint=manifest_checkpoint,
        holdout_sample_identity_sha256s=as_list(
            loaded.get("_holdout_sample_identity_sha256s")
        ),
    )
    if partition_proof is None:
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_CHECKPOINT_HOLDOUT_PARTITION_NOT_DISJOINT",
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "manifest_holdout_rows": manifest_rows,
            "evaluated_rows": 0,
            "checkpoint_id": manifest_checkpoint.checkpoint_id,
            "holdout_source_evidence": loaded_evidence,
            "checkpoint_holdout_partition_rejection_reasons": (
                partition_reasons
            ),
            "reason": (
                "checkpoint evidence did not bind a complete training-sample "
                "inventory disjoint from the authenticated holdout partition"
            ),
        }
    try:
        artifact_verification = checkpoint_manager.verify_manifest_artifact(
            manifest_checkpoint
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_CHECKPOINT_ARTIFACT_VERIFICATION_ERROR",
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "manifest_holdout_rows": manifest_rows,
            "evaluated_rows": 0,
            "checkpoint_id": manifest_checkpoint.checkpoint_id,
            "holdout_source_evidence": loaded_evidence,
            "reason": (
                "serving checkpoint artifact verification failed closed: "
                f"{type(exc).__name__}"
            ),
        }
    if (
        not isinstance(artifact_verification, Mapping)
        or artifact_verification.get("checkpoint_artifact_verified") is not True
    ):
        artifact_verification = as_dict(artifact_verification)
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_CHECKPOINT_ARTIFACT_VERIFICATION_FAILED",
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "manifest_holdout_rows": manifest_rows,
            "evaluated_rows": 0,
            "checkpoint_id": manifest_checkpoint.checkpoint_id,
            "holdout_source_evidence": loaded_evidence,
            "checkpoint_artifact_rejection_reasons": list(
                artifact_verification.get(
                    "artifact_verification_rejection_reasons", ()
                )
            ),
            "reason": "selected serving checkpoint artifact did not pass non-mutating verification",
        }
    try:
        load_result = checkpoint_manager.load_latest_weights(
            model,
            allowed_lineage_kinds=frozenset({VERIFIED_SERVING_LINEAGE}),
            expected_checkpoint_id=manifest_checkpoint.checkpoint_id,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_CHECKPOINT_WEIGHT_BLOB_LOAD_FAILED",
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "checkpoint_id": manifest_checkpoint.checkpoint_id,
            "holdout_source_evidence": loaded_evidence,
            "reason": f"checkpoint load failed: {type(exc).__name__}",
        }
    if not isinstance(load_result, Mapping):
        load_result = {}
    if (
        load_result.get("checkpoint_id") != manifest_checkpoint.checkpoint_id
        or load_result.get("latest_checkpoint_loadable") is not True
        or load_result.get("model_state_restored") is not True
    ):
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_CHECKPOINT_WEIGHT_BLOB_LOAD_FAILED",
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "checkpoint_id": manifest_checkpoint.checkpoint_id,
            "holdout_source_evidence": loaded_evidence,
            "checkpoint_load_status": load_result.get("load_status"),
            "reason": "checkpoint manager did not restore the selected serving checkpoint",
        }
    try:
        serving_semantics_valid, serving_semantic_reasons = (
            _verified_serving_checkpoint_evidence(
                load_result,
                expected_checkpoint_id=manifest_checkpoint.checkpoint_id,
            )
        )
    except (RuntimeError, TypeError, ValueError):
        serving_semantics_valid = False
        serving_semantic_reasons = (
            "serving_checkpoint_semantic_verifier_failed_closed",
        )
    if not serving_semantics_valid:
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_CHECKPOINT_SERVING_SEMANTICS_INVALID",
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "manifest_holdout_rows": manifest_rows,
            "evaluated_rows": 0,
            "checkpoint_id": manifest_checkpoint.checkpoint_id,
            "holdout_source_evidence": loaded_evidence,
            "checkpoint_serving_semantic_rejection_reasons": list(
                serving_semantic_reasons
            ),
            "reason": "selected checkpoint is not a semantically verified serving policy",
        }
    weight_path = Path(str(load_result.get("resolved_weight_file_path") or ""))
    if not weight_path.is_absolute() or not weight_path.is_file():
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_CHECKPOINT_WEIGHT_PATH_INVALID",
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "manifest_holdout_rows": manifest_rows,
            "evaluated_rows": 0,
            "checkpoint_id": manifest_checkpoint.checkpoint_id,
            "holdout_source_evidence": loaded_evidence,
            "reason": "verified checkpoint manager did not resolve an extant absolute weight path",
        }
    try:
        resolved_weight_file_sha256 = _sha256_path(weight_path)
    except OSError:
        resolved_weight_file_sha256 = None
    checkpoint_weight_identities = {
        "manifest_weight_file_sha256": str(
            getattr(manifest_checkpoint, "weight_file_sha256", "") or ""
        ),
        "artifact_weight_file_sha256": str(
            artifact_verification.get("weight_file_sha256") or ""
        ),
        "artifact_observed_weight_file_sha256": str(
            artifact_verification.get("observed_weight_file_sha256") or ""
        ),
        "loaded_weight_file_sha256": str(
            load_result.get("weight_file_sha256") or ""
        ),
        "resolved_weight_file_sha256": str(
            resolved_weight_file_sha256 or ""
        ),
    }
    if (
        any(
            len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in checkpoint_weight_identities.values()
        )
        or len(set(checkpoint_weight_identities.values())) != 1
    ):
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "BLOCKED_CHECKPOINT_WEIGHT_IDENTITY_MISMATCH",
            "confidence_outcome_join_available": False,
            "holdout_window": as_dict(manifest.get("holdout_window")),
            "manifest_path": manifest.get("manifest_path"),
            "manifest_holdout_rows": manifest_rows,
            "evaluated_rows": 0,
            "checkpoint_id": manifest_checkpoint.checkpoint_id,
            "checkpoint_weight_identities": checkpoint_weight_identities,
            "holdout_source_evidence": loaded_evidence,
            "reason": (
                "verified-serving manifest, non-mutating verification, loaded "
                "artifact, and resolved weight bytes did not share one SHA-256"
            ),
        }
    checkpoint_weight_identity_sha256 = next(
        iter(checkpoint_weight_identities.values())
    )

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
        outcome = _selected_action_outcome(forward.selected_action, trust_row)
        selected_direction = str(forward.selected_action or "").strip().lower()
        target_direction = _trusted_replay_holdout_target_action(trust_row)
        expected_after_cost = _expected_after_cost_bps(
            forward.expected_move_bps,
            trust_row,
        )
        if confidence is not None and 0.0 <= confidence <= 1.0 and outcome is not None:
            calibration_rows.append({"confidence": confidence, "outcome": outcome})
        elif selected_direction == "hold" or target_direction == "hold":
            rows_rejected["hold_excluded_from_directional_confidence_calibration"] = (
                rows_rejected.get(
                    "hold_excluded_from_directional_confidence_calibration",
                    0,
                )
                + 1
            )
        else:
            rows_rejected["missing_confidence_or_selected_action_outcome"] = rows_rejected.get(
                "missing_confidence_or_selected_action_outcome", 0
            ) + 1
        if expected_after_cost is not None:
            expected_move_rows.append(
                {"expected": expected_after_cost, "realized": realized}
            )
        else:
            rows_rejected["adaptive_cost_label_contract_invalid"] = (
                rows_rejected.get("adaptive_cost_label_contract_invalid", 0) + 1
            )
        hit = _directional_accuracy_hit(forward.selected_action, trust_row)
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
    evaluation_evidence_material = {
        "contract_version": "trusted_replay_holdout_evaluation_evidence_v2",
        "holdout_source_evidence": loaded_evidence,
        "checkpoint_id": manifest_checkpoint.checkpoint_id,
        "checkpoint_weight_identity_sha256": checkpoint_weight_identity_sha256,
        "checkpoint_parameter_fingerprint": load_result.get(
            "model_parameter_fingerprint"
        ),
        "checkpoint_evidence_digest": load_result.get(
            "checkpoint_evidence_digest"
        ),
        "checkpoint_holdout_partition_proof": partition_proof,
        "evaluated_rows": len(examples),
        "calibration_rows_sha256": _stable_json_sha256(calibration_rows),
        "expected_move_rows_sha256": _stable_json_sha256(expected_move_rows),
        "rows_rejected_by_reason": dict(sorted(rows_rejected.items())),
    }
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
        **loaded_evidence,
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
        "checkpoint_hash": checkpoint_weight_identity_sha256,
        "checkpoint_weight_identity_sha256": checkpoint_weight_identity_sha256,
        "checkpoint_weight_identities": checkpoint_weight_identities,
        "checkpoint_parameter_fingerprint": load_result.get(
            "model_parameter_fingerprint"
        ),
        "checkpoint_holdout_partition_proof": partition_proof,
        "checkpoint_evidence_digest": load_result.get(
            "checkpoint_evidence_digest"
        ),
        "checkpoint_verified_serving_semantics": True,
        "checkpoint_weight_blob_loaded": bool(load_result.get("model_state_restored")),
        "device": model.device,
        "cuda_active": model.cuda_active,
        "cache_hit": bool(loaded.get("cache_hit")),
        "rows_rejected_by_reason": dict(sorted(rows_rejected.items())),
        "evaluation_evidence_sha256": _stable_json_sha256(
            evaluation_evidence_material
        ),
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
            "status": "BLOCKED_TRUSTED_HOLDOUT_CALIBRATION_CADENCE_DEFERRED_REVALIDATION_REQUIRED",
            "confidence_outcome_join_available": False,
            "trusted_holdout_rows": 0,
            "evaluated_rows": 0,
            "calibration_source": None,
            "checkpoint_hash": None,
            "checkpoint_id": None,
            "rows_rejected_by_reason": {
                "PRIOR_HOLDOUT_CALIBRATION_NOT_REVALIDATED": 1
            },
            "future_labels_used_as_features": None,
            "uses_expected_move_as_realized_reward": None,
            "prior_published_status": previous_status or None,
            "prior_calibration_not_actuating": True,
            "holdout_calibration_reuse_contract": (
                "DISABLED_UNLESS_ALL_CAUSAL_IDENTITIES_ARE_REVALIDATED"
            ),
            "required_reuse_identity_bindings": [
                "current_full_label_archive_integrity_checkpoint",
                "holdout_manifest_and_window_sha256",
                "feature_archive_bounded_scan_identity_sha256",
                "deterministic_selected_sample_order_sha256",
                "fixed_observation_policy_and_cutoff",
                "verified_serving_checkpoint_weight_sha256",
            ],
            "reason": (
                "cadence deferred a fresh evaluation; prior metrics are not "
                "reused without exact causal-identity revalidation"
            ),
            "_calibration_rows": [],
            "_expected_move_rows": [],
        }
        reused_holdout_calibration = False
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
    public_holdout_active = holdout_active
    calibration_rows = holdout_calibration_rows if holdout_active else list(feedback_metrics["calibration_rows"])
    ece, buckets = _expected_calibration_error(calibration_rows)
    brier = _brier_score(calibration_rows)
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
    if holdout_active:
        calibration_status = "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION"
        calibration_reason = None
    elif confidence_join_available:
        calibration_status = "ACTIVE_TRUSTED_CONFIDENCE_OUTCOME_CALIBRATION"
        calibration_reason = (
            "trusted confidence/outcome rows are available, but no untouched holdout rows are flagged"
        )
    elif not run_holdout_calibration:
        calibration_status = str(holdout_artifact["status"])
        calibration_reason = str(holdout_artifact["reason"])
    else:
        calibration_status = "BLOCKED_NO_CONFIDENCE_OUTCOME_JOIN_FOR_TRUSTED_HOLDOUT"
        calibration_reason = "paper outcome labels currently omit confidence/expected-move prediction fields"
    last_holdout_evaluation_generated_utc = (
        generated_utc
        if run_holdout_calibration
        else previous_calibration.get("last_holdout_evaluation_generated_utc")
        or previous_calibration.get("generated_utc")
    )
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
            "holdout_calibration_reuse_contract": (
                "DISABLED_UNLESS_ALL_CAUSAL_IDENTITIES_ARE_REVALIDATED"
            ),
            "last_holdout_evaluation_generated_utc": (
                last_holdout_evaluation_generated_utc
            ),
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
    previous_time = parse_runtime_time(
        previous.get("last_holdout_evaluation_generated_utc")
        or (
            previous.get("generated_utc")
            if str(previous.get("status") or "")
            == "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION"
            else None
        )
    )
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
        realized = finite_float(
            _first_present_value(
                row.get("realized_net_pnl_bps"),
                row.get("realized_pnl_bps"),
            )
        )
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


_CHECKPOINT_CAUSAL_LEDGER_NAME = ".checkpoint-causal-order.jsonl"
_CHECKPOINT_CAUSAL_LOCK_NAME = ".checkpoint-causal-order.lock"


@dataclass(frozen=True)
class _CheckpointRetentionGroup:
    manager: V2HybridCheckpointManager
    manifest: CheckpointManifest
    manifest_path: Path
    weight_path: Path
    raw_manifest: dict[str, Any]
    verification: dict[str, Any]


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_hex(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    )


def _checkpoint_retention_order_key(
    group: _CheckpointRetentionGroup,
) -> tuple[int, int, datetime, str]:
    generation = group.manifest.checkpoint_generation
    if generation > 0:
        return (
            1,
            generation,
            datetime.min.replace(tzinfo=timezone.utc),
            group.manifest.checkpoint_id,
        )
    generated = parse_runtime_time(group.manifest.generated_utc)
    if generated is None:
        raise ValueError("legacy_checkpoint_generated_utc_invalid")
    return (0, 0, generated, group.manifest.checkpoint_id)


def _ppo_retention_ledger_state(ledger_path: Path) -> dict[str, Any]:
    """Read and independently verify terminal PPO checkpoint bindings."""

    sibling_files = tuple(
        path
        for path in (
            ledger_path,
            Path(f"{ledger_path}-wal"),
            Path(f"{ledger_path}-shm"),
        )
        if path.is_file()
    )
    if not ledger_path.exists():
        reasons = (
            ["PPO_LEDGER_PRIMARY_MISSING_WITH_SIDECAR"] if sibling_files else []
        )
        return {
            "integrity_verified": not reasons,
            "integrity_rejection_reasons": reasons,
            "pending_claims": set(),
            "attempt_rows": [],
            "ledger_files": sibling_files,
        }
    reasons: list[str] = []
    attempts: list[dict[str, Any]] = []
    pending_claims: set[str] = set()
    try:
        connection = sqlite3.connect(
            f"file:{ledger_path.resolve()}?mode=ro",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or str(quick_check[0]).lower() != "ok":
                reasons.append("PPO_LEDGER_SQLITE_QUICK_CHECK_FAILED")
            table_names = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            required_tables = {"metadata", "ppo_attempts", "ppo_claims"}
            if not required_tables.issubset(table_names):
                reasons.append("PPO_LEDGER_REQUIRED_TABLE_MISSING")
            else:
                metadata = {
                    str(row[0]): str(row[1])
                    for row in connection.execute("SELECT key, value FROM metadata")
                }
                attempts = [
                    dict(row)
                    for row in connection.execute(
                        "SELECT * FROM ppo_attempts ORDER BY sequence ASC"
                    )
                ]
                pending_claims = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT update_key FROM ppo_claims"
                    )
                }
                if (
                    metadata.get("schema_version")
                    != PPO_CONSUMPTION_LEDGER_SCHEMA_VERSION
                ):
                    reasons.append("PPO_LEDGER_SCHEMA_VERSION_MISMATCH")
                try:
                    row_count = int(metadata.get("row_count", ""))
                except (TypeError, ValueError, OverflowError):
                    row_count = -1
                if row_count != len(attempts):
                    reasons.append("PPO_LEDGER_ROW_COUNT_MISMATCH")
                previous_chain_hash = "0" * 64
                semantic_fields = (
                    "sequence",
                    "update_key",
                    "receipt_hash",
                    "finalized_outcome_digest",
                    "parent_policy_fingerprint",
                    "child_policy_fingerprint",
                    "disposition",
                    "checkpoint_id",
                    "checkpoint_path",
                    "checkpoint_sha256",
                    "training_partition_digest",
                    "recorded_utc",
                    "previous_chain_hash",
                )
                for expected_sequence, row in enumerate(attempts, start=1):
                    if row.get("sequence") != expected_sequence:
                        reasons.append("PPO_LEDGER_SEQUENCE_GAP")
                        break
                    if row.get("previous_chain_hash") != previous_chain_hash:
                        reasons.append("PPO_LEDGER_PREVIOUS_CHAIN_MISMATCH")
                        break
                    semantic = {field: row.get(field) for field in semantic_fields}
                    try:
                        observed_chain_hash = hashlib.sha256(
                            json.dumps(
                                semantic,
                                sort_keys=True,
                                separators=(",", ":"),
                                ensure_ascii=True,
                                allow_nan=False,
                            ).encode("utf-8")
                        ).hexdigest()
                    except (TypeError, ValueError, OverflowError):
                        observed_chain_hash = ""
                    if row.get("chain_hash") != observed_chain_hash:
                        reasons.append("PPO_LEDGER_CHAIN_HASH_MISMATCH")
                        break
                    previous_chain_hash = observed_chain_hash
                if metadata.get("chain_tip") != previous_chain_hash:
                    reasons.append("PPO_LEDGER_CHAIN_TIP_MISMATCH")
                if any(not _sha256_hex(update_key) for update_key in pending_claims):
                    reasons.append("PPO_LEDGER_PENDING_UPDATE_KEY_INVALID")
        finally:
            connection.close()
    except (OSError, sqlite3.DatabaseError):
        reasons.append("PPO_LEDGER_UNREADABLE")
    return {
        "integrity_verified": not reasons,
        "integrity_rejection_reasons": sorted(set(reasons)),
        "pending_claims": pending_claims,
        "attempt_rows": attempts,
        "ledger_files": sibling_files,
    }


def checkpoint_retention_status(
    *,
    paths: PersistentTrainerPaths,
    latest_checkpoint_id: str | None,
    best_checkpoint_id: str | None = None,
    rollover_limit_gb: int = 300,
    apply_rollover: bool = True,
) -> dict[str, Any]:
    activation_binding, activation_status = _authoritative_serving_activation(
        paths.repo_root
    )
    checkpoint_dir = paths.model_dir
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    candidate_dir = checkpoint_dir / "non_serving_training_candidates"
    rejected_dir = checkpoint_dir / "rejected_optimizer_attempts"
    store_dirs = (checkpoint_dir, candidate_dir, rejected_dir)
    for store_dir in store_dirs:
        store_dir.mkdir(parents=True, exist_ok=True)
    managers = tuple(
        (store_dir, V2HybridCheckpointManager(store_dir))
        for store_dir in store_dirs
    )
    scan_rejection_reasons: list[str] = []

    # Let the checkpoint owner recover only its narrowly-proven torn JSONL tail
    # before retention takes the global writer lock. Every other causal damage
    # remains a hard, no-deletion blocker.
    for store_dir, manager in managers:
        try:
            manager.manifests()
        except (OSError, RuntimeError, TypeError, ValueError):
            scan_rejection_reasons.append(
                f"CHECKPOINT_PREFLIGHT_SCAN_INVALID:{store_dir.name}"
            )

    lock_path = checkpoint_dir / _CHECKPOINT_CAUSAL_LOCK_NAME
    causal_ledger_path = checkpoint_dir / _CHECKPOINT_CAUSAL_LEDGER_NAME
    groups: list[_CheckpointRetentionGroup] = []
    observed_artifacts: list[Path] = []
    incomplete_artifacts: set[str] = set()
    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            for store_dir in store_dirs:
                staging_root = store_dir / ".checkpoint_retention_delete_staging"
                if staging_root.exists():
                    scan_rejection_reasons.append(
                        f"CHECKPOINT_DELETE_STAGING_NOT_EMPTY:{store_dir.name}"
                    )
                for path in store_dir.glob("v2_hybrid_ckpt_*"):
                    if path.is_symlink() or not path.is_file():
                        scan_rejection_reasons.append(
                            f"CHECKPOINT_ARTIFACT_TYPE_INVALID:{path.name}"
                        )
                        continue
                    if not (
                        path.name.endswith(".json")
                        or path.name.endswith(".weights.npz")
                    ):
                        scan_rejection_reasons.append(
                            f"CHECKPOINT_ARTIFACT_SUFFIX_INVALID:{path.name}"
                        )
                        continue
                    observed_artifacts.append(path)

            if not scan_rejection_reasons:
                seen_checkpoint_ids: set[str] = set()
                expected_artifacts: set[Path] = set()
                for store_dir, manager in managers:
                    try:
                        manifests = manager.manifests()
                    except (OSError, RuntimeError, TypeError, ValueError):
                        scan_rejection_reasons.append(
                            f"CHECKPOINT_MANIFEST_SCAN_INVALID:{store_dir.name}"
                        )
                        continue
                    for checkpoint_manifest in manifests:
                        checkpoint_id = checkpoint_manifest.checkpoint_id
                        if checkpoint_id in seen_checkpoint_ids:
                            scan_rejection_reasons.append(
                                f"CHECKPOINT_ID_AMBIGUOUS:{checkpoint_id}"
                            )
                            continue
                        seen_checkpoint_ids.add(checkpoint_id)
                        manifest_path = store_dir / f"{checkpoint_id}.json"
                        weight_path = store_dir / f"{checkpoint_id}.weights.npz"
                        expected_artifacts.update((manifest_path, weight_path))
                        if not manifest_path.is_file() or not weight_path.is_file():
                            scan_rejection_reasons.append(
                                f"CHECKPOINT_PAIR_INCOMPLETE:{checkpoint_id}"
                            )
                            for path in (manifest_path, weight_path):
                                if path.exists():
                                    incomplete_artifacts.add(
                                        str(path.relative_to(checkpoint_dir))
                                    )
                            continue
                        try:
                            raw_manifest = json.loads(
                                manifest_path.read_text(encoding="utf-8")
                            )
                            verification = manager.verify_manifest_artifact(
                                checkpoint_manifest
                            )
                        except (OSError, RuntimeError, TypeError, ValueError):
                            scan_rejection_reasons.append(
                                f"CHECKPOINT_ARTIFACT_VERIFY_ERROR:{checkpoint_id}"
                            )
                            continue
                        if not isinstance(raw_manifest, dict):
                            scan_rejection_reasons.append(
                                f"CHECKPOINT_MANIFEST_NOT_OBJECT:{checkpoint_id}"
                            )
                            continue
                        if verification.get("checkpoint_artifact_verified") is not True:
                            scan_rejection_reasons.append(
                                f"CHECKPOINT_ARTIFACT_INVALID:{checkpoint_id}"
                            )
                            continue
                        resolved_weight = verification.get(
                            "resolved_weight_file_path"
                        )
                        try:
                            resolved_matches = (
                                Path(str(resolved_weight)).resolve(strict=True)
                                == weight_path.resolve(strict=True)
                            )
                        except OSError:
                            resolved_matches = False
                        if not resolved_matches:
                            scan_rejection_reasons.append(
                                f"CHECKPOINT_WEIGHT_PATH_INVALID:{checkpoint_id}"
                            )
                            continue
                        try:
                            group = _CheckpointRetentionGroup(
                                manager=manager,
                                manifest=checkpoint_manifest,
                                manifest_path=manifest_path,
                                weight_path=weight_path,
                                raw_manifest=raw_manifest,
                                verification=dict(verification),
                            )
                            _checkpoint_retention_order_key(group)
                        except (TypeError, ValueError, OverflowError):
                            scan_rejection_reasons.append(
                                f"CHECKPOINT_CAUSAL_ORDER_INVALID:{checkpoint_id}"
                            )
                            continue
                        groups.append(group)
                unexpected = set(observed_artifacts) - expected_artifacts
                if unexpected:
                    incomplete_artifacts.update(
                        str(path.relative_to(checkpoint_dir))
                        for path in unexpected
                    )
                    scan_rejection_reasons.append(
                        "CHECKPOINT_ORPHAN_ARTIFACT_PRESENT"
                    )

            ledger_path = candidate_dir / "ppo_consumption.sqlite3"
            ledger_state = _ppo_retention_ledger_state(ledger_path)
            if ledger_state.get("integrity_verified") is not True:
                scan_rejection_reasons.extend(
                    str(reason)
                    for reason in ledger_state.get(
                        "integrity_rejection_reasons", []
                    )
                )
            pending_claims = set(ledger_state.get("pending_claims") or ())
            attempt_rows = list(ledger_state.get("attempt_rows") or ())
            ledger_files = list(ledger_state.get("ledger_files") or ())
            group_by_id = {
                group.manifest.checkpoint_id: group for group in groups
            }
            terminal_checkpoint_groups: set[str] = set()
            for row in attempt_rows:
                checkpoint_id_value = row.get("checkpoint_id")
                checkpoint_path_value = row.get("checkpoint_path")
                checkpoint_sha_value = row.get("checkpoint_sha256")
                bindings = (
                    checkpoint_id_value,
                    checkpoint_path_value,
                    checkpoint_sha_value,
                )
                if all(value in (None, "") for value in bindings):
                    continue
                if any(value in (None, "") for value in bindings):
                    scan_rejection_reasons.append(
                        "PPO_TERMINAL_CHECKPOINT_BINDING_PARTIAL"
                    )
                    continue
                checkpoint_id = str(checkpoint_id_value)
                checkpoint_sha = str(checkpoint_sha_value)
                group = group_by_id.get(checkpoint_id)
                if (
                    Path(checkpoint_id).name != checkpoint_id
                    or group is None
                    or not _sha256_hex(checkpoint_sha)
                ):
                    scan_rejection_reasons.append(
                        f"PPO_TERMINAL_CHECKPOINT_IDENTITY_INVALID:{checkpoint_id}"
                    )
                    continue
                try:
                    ledger_weight_path = Path(
                        str(checkpoint_path_value)
                    ).resolve(strict=True)
                    expected_weight_path = group.weight_path.resolve(strict=True)
                    observed_sha = _sha256_path(expected_weight_path)
                except OSError:
                    scan_rejection_reasons.append(
                        f"PPO_TERMINAL_CHECKPOINT_ARTIFACT_UNREADABLE:{checkpoint_id}"
                    )
                    continue
                if (
                    ledger_weight_path != expected_weight_path
                    or checkpoint_sha != observed_sha
                    or checkpoint_sha != group.manifest.weight_file_sha256
                    or row.get("child_policy_fingerprint")
                    != group.manifest.model_parameter_fingerprint
                ):
                    scan_rejection_reasons.append(
                        f"PPO_TERMINAL_CHECKPOINT_BINDING_MISMATCH:{checkpoint_id}"
                    )
                    continue
                terminal_checkpoint_groups.add(checkpoint_id)

            children_by_parent: dict[str, set[str]] = {}
            for group in groups:
                parent_id = group.manifest.parent_checkpoint_id
                if parent_id is None:
                    continue
                if parent_id not in group_by_id:
                    scan_rejection_reasons.append(
                        f"CHECKPOINT_PARENT_MISSING:{group.manifest.checkpoint_id}"
                    )
                    continue
                children_by_parent.setdefault(parent_id, set()).add(
                    group.manifest.checkpoint_id
                )

            ordered_groups = sorted(groups, key=_checkpoint_retention_order_key)
            serving_groups = [
                group
                for group in ordered_groups
                if group.manifest_path.parent == checkpoint_dir
                and group.manifest.lineage_kind == "VERIFIED_SERVING_POLICY"
            ]
            candidate_groups = [
                group
                for group in ordered_groups
                if group.manifest_path.parent == candidate_dir
                and group.manifest.lineage_kind
                == "NON_SERVING_TRAINING_CANDIDATE"
            ]
            newest_serving_artifact_id = (
                serving_groups[-1].manifest.checkpoint_id
                if serving_groups
                else None
            )
            active_serving_id: str | None = None
            requested_active_id = activation_binding.get("checkpoint_id")
            if isinstance(requested_active_id, str) and requested_active_id:
                active_group = group_by_id.get(requested_active_id)
                active_evidence = (
                    active_group.manifest.checkpoint_evidence
                    if active_group is not None
                    and isinstance(active_group.manifest.checkpoint_evidence, Mapping)
                    else {}
                )
                expected_activation_bindings = (
                    {
                        "checkpoint_id": active_group.manifest.checkpoint_id,
                        "checkpoint_evidence_digest": (
                            active_group.manifest.checkpoint_evidence_digest
                        ),
                        "training_partition_digest": (
                            active_group.manifest.training_partition_digest
                        ),
                        "training_sample_identity_set_sha256": (
                            active_evidence.get(
                                "training_sample_identity_set_sha256"
                            )
                        ),
                        "validation_sample_identity_set_sha256": (
                            active_evidence.get(
                                "validation_sample_identity_set_sha256"
                            )
                        ),
                        "training_feature_identity_set_sha256": (
                            active_evidence.get(
                                "training_feature_identity_set_sha256"
                            )
                        ),
                        "validation_feature_identity_set_sha256": (
                            active_evidence.get(
                                "validation_feature_identity_set_sha256"
                            )
                        ),
                    }
                    if active_group is not None
                    else {}
                )
                binding_reasons: list[str] = []
                if (
                    active_group is None
                    or active_group.manifest_path.parent != checkpoint_dir
                    or active_group.manifest.lineage_kind
                    != "VERIFIED_SERVING_POLICY"
                ):
                    binding_reasons.append(
                        "PRIMARY_ACTIVATION_CHECKPOINT_NOT_IN_VERIFIED_SERVING_STORE"
                    )
                elif any(
                    activation_binding.get(field_name) != expected
                    for field_name, expected in expected_activation_bindings.items()
                ):
                    binding_reasons.append(
                        "PRIMARY_ACTIVATION_CHECKPOINT_BINDING_MISMATCH"
                    )
                if binding_reasons:
                    activation_status.update(
                        {
                            "status": "BLOCKED_PRIMARY_ACTIVATION_BINDING_INVALID",
                            "checkpoint_binding_verified": False,
                            "rejection_reasons": binding_reasons,
                        }
                    )
                else:
                    active_serving_id = requested_active_id
                    activation_status.update(
                        {
                            "status": "PRIMARY_ACTIVATION_CHECKPOINT_VERIFIED",
                            "checkpoint_binding_verified": True,
                            "rejection_reasons": [],
                        }
                    )
            latest_candidate_id = (
                candidate_groups[-1].manifest.checkpoint_id
                if candidate_groups
                else None
            )
            effective_latest_checkpoint_id = latest_checkpoint_id
            latest_checkpoint_id_source = "caller" if latest_checkpoint_id else None
            if not effective_latest_checkpoint_id and active_serving_id:
                effective_latest_checkpoint_id = active_serving_id
                latest_checkpoint_id_source = "primary_manifest_bound_active_checkpoint"
            if latest_checkpoint_id and latest_checkpoint_id not in group_by_id:
                scan_rejection_reasons.append(
                    "CALLER_LATEST_CHECKPOINT_NOT_IN_VALIDATED_SCAN"
                )
            if best_checkpoint_id and best_checkpoint_id not in group_by_id:
                scan_rejection_reasons.append(
                    "OPERATOR_BEST_CHECKPOINT_NOT_IN_VALIDATED_SCAN"
                )

            control_files = [
                path
                for path in (
                    causal_ledger_path,
                    lock_path,
                    *ledger_files,
                )
                if path.is_file()
            ]

            def relative_name(path: Path) -> str:
                return str(path.relative_to(checkpoint_dir))

            pinned_names: set[str] = {
                relative_name(path) for path in control_files
            }
            pinned_reasons: dict[str, list[str]] = {}
            for path in control_files:
                reason = (
                    "CHECKPOINT_CAUSAL_ORDER_CONTROL"
                    if path in {causal_ledger_path, lock_path}
                    else "PPO_CONSUMPTION_LEDGER"
                )
                pinned_reasons.setdefault(relative_name(path), []).append(reason)

            def pin_group(group: _CheckpointRetentionGroup, reason: str) -> None:
                for artifact in (group.manifest_path, group.weight_path):
                    name = relative_name(artifact)
                    pinned_names.add(name)
                    pinned_reasons.setdefault(name, []).append(reason)

            def pin_parent_chain(checkpoint_id: str, reason: str) -> None:
                visited: set[str] = set()
                current_id: str | None = checkpoint_id
                depth = 0
                while current_id is not None:
                    if current_id in visited:
                        scan_rejection_reasons.append(
                            f"CHECKPOINT_PARENT_CYCLE:{checkpoint_id}"
                        )
                        return
                    visited.add(current_id)
                    group = group_by_id.get(current_id)
                    if group is None:
                        scan_rejection_reasons.append(
                            f"CHECKPOINT_PINNED_PARENT_MISSING:{current_id}"
                        )
                        return
                    pin_group(
                        group,
                        reason if depth == 0 else f"{reason}_ANCESTOR",
                    )
                    current_id = group.manifest.parent_checkpoint_id
                    depth += 1

            if active_serving_id:
                pin_parent_chain(active_serving_id, "ACTIVE_VERIFIED_SERVING")
            if newest_serving_artifact_id:
                pin_parent_chain(
                    newest_serving_artifact_id,
                    (
                        "NEWEST_VERIFIED_SERVING_ARTIFACT"
                        if newest_serving_artifact_id == active_serving_id
                        else "NEWEST_STAGED_UNACTIVATED_SERVING_ARTIFACT"
                    ),
                )
            if latest_candidate_id:
                pin_parent_chain(
                    latest_candidate_id,
                    "LATEST_NON_SERVING_CANDIDATE",
                )
            if latest_checkpoint_id and latest_checkpoint_id in group_by_id:
                pin_parent_chain(latest_checkpoint_id, "CALLER_LATEST_CHECKPOINT")
            if best_checkpoint_id and best_checkpoint_id in group_by_id:
                pin_parent_chain(best_checkpoint_id, "OPERATOR_BEST_CHECKPOINT")
            for group in groups:
                checkpoint_id = group.manifest.checkpoint_id
                for flag in ("pinned", "best_checkpoint"):
                    if flag in group.raw_manifest and not isinstance(
                        group.raw_manifest.get(flag), bool
                    ):
                        scan_rejection_reasons.append(
                            f"CHECKPOINT_MANIFEST_PIN_FLAG_INVALID:{checkpoint_id}"
                        )
                if (
                    group.raw_manifest.get("pinned") is True
                    or group.raw_manifest.get("best_checkpoint") is True
                ):
                    pin_parent_chain(checkpoint_id, "MANIFEST_PIN")
                consumed_keys = set(group.manifest.consumed_ppo_update_keys)
                if any(not _sha256_hex(value) for value in consumed_keys):
                    scan_rejection_reasons.append(
                        f"CHECKPOINT_CONSUMED_PPO_KEY_INVALID:{checkpoint_id}"
                    )
                if consumed_keys & pending_claims:
                    pin_parent_chain(
                        checkpoint_id,
                        "PENDING_PPO_CLAIM_RECONCILIATION",
                    )
            for checkpoint_id in terminal_checkpoint_groups:
                pin_parent_chain(
                    checkpoint_id,
                    "TERMINAL_PPO_ATTEMPT_DURABLE_ARTIFACT",
                )

            scan_rejection_reasons = sorted(set(scan_rejection_reasons))
            scan_verified = not scan_rejection_reasons
            limit_bytes = int(rollover_limit_gb) * 1024**3
            deleted: list[str] = []

            def extant_size() -> int:
                paths_to_count = [
                    path
                    for path in (*observed_artifacts, *control_files)
                    if path.is_file()
                ]
                return sum(path.stat().st_size for path in paths_to_count)

            total_bytes = extant_size()
            deleted_group_ids: set[str] = set()
            if (
                scan_verified
                and apply_rollover
                and total_bytes > limit_bytes
            ):
                for group in ordered_groups:
                    if total_bytes <= limit_bytes:
                        break
                    checkpoint_id = group.manifest.checkpoint_id
                    artifacts = (group.manifest_path, group.weight_path)
                    artifact_names = [relative_name(path) for path in artifacts]
                    if any(name in pinned_names for name in artifact_names):
                        continue
                    retained_children = children_by_parent.get(
                        checkpoint_id, set()
                    ) - deleted_group_ids
                    if retained_children:
                        continue
                    staging_dir = (
                        group.manifest_path.parent
                        / ".checkpoint_retention_delete_staging"
                        / checkpoint_id
                    )
                    staged: list[tuple[Path, Path]] = []
                    try:
                        pair_size = sum(path.stat().st_size for path in artifacts)
                        staging_dir.mkdir(parents=True, exist_ok=False)
                        for artifact in artifacts:
                            destination = staging_dir / artifact.name
                            artifact.replace(destination)
                            staged.append((artifact, destination))
                    except OSError:
                        for original, staged_path in reversed(staged):
                            try:
                                staged_path.replace(original)
                            except OSError:
                                pass
                        scan_rejection_reasons.append(
                            f"CHECKPOINT_PAIR_STAGE_FAILED:{checkpoint_id}"
                        )
                        break
                    unlink_failed = False
                    for _original, staged_path in staged:
                        try:
                            staged_path.unlink()
                        except OSError:
                            unlink_failed = True
                    try:
                        staging_dir.rmdir()
                        staging_dir.parent.rmdir()
                    except OSError:
                        unlink_failed = True
                    if unlink_failed:
                        scan_rejection_reasons.append(
                            f"CHECKPOINT_PAIR_DELETE_INCOMPLETE:{checkpoint_id}"
                        )
                        break
                    deleted.extend(artifact_names)
                    deleted_group_ids.add(checkpoint_id)
                    total_bytes -= pair_size

            remaining_groups = [
                group
                for group in ordered_groups
                if group.manifest_path.is_file() and group.weight_path.is_file()
            ]
            remaining_artifacts = [
                path for path in observed_artifacts if path.is_file()
            ]
            total_bytes = extant_size()
            latest_group = remaining_groups[-1] if remaining_groups else None
            oldest_group = remaining_groups[0] if remaining_groups else None
            rollover_blocked = bool(
                apply_rollover and total_bytes > limit_bytes
            )
            if scan_rejection_reasons:
                rollover_status = "ROLLOVER_BLOCKED_SCAN_INVALID"
            elif deleted:
                rollover_status = (
                    "ROLLOVER_APPLIED"
                    if not rollover_blocked
                    else "ROLLOVER_PARTIAL_PARENT_OR_PIN_PROTECTED"
                )
            elif rollover_blocked:
                rollover_status = "ROLLOVER_BLOCKED_PINNED_OR_PARENT_PROTECTED"
            else:
                rollover_status = "BELOW_LIMIT_NO_ACTION"
            status_manifest = {
                "schema_version": (
                    "native_cuda_trainer_checkpoint_retention_manifest_v3"
                ),
                "generated_est": est_now(),
                "checkpoint_dir": str(MODEL_DIR_REL),
                "checkpoint_count": len(remaining_artifacts),
                "checkpoint_pair_count": len(remaining_groups),
                "checkpoint_total_size_gb": round(total_bytes / 1024**3, 6),
                "total_size_gb": round(total_bytes / 1024**3, 6),
                "checkpoint_dir_size_bytes": total_bytes,
                "checkpoint_rollover_limit_gb": int(rollover_limit_gb),
                "rollover_limit_gb": int(rollover_limit_gb),
                "checkpoint_rollover_limit_bytes": limit_bytes,
                "oldest_checkpoint": (
                    relative_name(oldest_group.manifest_path)
                    if oldest_group
                    else None
                ),
                "latest_checkpoint": (
                    relative_name(latest_group.manifest_path)
                    if latest_group
                    else None
                ),
                "latest_checkpoint_id": effective_latest_checkpoint_id,
                "latest_checkpoint_id_source": latest_checkpoint_id_source,
                "active_verified_serving_checkpoint_id": active_serving_id,
                "active_manifest_bound_checkpoint_id": active_serving_id,
                "newest_verified_serving_artifact_id": (
                    newest_serving_artifact_id
                ),
                "newest_unactivated_serving_artifact_id": (
                    newest_serving_artifact_id
                    if newest_serving_artifact_id != active_serving_id
                    else None
                ),
                "primary_checkpoint_activation": activation_status,
                "best_checkpoint": best_checkpoint_id,
                "pinned_checkpoints": sorted(pinned_names),
                "pinned_checkpoint_reasons": {
                    key: sorted(set(value))
                    for key, value in sorted(pinned_reasons.items())
                },
                "latest_non_serving_candidate_id": latest_candidate_id,
                "checkpoint_ordering": (
                    "CAUSAL_GENERATION_THEN_STRICT_LEGACY_GENERATED_UTC"
                ),
                "filesystem_mtime_used_for_ordering": False,
                "checkpoint_retention_scan_verified": not scan_rejection_reasons,
                "checkpoint_retention_scan_rejection_reasons": sorted(
                    set(scan_rejection_reasons)
                ),
                "checkpoint_causal_ledger_path": (
                    relative_name(causal_ledger_path)
                    if causal_ledger_path.is_file()
                    else None
                ),
                "checkpoint_causal_lock_path": relative_name(lock_path),
                "ppo_consumption_ledger_path": (
                    relative_name(ledger_path) if ledger_path.is_file() else None
                ),
                "ppo_consumption_ledger_pinned": ledger_path.is_file(),
                "ppo_consumption_ledger_integrity_verified": (
                    ledger_state.get("integrity_verified") is True
                ),
                "terminal_ppo_attempt_count": len(attempt_rows),
                "terminal_checkpoint_reference_count": len(
                    terminal_checkpoint_groups
                ),
                "terminal_checkpoint_bindings_verified": bool(
                    ledger_state.get("integrity_verified") is True
                    and not any(
                        reason.startswith("PPO_TERMINAL_")
                        for reason in scan_rejection_reasons
                    )
                ),
                "pending_ppo_claim_count": (
                    len(pending_claims)
                    if ledger_state.get("integrity_verified") is True
                    else None
                ),
                "pending_ppo_claim_state_verified": (
                    ledger_state.get("integrity_verified") is True
                ),
                "complete_pair_deletion_only": True,
                "incomplete_pairs_fail_closed": True,
                "parent_chain_holes_fail_closed": True,
                "pinned_parent_chains_preserved": True,
                "incomplete_checkpoint_artifacts": sorted(
                    incomplete_artifacts
                ),
                "deleted_checkpoints": deleted,
                "rollover_action_taken": (
                    "DELETED_OLDEST_CAUSAL_NON_PINNED_LEAF"
                    if deleted
                    else "NONE"
                ),
                "checkpoint_rollover_status": rollover_status,
                "never_delete_latest_checkpoint": True,
                "never_delete_pinned_high_performing_checkpoint": True,
            }
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    write_json(
        checkpoint_dir / "checkpoint_retention_manifest.json",
        status_manifest,
    )
    return status_manifest


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
    result_status = as_dict(getattr(trainer_result, "status", {}))
    resource = as_dict(result_status.get("cuda_cpu_resource_utilization"))
    envelope = as_dict(result_status.get("current_cycle_learning_envelope"))
    source_cycle_resource = as_dict(
        result_status.get("current_cycle_resource_evidence")
    )
    service_state = systemctl_show(PERSISTENT_UNIT)
    service_pid = int(finite_float(service_state.get("MainPID")) or 0)
    expected_instance_id = f"{socket.gethostname()}:{os.getpid()}"
    resource_rejection_reasons: list[str] = []
    if not envelope:
        resource_rejection_reasons.append("CURRENT_CYCLE_ENVELOPE_MISSING")
    if (
        source_cycle_resource.get("cycle_id") != envelope.get("cycle_id")
        or source_cycle_resource.get("process_instance_id")
        != envelope.get("process_instance_id")
    ):
        resource_rejection_reasons.append("CURRENT_CYCLE_RESOURCE_IDENTITY_MISMATCH")
    if source_cycle_resource.get("process_instance_id") != expected_instance_id:
        resource_rejection_reasons.append("CURRENT_CYCLE_RESOURCE_PROCESS_MISMATCH")
    if (
        service_state.get("ActiveState") != "active"
        or service_pid <= 0
        or service_pid != os.getpid()
    ):
        resource_rejection_reasons.append("SYSTEMD_MAINPID_NOT_CURRENT_PROCESS")
    if gpu.get("available") is not True:
        resource_rejection_reasons.append("CURRENT_NVIDIA_SMI_REVALIDATION_FAILED")
    if source_cycle_resource.get("cuda_available") is not True:
        resource_rejection_reasons.append("CURRENT_CYCLE_CUDA_AVAILABLE_NOT_TRUE")
    if source_cycle_resource.get("cuda_active") is not True:
        resource_rejection_reasons.append("CURRENT_CYCLE_CUDA_ACTIVE_NOT_TRUE")
    resource_rejection_reasons = list(dict.fromkeys(resource_rejection_reasons))
    current_cycle_resource_evidence = {
        **source_cycle_resource,
        "cuda_available": bool(
            not resource_rejection_reasons
            and source_cycle_resource.get("cuda_available") is True
        ),
        "cuda_active": bool(
            not resource_rejection_reasons
            and source_cycle_resource.get("cuda_active") is True
        ),
        "systemd_main_pid": service_pid or None,
        "systemd_process_reverified": not resource_rejection_reasons,
        "resource_revalidation_rejection_reasons": resource_rejection_reasons,
    }
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
        "current_cycle_resource_evidence": current_cycle_resource_evidence,
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
    trainer_process_active: bool | None = None,
    cuda_inference_active: bool | None = None,
    trainer_process_evidence: Mapping[str, Any] | None = None,
    current_cycle_learning_envelope: Mapping[str, Any] | None = None,
    runtime_status_evidence: Mapping[str, Any] | None = None,
    heartbeat_evidence: Mapping[str, Any] | None = None,
    verified_serving_checkpoint: Mapping[str, Any] | None = None,
    prediction_publication_evidence: Mapping[str, Any] | None = None,
    resource_evidence: Mapping[str, Any] | None = None,
    parity_evidence: Mapping[str, Any] | None = None,
    now_utc: datetime | None = None,
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
        trainer_process_active=trainer_process_active,
        trainer_process_evidence=trainer_process_evidence,
        cuda_inference_active=cuda_inference_active,
        current_cycle_learning_envelope=current_cycle_learning_envelope,
        runtime_status_evidence=runtime_status_evidence,
        heartbeat_evidence=heartbeat_evidence,
        verified_serving_checkpoint=verified_serving_checkpoint,
        prediction_publication_evidence=prediction_publication_evidence,
        resource_evidence=resource_evidence,
        parity_evidence=parity_evidence,
        now_utc=now_utc,
    )
    return {
        **{key: value for key, value in readiness.items() if key != "schema_version"},
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
    service_pid = int(finite_float(service.get("MainPID")) or 0)
    pid = service_pid if service_pid > 0 else os.getpid()
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
    service_active = service.get("ActiveState") == "active" and service_pid > 0
    current_process_is_service_main = service_active and service_pid == os.getpid()
    worker_health_status = (
        "HEALTHY"
        if service_active and heartbeat_age_seconds is not None and heartbeat_age_seconds <= 300
        else "DEGRADED"
        if service_active
        else "OFFLINE"
    )
    redis_client = connect_redis()
    redis_trainer_status = as_dict(
        redis_json(redis_client, "v2:trainer:hybrid_cuda:status")
    )
    runtime_status_evidence = redis_trainer_status or (
        status
        if as_dict(status.get("status_publication")).get(
            "publication_complete"
        )
        is True
        else {}
    )
    heartbeat_evidence = as_dict(
        redis_json(redis_client, "v2:trainer:hybrid_cuda:heartbeat")
    ) or as_dict(status.get("current_cycle_heartbeat_evidence"))
    current_cycle_envelope = as_dict(
        runtime_status_evidence.get("current_cycle_learning_envelope")
    )
    prediction_publication_evidence = as_dict(
        prediction_public.get("current_cycle_prediction_publication_evidence")
    )
    parity_dashboard = as_dict(
        read_json(
            paths.public_root
            / (
                "v2_native_hybrid_trainer_full_function_parity_and_paper_reverify/"
                "latest/operator_dashboard_payload.json"
            )
        )
    )
    parity_evidence = as_dict(
        parity_dashboard.get("current_cycle_parity_evidence")
    )
    resource_evidence = as_dict(resource.get("current_cycle_resource_evidence"))
    verified_serving_evidence = as_dict(
        status.get("current_cycle_verified_serving_checkpoint_evidence")
    )
    process_evidence = (
        {
            "service_active": True,
            "service_unit": PERSISTENT_UNIT,
            "process_id": service_pid,
            "process_instance_id": f"{socket.gethostname()}:{service_pid}",
        }
        if current_process_is_service_main
        else {}
    )
    online_learning = online_learning_runtime_fields(
        training=training,
        latest_training_metrics=latest_training_metrics,
        persistent_state=persistent_state,
        prediction_rows=prediction_rows,
        trainer_process_active=current_process_is_service_main,
        trainer_process_evidence=process_evidence,
        cuda_inference_active=bool(
            resource_evidence.get("cuda_available") is True
            and resource_evidence.get("cuda_active") is True
        ),
        current_cycle_learning_envelope=current_cycle_envelope,
        runtime_status_evidence=runtime_status_evidence,
        heartbeat_evidence=heartbeat_evidence,
        verified_serving_checkpoint=verified_serving_evidence,
        prediction_publication_evidence=prediction_publication_evidence,
        resource_evidence=resource_evidence,
        parity_evidence=parity_evidence,
        now_utc=datetime.now(tz=timezone.utc),
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
        "service_pid": service_pid or None,
        "cycle_process_pid": os.getpid(),
        "cycle_process_active": True,
        "cycle_process_is_service_main": current_process_is_service_main,
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
        "current_cycle_learning_envelope": current_cycle_envelope,
        "current_cycle_prediction_publication_evidence": (
            prediction_publication_evidence
        ),
        "current_cycle_resource_evidence": resource_evidence,
        "current_cycle_parity_evidence": parity_evidence,
        "current_cycle_verified_serving_checkpoint_evidence": (
            verified_serving_evidence
        ),
        "trainer_process_evidence": process_evidence,
        "actual_systemd_mainpid_bound_to_cycle_process": (
            current_process_is_service_main
        ),
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
    service = systemctl_show(PERSISTENT_UNIT)
    service_pid = int(finite_float(service.get("MainPID")) or 0)
    service_active = service.get("ActiveState") == "active" and service_pid > 0
    current_process_is_service_main = service_active and service_pid == os.getpid()
    current_runtime_path = paths.operator_dir / "native_trainer_runtime_status.json"
    current_runtime = as_dict(read_json(current_runtime_path))
    latest_training_metrics = current_runtime.get("latest_training_metrics")
    online_learning = online_learning_runtime_fields(
        latest_training_metrics=latest_training_metrics,
        persistent_state=state,
        prediction_rows=prediction_rows,
        trainer_process_active=current_process_is_service_main,
        trainer_process_evidence=(
            {
                "service_active": True,
                "service_unit": PERSISTENT_UNIT,
                "process_id": service_pid,
                "process_instance_id": f"{socket.gethostname()}:{service_pid}",
            }
            if current_process_is_service_main
            else {}
        ),
        cuda_inference_active=False,
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
        "service_active": service_active,
        "service_state": service,
        "service_pid": service_pid or None,
        "pid": os.getpid(),
        "cycle_process_pid": os.getpid(),
        "cycle_process_active": True,
        "cycle_process_is_service_main": current_process_is_service_main,
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
        "worker_health_status": (
            "HEALTHY" if current_process_is_service_main else "OFFLINE"
        ),
        "trainer_liveness_status": (
            "HEALTHY" if current_process_is_service_main else "OFFLINE"
        ),
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
            "schema_version": "native_trainer_runtime_status_v1",
            "generated_est": generated_est,
            "generated_utc": generated_utc,
            "payload_age_seconds": 0,
            "current_status_age_seconds": 0,
            "training_loop_active": True,
            "continuous_training_enabled": True,
            "training_cycle_status": payload["training_cycle_status"],
            "persistent_trainer_service_active": service_active,
            "persistent_trainer_pid": service_pid or None,
            "trainer_cycle_process_pid": os.getpid(),
            "trainer_cycle_process_active": True,
            "trainer_cycle_process_is_service_main": current_process_is_service_main,
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
            "trainer_liveness_status": (
                "HEALTHY" if current_process_is_service_main else "OFFLINE"
            ),
            "worker_health_status": (
                "HEALTHY" if current_process_is_service_main else "OFFLINE"
            ),
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
_COMPARABLE_VALIDATION_REGRESSION_REASONS = frozenset(
    {
        "CANDIDATE_VALIDATION_LOSS_REGRESSED",
        "CANDIDATE_VALIDATION_EDGE_LCB_REGRESSED",
    }
)


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
_PREFETCH_TRUSTED_REPLAY_ARCHIVE_ROOT: Path | None = None
_PREFETCH_MAX_ROWS_PER_CYCLE: int | None = None
_PREFETCH_CHUNK_ROWS = 2_048
_PREFETCH_IDLE_SLEEP_SECONDS = 10.0


def _prefetch_backfill_worker(
    *,
    trusted_replay_archive_root: Path,
    stop_event: threading.Event,
    max_rows_per_cycle: int,
) -> None:
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
        V2HybridTrainerDataLoader,
    )

    loader = None
    cycle_row_limit = max(0, int(max_rows_per_cycle))
    chunk_row_limit = min(_PREFETCH_CHUNK_ROWS, cycle_row_limit)
    if chunk_row_limit <= 0:
        return
    while not stop_event.is_set():
        try:
            with _PREFETCH_LOCK:
                queued = len(_PREFETCH_QUEUE)
            buffered = len(_REPLAY_BUFFER)
            capacity = int(_REPLAY_BUFFER.maxlen or 0)
            remaining_cycle_rows = max(0, cycle_row_limit - queued)
            remaining_capacity_rows = max(
                0,
                capacity - buffered - queued,
            ) if capacity else 0
            load_limit = min(
                chunk_row_limit,
                remaining_cycle_rows,
                remaining_capacity_rows,
            )
            if load_limit <= 0:
                stop_event.wait(_PREFETCH_IDLE_SLEEP_SECONDS)
                continue
            if loader is None:
                loader = V2HybridTrainerDataLoader(
                    io=V2OnlyJsonIO(client=connect_redis()),
                    trusted_replay_archive_root=trusted_replay_archive_root,
                )
            examples = loader.load_trusted_replay_examples(
                limit=load_limit, backfill=True
            )
            if examples:
                with _PREFETCH_LOCK:
                    still_available = max(
                        0,
                        cycle_row_limit - len(_PREFETCH_QUEUE),
                    )
                    _PREFETCH_QUEUE.extend(examples[:still_available])
            else:
                stop_event.wait(_PREFETCH_IDLE_SLEEP_SECONDS)
        except Exception:
            loader = None
            stop_event.wait(_PREFETCH_IDLE_SLEEP_SECONDS)


def _ensure_prefetch_thread_started(
    *,
    trusted_replay_archive_root: Path,
    max_rows_per_cycle: int,
) -> None:
    global _PREFETCH_STOP, _PREFETCH_THREAD
    global _PREFETCH_TRUSTED_REPLAY_ARCHIVE_ROOT, _PREFETCH_MAX_ROWS_PER_CYCLE
    resolved_archive_root = Path(trusted_replay_archive_root).expanduser().resolve()
    resolved_max_rows = max(0, int(max_rows_per_cycle))
    if _PREFETCH_THREAD is not None and _PREFETCH_THREAD.is_alive():
        if (
            _PREFETCH_TRUSTED_REPLAY_ARCHIVE_ROOT == resolved_archive_root
            and _PREFETCH_MAX_ROWS_PER_CYCLE == resolved_max_rows
        ):
            return
        _PREFETCH_STOP.set()
        _PREFETCH_THREAD.join(timeout=5.0)
        if _PREFETCH_THREAD.is_alive():
            raise RuntimeError("trusted replay prefetch root change could not stop prior worker")
    if (
        _PREFETCH_TRUSTED_REPLAY_ARCHIVE_ROOT != resolved_archive_root
        or _PREFETCH_MAX_ROWS_PER_CYCLE != resolved_max_rows
    ):
        with _PREFETCH_LOCK:
            _PREFETCH_QUEUE.clear()
    if _PREFETCH_TRUSTED_REPLAY_ARCHIVE_ROOT != resolved_archive_root:
        _REPLAY_BUFFER.clear()
    _PREFETCH_STOP = threading.Event()
    _PREFETCH_TRUSTED_REPLAY_ARCHIVE_ROOT = resolved_archive_root
    _PREFETCH_MAX_ROWS_PER_CYCLE = resolved_max_rows
    _PREFETCH_THREAD = threading.Thread(
        target=_prefetch_backfill_worker,
        kwargs={
            "trusted_replay_archive_root": resolved_archive_root,
            "stop_event": _PREFETCH_STOP,
            "max_rows_per_cycle": resolved_max_rows,
        },
        name="v2-trainer-backfill-prefetch",
        daemon=True,
    )
    _PREFETCH_THREAD.start()


def _snapshot_prefetched_backfill_examples() -> list[Any]:
    """Return a stable queue prefix without discarding unconsumed rows."""

    with _PREFETCH_LOCK:
        return list(_PREFETCH_QUEUE)


def _acknowledge_prefetched_backfill_examples(consumed: int) -> int:
    """Remove only rows the completed trainer cycle actually consumed."""

    acknowledged = 0
    with _PREFETCH_LOCK:
        for _index in range(max(0, int(consumed))):
            if not _PREFETCH_QUEUE:
                break
            _PREFETCH_QUEUE.popleft()
            acknowledged += 1
    return acknowledged


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
    validation_regression_reasons: Iterable[str] = (),
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
    observed_regression_reasons = tuple(
        sorted(
            {
                str(reason)
                for reason in validation_regression_reasons
                if str(reason) in _COMPARABLE_VALIDATION_REGRESSION_REASONS
            }
        )
    )
    reason_coded_validation_regression = bool(observed_regression_reasons)
    validation_regressed = bool(
        accepted_rows > 0 and reason_coded_validation_regression
    )
    if oom_occurred:
        classification = "OOM_BACKOFF"
        multiplier = max(RESIDENT_STEPS_MULTIPLIER_MIN, multiplier // 2)
        oom_events += 1
    elif validation_regressed:
        # Only a reason-coded regression on comparable untouched validation
        # evidence is an actuation signal. Generic promotion rejection includes
        # PIT gaps, starvation, missing confidence evidence, and persistence
        # failures; none proves that doing less optimizer work improves quality.
        classification = "COMPARABLE_VALIDATION_REGRESSION_BACKOFF"
        multiplier = max(RESIDENT_STEPS_MULTIPLIER_MIN, multiplier // 2)
    elif accepted_rows <= 0:
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
        "data_starved": accepted_rows <= 0,
        "data_starvation_actuation_rule": "accepted_rows_gt_0",
        "data_loader_time_ms": data_loader_time_ms,
        "gpu_train_time_ms": gpu_train_time_ms,
        "oom_events": oom_events,
        "checkpoint_promotion_rejected": bool(checkpoint_promotion_rejected),
        "checkpoint_promotion_reason": checkpoint_promotion_reason,
        "validation_loss_delta": validation_loss_delta,
        "validation_loss_delta_actuation_used": False,
        "validation_regressed": validation_regressed,
        "reason_coded_validation_regression_observed": (
            reason_coded_validation_regression
        ),
        "validation_regression_actuation_requires_accepted_rows_gt_0": True,
        "comparable_validation_regression_reasons": list(
            observed_regression_reasons
        ),
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
    candidate_progress = as_dict(
        nested_training_metrics.get("candidate_progress_decision")
    )
    regression_reason_candidates = [
        *as_list(candidate_progress.get("candidate_progress_rejection_reasons")),
        *as_list(promotion.get("checkpoint_promotion_rejection_reasons")),
        *as_list(nested_training_metrics.get("checkpoint_promotion_rejection_reasons")),
    ]
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
        validation_regression_reasons=regression_reason_candidates,
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
    interval_seconds: int = LEGACY_RUNTIME_DEFAULT_PREDICTION_LOOP_SECONDS,
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
    expected_cycle_cadence_seconds = max(1, min(300, int(interval_seconds)))
    config = HybridTrainerConfig(
        symbols=symbols,
        timeframes=tuple(DEFAULT_TIMEFRAMES),
        model_dir=paths.model_dir,
        max_training_rows_per_cycle=int(max_rows),
        # Cap batch_size independently of max_rows. A batch equal to a very
        # large max_rows can run one oversized native CUDA op that the SIGALRM
        # timeout cannot interrupt. RL_BATCH_SIZE is still bounded by the same
        # safety ceiling inside legacy_grade_runtime_config.
        batch_size=int(effective_config.get("batch_size") or max(1, min(int(max_rows), RESIDENT_MAX_BATCH_SIZE))),
        train_steps=train_steps,
        rollout_n_steps=int(effective_config.get("n_steps") or DEFAULT_ROLLOUT_N_STEPS),
        rollout_max_envs=int(effective_config.get("n_envs") or DEFAULT_ROLLOUT_MAX_ENVS),
        expected_cycle_cadence_seconds=expected_cycle_cadence_seconds,
        risk_caps_configured=bool(risk_caps_configured),
    )
    _ensure_prefetch_thread_started(
        trusted_replay_archive_root=paths.trusted_replay_archive_root,
        max_rows_per_cycle=config.max_training_rows_per_cycle,
    )
    prefetched_backfill_examples = _snapshot_prefetched_backfill_examples()
    result = run_hybrid_trainer_cycle(
        config=config,
        io=io,
        publish=True,
        replay_buffer=_REPLAY_BUFFER,
        prefetched_backfill_examples=prefetched_backfill_examples,
        trusted_replay_archive_root=paths.trusted_replay_archive_root,
        behavior_receipt_archive_root=paths.behavior_receipt_archive_root,
    )
    result_metrics = as_dict(getattr(result, "metrics", {}))
    training_metrics = as_dict(
        as_dict(result_metrics.get("training")).get("metrics")
    )
    loader_stage = as_dict(training_metrics.get("data_loader_stage_ms"))
    consumed_prefetch_rows = int(
        finite_float(loader_stage.get("prefetched_backfill_rows_consumed"))
        or 0
    )
    _acknowledge_prefetched_backfill_examples(consumed_prefetch_rows)
    return result


def dashboard_runtime_readiness_blockers(
    *,
    persistent: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    trainer_result: Any | None,
    now_utc: datetime | None = None,
) -> list[str]:
    """Return fail-closed blockers for the operator dashboard readiness gate.

    Resource availability is telemetry, not proof of learning or serving. A
    READY gate requires fresh evidence from this cycle, a semantically verified
    serving checkpoint, current prediction publication, and durable learning.
    """

    blockers: list[str] = []

    def block(reason: str) -> None:
        if reason not in blockers:
            blockers.append(reason)

    if persistent.get("service_active") is not True:
        block("PERSISTENT_TRAINER_SERVICE_NOT_ACTIVE")
    if persistent.get("training_loop_active") is not True:
        block("PERSISTENT_TRAINING_LOOP_NOT_ACTIVE")
    if persistent.get("trainer_liveness_status") != "HEALTHY":
        block("TRAINER_LIVENESS_NOT_HEALTHY")
    if persistent.get("worker_health_status") != "HEALTHY":
        block("TRAINER_WORKER_NOT_HEALTHY")
    if persistent.get("trainer_process_status") != "ACTIVE":
        block("TRAINER_PROCESS_NOT_ACTIVE")
    if persistent.get("cuda_inference_status") != "ACTIVE":
        block("CUDA_INFERENCE_NOT_ACTIVE")
    if persistent.get("prediction_publication_status") != "ACTIVE":
        block("PREDICTION_PUBLICATION_NOT_ACTIVE")
    if persistent.get("prediction_grid_current") is not True:
        block("PREDICTION_GRID_NOT_CURRENT")
    if persistent.get("trainer_learning_ready") is not True:
        block("TRAINER_LEARNING_NOT_READY")
    if persistent.get("online_learning_status") != "WEIGHTS_UPDATING":
        block("ONLINE_LEARNING_NOT_WEIGHTS_UPDATING")
    if persistent.get("checkpoint_weight_blob_written") is not True:
        block("CHECKPOINT_WEIGHT_BLOB_NOT_WRITTEN")
    if persistent.get("checkpoint_reload_verified") is not True:
        block("CHECKPOINT_RELOAD_NOT_VERIFIED")

    effective_config = as_dict(persistent.get("legacy_runtime_effective_config"))
    cadence_seconds = finite_float(effective_config.get("prediction_loop_seconds"))
    if cadence_seconds is None or cadence_seconds <= 0.0:
        block("TRAINER_RUNTIME_CADENCE_EVIDENCE_MISSING")
        freshness_budget_seconds = None
    else:
        freshness_budget_seconds = cadence_seconds * 3.0
    observed_now = now_utc or datetime.now(tz=timezone.utc)
    if observed_now.tzinfo is None or observed_now.utcoffset() is None:
        raise ValueError("dashboard readiness now_utc must be timezone-aware")
    observed_now = observed_now.astimezone(timezone.utc)

    def require_current_clock(value: Any, *, missing: str, stale: str) -> None:
        parsed = parse_runtime_time(value)
        if parsed is None:
            block(missing)
            return
        age_seconds = (observed_now - parsed.astimezone(timezone.utc)).total_seconds()
        if (
            freshness_budget_seconds is None
            or age_seconds < 0.0
            or age_seconds > freshness_budget_seconds
        ):
            block(stale)

    require_current_clock(
        persistent.get("generated_utc"),
        missing="TRAINER_RUNTIME_GENERATED_CLOCK_MISSING",
        stale="TRAINER_RUNTIME_STATUS_STALE",
    )
    heartbeat_age = finite_float(persistent.get("heartbeat_age_seconds"))
    if heartbeat_age is None:
        block("TRAINER_HEARTBEAT_AGE_MISSING")
    elif (
        freshness_budget_seconds is None
        or heartbeat_age < 0.0
        or heartbeat_age > freshness_budget_seconds
    ):
        block("TRAINER_HEARTBEAT_STALE")

    if checkpoint.get("checkpoint_retention_scan_verified") is not True:
        block("CHECKPOINT_RETENTION_SCAN_NOT_VERIFIED")
    active_serving_id = str(
        checkpoint.get("active_verified_serving_checkpoint_id") or ""
    )
    if not active_serving_id:
        block("ACTIVE_VERIFIED_SERVING_CHECKPOINT_MISSING")

    if trainer_result is None:
        block("CURRENT_TRAINER_RESULT_MISSING")
        return blockers
    result_status = as_dict(getattr(trainer_result, "status", {}))
    result_metrics = as_dict(getattr(trainer_result, "metrics", {}))
    if result_status.get("trainer_process_status") != "ACTIVE_CURRENT_CYCLE":
        block("CURRENT_CYCLE_TRAINER_PROCESS_NOT_ACTIVE")
    if result_status.get("cuda_inference_status") != "ACTIVE":
        block("CURRENT_CYCLE_CUDA_INFERENCE_NOT_ACTIVE")
    if result_status.get("prediction_publication_status") != "ACTIVE":
        block("CURRENT_CYCLE_PREDICTION_PUBLICATION_NOT_ACTIVE")
    require_current_clock(
        result_status.get("generated_utc"),
        missing="CURRENT_CYCLE_GENERATED_CLOCK_MISSING",
        stale="CURRENT_CYCLE_RUNTIME_EVIDENCE_STALE",
    )
    result_checkpoint_id = str(result_status.get("checkpoint_id") or "")
    if not result_checkpoint_id or result_checkpoint_id != active_serving_id:
        block("CURRENT_CYCLE_CHECKPOINT_NOT_ACTIVE_VERIFIED_SERVING")
    checkpoint_reload = as_dict(result_metrics.get("checkpoint_reload"))
    try:
        serving_verified, _serving_reasons = _verified_serving_checkpoint_evidence(
            checkpoint_reload,
            expected_checkpoint_id=result_checkpoint_id,
        )
    except (RuntimeError, TypeError, ValueError):
        serving_verified = False
    if not serving_verified:
        block("CURRENT_CYCLE_SERVING_CHECKPOINT_SEMANTICS_NOT_VERIFIED")
    return blockers


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
    blockers = dashboard_runtime_readiness_blockers(
        persistent=persistent,
        checkpoint=checkpoint,
        trainer_result=trainer_result,
    )
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
    # ``build_persistent_runtime_status`` already evaluated the canonical
    # envelope against Redis TTL evidence, the public complete grid, current
    # CUDA/parity attestations, and the actual systemd MainPID.  Re-running the
    # legacy compatibility call here would discard those identities and could
    # join stale counters into a different answer.
    online_learning = {
        key: persistent.get(key)
        for key in (
            "canonical_readiness_status",
            "trainer_learning_ready",
            "trainer_process_status",
            "cuda_inference_status",
            "prediction_publication_status",
            "offline_replay_learning_status",
            "online_paper_learning_status",
            "online_learning_status",
            "effective_trainer_mode",
            "allowed_effective_trainer_modes",
            "cycle_id",
            "process_instance_id",
            "expected_cycle_cadence_seconds",
            "freshness_budget_seconds",
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
            "checkpoint_id",
            "parent_checkpoint_id",
            "parent_policy_fingerprint",
            "candidate_policy_fingerprint",
            "checkpoint_hash",
            "checkpoint_reload_verified",
            "requirement_checks",
            "readiness_blocking_reasons",
            "rows_rejected_by_reason",
            "loss_before",
            "loss_after",
        )
    }
    persistent_cycle_envelope = as_dict(
        persistent.get("current_cycle_learning_envelope")
    )
    canonical_persistent_evidence_present = bool(
        persistent.get("canonical_readiness_status") in {"READY", "BLOCKED"}
        and persistent_cycle_envelope
        and persistent_cycle_envelope.get("cycle_id")
        and persistent_cycle_envelope.get("process_instance_id")
    )
    if not canonical_persistent_evidence_present:
        current_feedback_metrics = as_dict(
            as_dict(latest_training_metrics).get("metrics")
        )
        # Do not let absent present-cycle evidence inherit counters or READY
        # labels from the prior operator artifact.  Zero here means the current
        # fail-closed feedback scan admitted no rows; historical totals remain
        # available only in their explicitly historical telemetry fields.
        online_learning.update(
            {
                "canonical_readiness_status": "BLOCKED",
                "trainer_learning_ready": False,
                "trainer_process_status": (
                    "BLOCKED_NO_CURRENT_CYCLE_PROCESS_EVIDENCE"
                ),
                "cuda_inference_status": (
                    "BLOCKED_NO_CURRENT_CYCLE_CUDA_EVIDENCE"
                ),
                "prediction_publication_status": (
                    "BLOCKED_NO_CURRENT_COMPLETE_PREDICTION_PUBLICATION"
                ),
                "offline_replay_learning_status": (
                    "BLOCKED_NO_COHERENT_CURRENT_CYCLE_LEARNING_ENVELOPE"
                ),
                "online_paper_learning_status": (
                    "BLOCKED_NO_COHERENT_CURRENT_CYCLE_LEARNING_ENVELOPE"
                ),
                "online_learning_status": (
                    "BLOCKED_NO_COHERENT_CURRENT_CYCLE_LEARNING_ENVELOPE"
                ),
                "effective_trainer_mode": "INFERENCE_ONLY",
                "last_successful_weight_update_at": None,
                "trusted_rows_loaded": int(
                    finite_float(
                        current_feedback_metrics.get("trusted_rows_loaded")
                    )
                    or 0
                ),
                "trusted_replay_rows_loaded": 0,
                "feedback_rows_entered_batch": int(
                    finite_float(
                        current_feedback_metrics.get(
                            "feedback_rows_entered_batch"
                        )
                    )
                    or 0
                ),
                "optimizer_steps_this_cycle": 0,
                "optimizer_steps_last_hour": 0,
                "rows_rejected_by_reason": dict(
                    as_dict(
                        current_feedback_metrics.get(
                            "rows_rejected_by_reason"
                        )
                    )
                ),
                "requirement_checks": {},
                "readiness_blocking_reasons": [
                    "CURRENT_CYCLE_LEARNING_ENVELOPE_MISSING"
                ],
            }
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
        "schema_version": "native_trainer_runtime_status_v1",
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
        "current_cycle_learning_envelope": persistent.get(
            "current_cycle_learning_envelope"
        ),
        "current_cycle_prediction_publication_evidence": persistent.get(
            "current_cycle_prediction_publication_evidence"
        ),
        "current_cycle_resource_evidence": persistent.get(
            "current_cycle_resource_evidence"
        ),
        "current_cycle_parity_evidence": persistent.get(
            "current_cycle_parity_evidence"
        ),
        "current_cycle_verified_serving_checkpoint_evidence": persistent.get(
            "current_cycle_verified_serving_checkpoint_evidence"
        ),
        "actual_systemd_mainpid_bound_to_cycle_process": persistent.get(
            "actual_systemd_mainpid_bound_to_cycle_process"
        ),
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
    # Historical 10k-row / 50-symbol bootstrap milestones remain visible for
    # provenance, but they are not market-adaptive learning or serving proof and
    # therefore cannot make this goal READY or BLOCKED. Runtime readiness is
    # derived from current causal evidence above.
    legacy_bootstrap_milestones = {
        "readiness_actuation_used": False,
        "trusted_replay_rows": trusted_replay_dataset.get("trusted_replay_rows"),
        "trusted_replay_rows_requirement_met": trusted_replay_dataset.get(
            "trusted_replay_rows_requirement_met"
        ),
        "symbol_count": trusted_replay_dataset.get("symbol_count"),
        "symbol_count_requirement_met": trusted_replay_dataset.get(
            "symbol_count_requirement_met"
        ),
        "all_required_timeframes_present": trusted_replay_dataset.get(
            "all_required_timeframes_present"
        ),
    }
    goal_blockers: list[str] = [
        f"runtime_readiness:{reason}" for reason in blockers
    ]
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
        "readiness_basis": "CURRENT_CAUSAL_RUNTIME_EVIDENCE_NOT_STATIC_BOOTSTRAP_COUNTS",
        "legacy_bootstrap_milestones": legacy_bootstrap_milestones,
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
                    "- Legacy 10k-row / 50-symbol bootstrap milestones are telemetry only and do not actuate readiness.",
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
    interval_seconds: int = LEGACY_RUNTIME_DEFAULT_PREDICTION_LOOP_SECONDS,
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
                    interval_seconds=interval_seconds,
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
        elif msg.strip() == "no prediction examples built":
            trainer_result = None
            training_blocker_reason = "NO_PREDICTION_EXAMPLES_BUILT"
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
    parser.add_argument("--repo-root", type=Path, default=CANONICAL_REPO_ROOT)
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
    interval_seconds = max(1, min(300, int(args.interval_seconds)))
    cycles = 0
    while True:
        payloads = run_one_persistent_cycle(
            paths=paths,
            max_rows=args.max_rows,
            risk_caps_configured=True,
            run_training=not args.no_training,
            interval_seconds=interval_seconds,
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
        sleep_s = interval_seconds if blockers else post_training_pause_s
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
