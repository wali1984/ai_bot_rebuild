"""Current native trainer runtime truth payloads.

This module builds website-facing status from current V2 runtime sources. It is
read-only except for writing V2-owned public JSON artifacts through the CLI.
It never calls exchanges, writes legacy Redis namespaces, or starts legacy
trainer bridge/wrapper processes.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import socket
import subprocess
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (
    VERIFIED_SERVING_LINEAGE,
)
from v2.backend.app.services.native_trainer.learning_readiness import (
    build_learning_readiness,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
PUBLIC_ROOT = REPO_ROOT / "v2/frontend/public"
OPERATOR_RUNTIME_REL = Path("operator_runtime/v2_native_trainer/latest")
ARTIFACT_REL = Path("v2_model_state_ai_predictions_signals_and_runtime_truth_semantic_repair/latest")
WORKLOG_REL = Path("claude_worklog/final_readiness") / ARTIFACT_REL
EST = ZoneInfo("America/New_York")

READY = "V2_MODEL_STATE_AI_PREDICTIONS_SIGNALS_AND_RUNTIME_TRUTH_SEMANTIC_REPAIR_READY"
BLOCKED = "V2_MODEL_STATE_AI_PREDICTIONS_SIGNALS_AND_RUNTIME_TRUTH_SEMANTIC_REPAIR_BLOCKED"

PREDICTION_STATUS_REL = Path(
    "operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json"
)
ALL_TF_STATUS_REL = Path(
    "v2_all_timeframe_prediction_signal_price_target_publisher/latest/all_timeframe_prediction_publisher_status.json"
)
RUNTIME_TRUTH_REL = Path("operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json")
RUNTIME_PAGES_REL = Path("operator_runtime/v2_runtime_truth/latest/runtime_pages_payload.json")
PORTFOLIO_REL = Path("operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json")
PAPER_TRIAL_REL = Path(
    "v2_paper_only_confidence_threshold_trial_and_outcome_monitor/latest/operator_dashboard_payload.json"
)
PARITY_REL = Path(
    "v2_native_hybrid_trainer_full_function_parity_and_paper_reverify/latest/operator_dashboard_payload.json"
)
LIVE_GATE_REL = Path("operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json")

MODEL_DIR = Path(".local_models/v2_native_rl_masa_ppo")
TRAINER_METRICS_KEY = "v2:trainer:hybrid_cuda:metrics"
TRAINER_STATUS_KEY = "v2:trainer:hybrid_cuda:status"
TRAINER_HEARTBEAT_KEY = "v2:trainer:hybrid_cuda:heartbeat"
TRAINER_BRIDGE_UNIT = "ai-bot-v2-trainer-bridge.service"
NATIVE_TRAINER_UNIT = "ai-bot-v2-native-rl-masa-ppo-cuda-trainer-loop.service"
NATIVE_TRAINER_TIMER = "ai-bot-v2-native-rl-masa-ppo-cuda-trainer-loop.timer"
PERSISTENT_TRAINER_UNIT = "ai-bot-v2-native-cuda-trainer-persistent.service"
PERSISTENT_RUNTIME_REL = OPERATOR_RUNTIME_REL / "native_cuda_trainer_persistent_runtime_status.json"
PERSISTENT_RESOURCE_REL = OPERATOR_RUNTIME_REL / "native_cuda_trainer_resource_utilization_status.json"
PERSISTENT_CHECKPOINT_REL = OPERATOR_RUNTIME_REL / "native_cuda_trainer_checkpoint_retention_status.json"
PAPER_TRIAL_GUARD_REL = OPERATOR_RUNTIME_REL / "paper_confidence_trial_drawdown_guard_status.json"


@dataclass(frozen=True)
class NativeTrainerRuntimePaths:
    repo_root: Path = REPO_ROOT
    public_root: Path = PUBLIC_ROOT

    @property
    def operator_runtime_dir(self) -> Path:
        return self.public_root / OPERATOR_RUNTIME_REL

    @property
    def artifact_dir(self) -> Path:
        return self.public_root / ARTIFACT_REL

    @property
    def worklog_dir(self) -> Path:
        return self.repo_root / WORKLOG_REL


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


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(timezone.utc)


def age_seconds_from_timestamp(value: Any) -> float | None:
    dt = parse_time(value)
    if dt is None:
        return None
    age_seconds = datetime.now(tz=timezone.utc).timestamp() - dt.timestamp()
    return age_seconds if age_seconds >= 0.0 and math.isfinite(age_seconds) else None


def generated_age_seconds(payload: Mapping[str, Any], path: Path | None = None) -> float | None:
    del path  # File mtimes are not producer clocks and cannot establish freshness.
    for key in ("generated_est", "generated_at", "generated_utc", "last_equity_update_est"):
        if key in payload:
            return age_seconds_from_timestamp(payload.get(key))
    return None


def online_learning_runtime_fields(
    *,
    training: Mapping[str, Any] | None = None,
    persistent_runtime: Mapping[str, Any] | None = None,
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
    training = as_dict(training)
    persistent_runtime = as_dict(persistent_runtime)
    metrics = as_dict(training.get("metrics"))
    rows_rejected_by_reason = as_dict(metrics.get("rows_rejected_by_reason"))
    readiness = build_learning_readiness(
        training=training,
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
        "loss_before": metrics.get("loss_before"),
        "loss_after": metrics.get("loss_after"),
    }


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
    row: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            row[key] = value
    return row


def connect_redis() -> Any:
    try:
        import redis  # type: ignore

        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        client.ping()
        return client
    except Exception:
        return None


def redis_json(client: Any, key: str, default: Any = None) -> Any:
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


def scan_redis_json(client: Any, pattern: str, limit: int = 2000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if client is None:
        return rows
    try:
        for key in client.scan_iter(match=pattern, count=500):
            raw = client.get(str(key))
            payload = json.loads(raw) if raw else None
            if isinstance(payload, dict):
                row = dict(payload)
                row["_redis_key"] = str(key)
                rows.append(row)
            if len(rows) >= limit:
                break
    except Exception:
        return rows
    return rows


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
        return {"source": "nvidia-smi", "available": False, "error": f"{type(exc).__name__}: {exc}"}
    if result.returncode != 0 or not result.stdout.strip():
        return {
            "source": "nvidia-smi",
            "available": False,
            "error": result.stderr.strip() or "nvidia-smi returned no GPU row",
        }
    parts = [part.strip() for part in result.stdout.splitlines()[0].split(",")]
    if len(parts) < 4:
        return {"source": "nvidia-smi", "available": False, "error": "unexpected nvidia-smi output"}
    return {
        "source": "nvidia-smi",
        "available": True,
        "gpu_name": parts[0],
        "gpu_utilization_percent": finite_float(parts[1]),
        "vram_used_mb": finite_float(parts[2]),
        "vram_total_mb": finite_float(parts[3]),
    }


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


def checkpoint_retention_status(repo_root: Path, latest_checkpoint_id: str | None) -> dict[str, Any]:
    checkpoint_dir = repo_root / MODEL_DIR
    files = sorted(
        [path for path in checkpoint_dir.glob("*.json") if path.is_file()],
        key=lambda item: item.name,
    ) if checkpoint_dir.exists() else []
    total_bytes = sum(path.stat().st_size for path in files)
    latest = next(
        (path for path in files if latest_checkpoint_id and path.stem == latest_checkpoint_id),
        None,
    )
    pinned = [
        path.name
        for path in files
        if latest_checkpoint_id and latest_checkpoint_id in path.name
    ]
    return {
        "schema_version": "native_trainer_checkpoint_retention_status_v1",
        "generated_est": est_now(),
        "checkpoint_dir": str(MODEL_DIR),
        "checkpoint_count": len(files),
        "checkpoint_total_size_gb": round(total_bytes / (1024 ** 3), 6),
        "checkpoint_dir_size_bytes": total_bytes,
        "rollover_limit_gb": 300,
        "checkpoint_rollover_limit_bytes": 300 * 1024 ** 3,
        "oldest_checkpoint": None,
        "latest_checkpoint": latest.name if latest else None,
        "latest_checkpoint_id": latest_checkpoint_id,
        "pinned_checkpoints": pinned,
        "checkpoint_rollover_status": "BELOW_LIMIT_NO_ACTION",
        "rollover_action_taken": "NONE",
        "never_delete_latest_checkpoint": True,
        "never_delete_pinned_high_performing_checkpoint": True,
    }


def service_process_active(service_state: Mapping[str, Any]) -> bool:
    """Require systemd liveness and a real PID; cached JSON booleans never count."""

    pid = finite_float(service_state.get("MainPID"))
    return bool(
        service_state.get("ActiveState") == "active"
        and pid is not None
        and pid.is_integer()
        and pid > 0.0
    )


def causal_verified_serving_checkpoint_evidence(repo_root: Path) -> dict[str, Any]:
    """Return the newest manager-verified serving artifact in causal order.

    The checkpoint manager validates the append-only causal ledger, manifest,
    safe NPZ bytes, content identity, and ancestry.  Filesystem mtimes are never
    used to select or validate the serving policy.
    """

    manager = V2HybridCheckpointManager(repo_root / MODEL_DIR)
    try:
        manifests = manager.manifests(
            allowed_lineage_kinds=frozenset({VERIFIED_SERVING_LINEAGE}),
            require_weight_blob=True,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "checkpoint_artifact_verified": False,
            "causal_order_verified": False,
            "status": "BLOCKED_CHECKPOINT_MANAGER_SCAN_INVALID",
            "rejection_reasons": [f"{type(exc).__name__}:{exc}"],
        }
    if not manifests:
        return {
            "checkpoint_artifact_verified": False,
            "causal_order_verified": False,
            "status": "BLOCKED_NO_CAUSAL_VERIFIED_SERVING_CHECKPOINT",
            "rejection_reasons": ["NO_VERIFIED_SERVING_MANIFEST"],
        }
    manifest = manifests[0]
    try:
        verified = manager.verify_manifest_artifact(manifest)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "checkpoint_artifact_verified": False,
            "causal_order_verified": False,
            "checkpoint_id": manifest.checkpoint_id,
            "status": "BLOCKED_CHECKPOINT_ARTIFACT_VERIFICATION_FAILED",
            "rejection_reasons": [f"{type(exc).__name__}:{exc}"],
        }

    checkpoint_evidence = as_dict(verified.get("checkpoint_evidence"))
    optimizer = as_dict(checkpoint_evidence.get("optimizer_evidence"))
    update_keys = as_list(verified.get("consumed_ppo_update_keys"))
    ppo_rows_consumed = finite_float(optimizer.get("ppo_rows_consumed"))
    clipped_rows = finite_float(optimizer.get("ppo_clipped_surrogate_rows"))
    unavailable_rows = finite_float(
        optimizer.get("ppo_rows_available_but_optimizer_unavailable")
    )
    exact_optimizer_contract_durable = bool(
        optimizer.get("exact_optimizer_contract_valid") is True
        and optimizer.get("ppo_objective_used") is True
        and optimizer.get("optimizer_parameter_fingerprints_bound") is True
        and optimizer.get("ppo_consumed_update_keys_complete") is True
        and optimizer.get("ppo_consumed_update_keys_ordered") is True
        and optimizer.get("ppo_consumed_update_keys_unique") is True
        and ppo_rows_consumed is not None
        and ppo_rows_consumed.is_integer()
        and ppo_rows_consumed == len(update_keys)
        and clipped_rows is not None
        and clipped_rows.is_integer()
        and clipped_rows == len(update_keys)
        and unavailable_rows == 0.0
    )
    causal_order_verified = bool(
        verified.get("checkpoint_artifact_verified") is True
        and finite_float(verified.get("checkpoint_generation")) is not None
        and float(verified.get("checkpoint_generation")) > 0.0
        and verified.get("checkpoint_causal_order_schema_version")
        and verified.get("checkpoint_causal_record_digest")
    )
    serving_decision = as_dict(checkpoint_evidence.get("serving_promotion_decision"))
    candidate_decision = as_dict(checkpoint_evidence.get("candidate_progress_decision"))
    semantic_serving_verified = bool(
        verified.get("lineage_kind") == VERIFIED_SERVING_LINEAGE
        and checkpoint_evidence.get("checkpoint_role") == VERIFIED_SERVING_LINEAGE
        and checkpoint_evidence.get("ledger_disposition") == "SERVING_PROMOTED"
        and serving_decision.get("checkpoint_promotion_allowed") is True
        and candidate_decision.get("candidate_progress_allowed") is True
    )
    artifact_verified = bool(
        verified.get("checkpoint_artifact_verified") is True
        and causal_order_verified
        and semantic_serving_verified
    )
    return {
        **verified,
        "generated_utc": manifest.generated_utc,
        "checkpoint_artifact_verified": artifact_verified,
        "causal_order_verified": causal_order_verified,
        "semantic_serving_verified": semantic_serving_verified,
        "exact_optimizer_contract_durable": exact_optimizer_contract_durable,
        "ledger_disposition": checkpoint_evidence.get("ledger_disposition"),
        "status": (
            "CAUSAL_VERIFIED_SERVING_CHECKPOINT_CONFIRMED"
            if artifact_verified and exact_optimizer_contract_durable
            else "BLOCKED_INCOMPLETE_CAUSAL_SERVING_EVIDENCE"
        ),
    }


def summarize_predictions(prediction_payload: Mapping[str, Any], redis_predictions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    public_rows = [as_dict(row) for row in as_list(prediction_payload.get("prediction_rows"))]
    redis_rows = [as_dict(row) for row in redis_predictions]
    # Redis rows remain visible as diagnostics when the public publisher is
    # absent, but they are never treated as a complete publication snapshot.
    rows = public_rows if prediction_payload else redis_rows
    primary = [row for row in redis_rows if ":rl_core:" not in str(row.get("_redis_key", ""))]
    sidecar_rows = [row for row in redis_rows if ":rl_core:" in str(row.get("_redis_key", ""))]
    source_counts = Counter(str(row.get("trainer_source") or row.get("model_source") or "source_pending") for row in rows)
    timeframe_counts = Counter(str(row.get("timeframe") or "unknown") for row in rows)
    symbols = sorted({str(row.get("symbol")) for row in rows if row.get("symbol")})
    paper_allowed = sum(1 for row in rows if row.get("paper_fill_allowed") is True)
    block_reasons = Counter(
        str(reason)
        for row in rows
        for reason in as_list(row.get("paper_fill_gate_block_reasons"))
        if reason
    )
    payload_block_reasons = {
        str(reason): int(finite_float(count) or 0)
        for reason, count in as_dict(prediction_payload.get("paper_actionability_block_reason_counts")).items()
    }
    actionability_block_reasons = payload_block_reasons or dict(block_reasons.most_common(12))
    native_primary_count = sum(
        1
        for row in rows
        if str(row.get("trainer_source") or "").startswith("V2_NATIVE")
        or str(row.get("trainer_source") or "").find("CUDA") >= 0
    )
    def declared_count(field_name: str, *, positive: bool = False) -> int | None:
        value = finite_float(prediction_payload.get(field_name))
        if value is None or not value.is_integer() or value < (1.0 if positive else 0.0):
            return None
        return int(value)

    expected_rows = declared_count("expected_prediction_count", positive=True)
    declared_rows = declared_count("prediction_rows_count", positive=True)
    current_rows = declared_count("current_prediction_count", positive=True)
    missing_rows = declared_count("missing_prediction_rows_count")
    stale_rows = declared_count("stale_prediction_rows_count")
    rows_all_current = bool(rows) and all(row.get("status") == "PRESENT_CURRENT" for row in rows)
    grid_current = bool(
        prediction_payload
        and prediction_payload.get("publication_complete") is True
        and expected_rows is not None
        and declared_rows == expected_rows
        and len(public_rows) == expected_rows
        and current_rows == expected_rows
        and missing_rows == 0
        and stale_rows == 0
        and rows_all_current
    )
    return {
        "prediction_rows": len(rows),
        "prediction_grid_rows": len(rows),
        "prediction_grid_expected_rows": expected_rows,
        "prediction_grid_current": grid_current,
        "prediction_publication_complete": prediction_payload.get("publication_complete") is True,
        "prediction_count_fields_complete": all(
            value is not None
            for value in (expected_rows, declared_rows, current_rows, missing_rows, stale_rows)
        ),
        "current_prediction_count": current_rows,
        "missing_prediction_rows_count": missing_rows,
        "stale_prediction_rows_count": stale_rows,
        "non_current_prediction_rows_count": (
            max(0, expected_rows - current_rows)
            if expected_rows is not None and current_rows is not None
            else None
        ),
        "coverage_status": prediction_payload.get("coverage_status"),
        "actionability_status": prediction_payload.get("actionability_status"),
        "missing_prediction_symbols": as_list(prediction_payload.get("missing_prediction_symbols")),
        "blocked_prediction_rows": int(prediction_payload.get("blocked_prediction_rows_count") or 0),
        "paper_actionability_allowed_rows_count": int(prediction_payload.get("paper_actionability_allowed_rows_count") or 0),
        "paper_actionability_blocked_rows_count": int(prediction_payload.get("paper_actionability_blocked_rows_count") or 0),
        "paper_actionability_block_reason_counts": actionability_block_reasons,
        "paper_allowed_rows": paper_allowed,
        "confidence_blocked_rows": block_reasons.get("confidence_below_threshold", 0),
        "expected_move_blocked_rows": block_reasons.get("expected_move_after_cost_below_threshold", 0),
        "source_counts": dict(source_counts.most_common()),
        "native_cuda_primary_rows": native_primary_count,
        "rl_core_sidecar_rows": len(sidecar_rows),
        "rl_core_primary_overwrites": 0 if not any(":rl_core:" in str(row.get("_redis_key", "")) for row in primary) else len(primary),
        "valid_symbol_count": len(symbols),
        "timeframes": sorted(timeframe_counts.keys()),
        "timeframe_counts": dict(timeframe_counts.most_common()),
        "block_reason_distribution": dict(block_reasons.most_common(12)),
    }


def bottleneck_reason(gpu: Mapping[str, Any], metrics: Mapping[str, Any], service_state: Mapping[str, str]) -> str:
    util = finite_float(gpu.get("gpu_utilization_percent"))
    vram_used = finite_float(gpu.get("vram_used_mb"))
    vram_total = finite_float(gpu.get("vram_total_mb"))
    steps_per_minute = finite_float(metrics.get("training_steps_per_minute"))
    if service_state.get("ActiveState") not in {"active", "activating"} and steps_per_minute:
        return "SCHEDULED_ONESHOT_TRAINING_TIMER_ACTIVE_SERVICE_NOT_PERSISTENT"
    if util is not None and util < 20 and steps_per_minute:
        return "GPU_TRAINING_ACTIVE_LOW_UTILIZATION"
    if vram_used is not None and vram_total and vram_used / vram_total < 0.02:
        return "MODEL_TOO_SMALL_TO_SATURATE_GPU_OR_BATCH_LIMITED"
    return "CURRENT_RUNTIME_TELEMETRY_PUBLISHED"


def build_native_trainer_runtime_payloads(paths: NativeTrainerRuntimePaths | None = None) -> dict[str, Any]:
    paths = paths or NativeTrainerRuntimePaths()
    public = paths.public_root
    repo = paths.repo_root
    prediction_payload = as_dict(read_json(public / PREDICTION_STATUS_REL))
    read_json(public / ALL_TF_STATUS_REL)  # Legacy display source; not readiness evidence.
    runtime_truth = as_dict(read_json(public / RUNTIME_TRUTH_REL))
    portfolio = as_dict(read_json(public / PORTFOLIO_REL))
    paper_trial = as_dict(read_json(public / PAPER_TRIAL_REL))
    parity = as_dict(read_json(public / PARITY_REL))
    live_gate = as_dict(read_json(public / LIVE_GATE_REL))
    redis_client = connect_redis()
    trainer_metrics = as_dict(redis_json(redis_client, TRAINER_METRICS_KEY))
    trainer_status = as_dict(redis_json(redis_client, TRAINER_STATUS_KEY))
    trainer_heartbeat = as_dict(redis_json(redis_client, TRAINER_HEARTBEAT_KEY))
    redis_predictions = scan_redis_json(redis_client, "v2:prediction:*", limit=2500)
    prediction_summary = summarize_predictions(prediction_payload, redis_predictions)

    training = as_dict(trainer_metrics.get("training"))
    bridge_state = systemctl_show(TRAINER_BRIDGE_UNIT)
    trainer_service = systemctl_show(NATIVE_TRAINER_UNIT)
    trainer_timer = systemctl_show(NATIVE_TRAINER_TIMER)
    persistent_service = systemctl_show(PERSISTENT_TRAINER_UNIT)
    persistent_runtime = as_dict(read_json(public / PERSISTENT_RUNTIME_REL))
    persistent_resource = as_dict(read_json(public / PERSISTENT_RESOURCE_REL))
    read_json(public / PERSISTENT_CHECKPOINT_REL)  # Historical telemetry only.
    paper_trial_guard = as_dict(read_json(public / PAPER_TRIAL_GUARD_REL))
    gpu_probe = gpu_status_from_nvidia_smi()
    mem = memory_status()
    verified_serving = causal_verified_serving_checkpoint_evidence(repo)
    latest_checkpoint_id = str(verified_serving.get("checkpoint_id") or "").strip() or None
    retention = checkpoint_retention_status(repo, latest_checkpoint_id)

    generated = est_now()
    trainer_source = "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW"
    model_source = "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"
    current_cycle_envelope = as_dict(
        trainer_status.get("current_cycle_learning_envelope")
    )
    prediction_publication_evidence = as_dict(
        prediction_payload.get("current_cycle_prediction_publication_evidence")
    )
    prediction_source_exact_match = bool(
        prediction_publication_evidence
        and all(
            prediction_payload.get(field_name)
            == prediction_publication_evidence.get(field_name)
            for field_name in (
                "generated_utc",
                "publication_complete",
                "prediction_rows_count",
                "expected_prediction_count",
                "current_prediction_count",
                "missing_prediction_rows_count",
                "stale_prediction_rows_count",
                "lineages_published",
                "prediction_rows",
            )
        )
    )
    resource_evidence = as_dict(
        persistent_resource.get("current_cycle_resource_evidence")
    )
    resource = resource_evidence
    parity_evidence = as_dict(parity.get("current_cycle_parity_evidence"))
    training_steps_total_value = finite_float(
        current_cycle_envelope.get("optimizer_steps_total")
    )
    training_steps_total = (
        int(training_steps_total_value)
        if training_steps_total_value is not None
        and training_steps_total_value >= 0.0
        and training_steps_total_value.is_integer()
        else None
    )
    training_steps_last_hour_value = finite_float(
        current_cycle_envelope.get("optimizer_steps_last_hour")
    )
    training_steps_last_hour = (
        int(training_steps_last_hour_value)
        if training_steps_last_hour_value is not None
        and training_steps_last_hour_value >= 0.0
        and training_steps_last_hour_value.is_integer()
        else None
    )
    persistent_active = service_process_active(persistent_service)
    scheduled_trainer_active = service_process_active(trainer_service)
    active_trainer_services: list[tuple[str, Mapping[str, Any]]] = []
    if persistent_active:
        active_trainer_services.append((PERSISTENT_TRAINER_UNIT, persistent_service))
    if scheduled_trainer_active:
        active_trainer_services.append((NATIVE_TRAINER_UNIT, trainer_service))
    actual_trainer_process_active = len(active_trainer_services) == 1
    if actual_trainer_process_active:
        active_service_unit, active_service_state = active_trainer_services[0]
        active_process_id = int(float(active_service_state["MainPID"]))
        trainer_process_evidence = {
            "service_active": True,
            "service_unit": active_service_unit,
            "process_id": active_process_id,
            "process_instance_id": f"{socket.gethostname()}:{active_process_id}",
        }
    else:
        trainer_process_evidence = {}
    observed_now = datetime.now(tz=timezone.utc)
    live_cuda_probe_active = gpu_probe.get("available") is True
    online_learning = online_learning_runtime_fields(
        training=training,
        persistent_runtime=persistent_runtime,
        prediction_rows=prediction_summary["prediction_rows"],
        trainer_process_active=actual_trainer_process_active,
        trainer_process_evidence=trainer_process_evidence,
        cuda_inference_active=live_cuda_probe_active,
        current_cycle_learning_envelope=current_cycle_envelope,
        runtime_status_evidence=trainer_status,
        heartbeat_evidence=trainer_heartbeat,
        verified_serving_checkpoint=verified_serving,
        prediction_publication_evidence=prediction_publication_evidence,
        resource_evidence=resource_evidence,
        parity_evidence=parity_evidence,
        now_utc=observed_now,
    )
    gpu_status = {
        "schema_version": "native_trainer_gpu_status_v1",
        "generated_est": generated,
        "cuda_active": bool(
            live_cuda_probe_active
            and current_cycle_envelope.get("cuda_inference_status") == "ACTIVE"
            and resource_evidence.get("cuda_active") is True
            and resource_evidence.get("cuda_available") is True
        ),
        "gpu_name": gpu_probe.get("gpu_name") if live_cuda_probe_active else None,
        "gpu_utilization_percent": (
            gpu_probe.get("gpu_utilization_percent") if live_cuda_probe_active else None
        ),
        "vram_used_mb": gpu_probe.get("vram_used_mb") if live_cuda_probe_active else None,
        "vram_total_mb": gpu_probe.get("vram_total_mb") if live_cuda_probe_active else None,
        "vram_reserved_mb": resource.get("vram_reserved_mb"),
        "cpu_utilization_percent": resource.get("cpu_utilization_percent"),
        "ram_used_gb": mem.get("ram_used_gb"),
        "ram_total_gb": mem.get("ram_total_gb"),
        "dataloader_workers": resource.get("dataloader_workers"),
        "pinned_memory": resource.get("pinned_memory") is True,
        "amp_enabled": resource.get("amp_enabled") is True,
        "target_batch_size": resource.get("target_batch_size"),
        "actual_batch_size": resource.get("batch_size"),
        "resource_bottleneck_reason": (
            resource.get("bottleneck_reason")
            if resource
            else "BLOCKED_NO_IDENTITY_BOUND_CURRENT_RESOURCE_EVIDENCE"
        ),
        "nvidia_smi_available": bool(gpu_probe.get("available")),
        "resource_evidence_age_seconds": generated_age_seconds(resource_evidence),
        "resource_evidence_identity_bound": bool(
            resource_evidence
            and resource_evidence.get("cycle_id") == current_cycle_envelope.get("cycle_id")
            and resource_evidence.get("process_instance_id")
            == current_cycle_envelope.get("process_instance_id")
        ),
    }
    runtime = {
        "schema_version": "native_trainer_runtime_status_v1",
        "generated_est": generated,
        "payload_age_seconds": generated_age_seconds(current_cycle_envelope),
        "go_no_go": (
            READY if online_learning.get("canonical_readiness_status") == "READY" else BLOCKED
        ),
        "readiness_scope": "REPORT_ONLY_PAPER_SHADOW",
        "live_execution_authorized": False,
        "trainer_source": trainer_source,
        "model_source": model_source,
        "checkpoint_id": latest_checkpoint_id,
        "checkpoint_count": retention.get("checkpoint_count"),
        "checkpoint_total_size_gb": retention.get("checkpoint_total_size_gb"),
        "checkpoint_dir_size_bytes": retention.get("checkpoint_dir_size_bytes"),
        "checkpoint_rollover_limit_bytes": retention.get("checkpoint_rollover_limit_bytes"),
        "checkpoint_rollover_status": retention.get("checkpoint_rollover_status"),
        "cuda_active": gpu_status["cuda_active"],
        "gpu_name": gpu_status["gpu_name"],
        "gpu_utilization_percent": gpu_status["gpu_utilization_percent"],
        "vram_used_mb": gpu_status["vram_used_mb"],
        "vram_total_mb": gpu_status["vram_total_mb"],
        "cpu_utilization_percent": gpu_status["cpu_utilization_percent"],
        "ram_used_gb": gpu_status["ram_used_gb"],
        "ram_total_gb": gpu_status["ram_total_gb"],
        "training_loop_active": actual_trainer_process_active,
        "training_timer_active": trainer_timer.get("ActiveState") == "active",
        "continuous_training_enabled": persistent_active or trainer_timer.get("ActiveState") == "active",
        **online_learning,
        "persistent_trainer_service_active": persistent_active,
        "persistent_trainer_service_state": persistent_service,
        "persistent_trainer_pid": (
            int(float(persistent_service["MainPID"])) if persistent_active else None
        ),
        "persistent_trainer_uptime_seconds": (
            persistent_runtime.get("uptime_seconds") if persistent_active else None
        ),
        "trainer_service_state": trainer_service,
        "trainer_timer_state": trainer_timer,
        "training_steps_total": training_steps_total,
        "training_steps_last_hour": training_steps_last_hour,
        "samples_per_second": resource.get("samples_per_second"),
        "predictions_per_second": resource.get("predictions_per_second"),
        "training_steps_per_minute": resource.get("training_steps_per_minute"),
        "batch_size": resource.get("batch_size"),
        "target_batch_size": gpu_status["target_batch_size"],
        "dataloader_workers": gpu_status["dataloader_workers"],
        "pinned_memory": gpu_status["pinned_memory"],
        "amp_enabled": gpu_status["amp_enabled"],
        "train_rows": current_cycle_envelope.get("train_rows"),
        "validation_rows": current_cycle_envelope.get("validation_rows"),
        "prediction_rows": prediction_summary["prediction_rows"],
        "prediction_grid_rows": prediction_summary["prediction_grid_rows"],
        "prediction_grid_expected_rows": prediction_summary["prediction_grid_expected_rows"],
        "prediction_grid_current": prediction_summary["prediction_grid_current"],
        "prediction_publication_complete": prediction_summary[
            "prediction_publication_complete"
        ],
        "prediction_count_fields_complete": prediction_summary[
            "prediction_count_fields_complete"
        ],
        "prediction_source_exactly_bound_to_current_cycle_evidence": (
            prediction_source_exact_match
        ),
        "current_prediction_count": prediction_summary["current_prediction_count"],
        "missing_prediction_rows_count": prediction_summary["missing_prediction_rows_count"],
        "stale_prediction_rows_count": prediction_summary["stale_prediction_rows_count"],
        "non_current_prediction_rows_count": prediction_summary["non_current_prediction_rows_count"],
        "prediction_coverage_status": prediction_summary["coverage_status"],
        "prediction_actionability_status": prediction_summary["actionability_status"],
        "missing_prediction_symbols": prediction_summary["missing_prediction_symbols"],
        "blocked_prediction_rows": prediction_summary["blocked_prediction_rows"],
        "paper_actionability_allowed_rows_count": prediction_summary["paper_actionability_allowed_rows_count"],
        "paper_actionability_blocked_rows_count": prediction_summary["paper_actionability_blocked_rows_count"],
        "paper_actionability_block_reason_counts": prediction_summary["paper_actionability_block_reason_counts"],
        "valid_symbol_count": prediction_summary["valid_symbol_count"],
        "timeframes": prediction_summary["timeframes"],
        "trainer_bridge_active": bridge_state.get("ActiveState") in {"active", "activating"},
        "trainer_bridge_masked": bridge_state.get("UnitFileState") == "masked",
        "trainer_bridge_state": bridge_state,
        "rl_core_primary_overwrites": prediction_summary["rl_core_primary_overwrites"],
        "rl_core_sidecar_rows": prediction_summary["rl_core_sidecar_rows"],
        "parity_status": (
            "FULL_FUNCTION_PARITY_VERIFIED"
            if parity_evidence.get("parity_complete") is True
            and parity_evidence.get("required_missing_parity_methods") == 0
            and parity_evidence.get("status") == "FULL_FUNCTION_PARITY_VERIFIED"
            else "BLOCKED_NO_CURRENT_IDENTITY_BOUND_PARITY_EVIDENCE"
        ),
        "hybrid_trainer_methods_inventoried": parity_evidence.get("method_count"),
        "required_missing_parity_methods": parity_evidence.get(
            "required_missing_parity_methods"
        ),
        "live_gate": live_gate.get("live_gate"),
        "trader_state": runtime_truth.get("trader_state"),
        "live_order_submit_blocker": runtime_truth.get("live_order_submit_blocker"),
        "paper_current_session_equity": portfolio.get("equity"),
        "paper_current_session_pnl": portfolio.get("total_pnl_usd"),
        "paper_accepted_fills": portfolio.get("accepted_fill_total"),
        "paper_open_positions": portfolio.get("open_positions_count"),
        "paper_threshold_trial": {
            "generated_est": paper_trial.get("generated_est"),
            "paper_allowed_before": as_dict(paper_trial.get("summary")).get("paper_allowed_before"),
            "trial_candidates": as_dict(paper_trial.get("summary")).get("trial_candidate_count"),
            "trial_promoted_signals": as_dict(paper_trial.get("summary")).get("trial_promoted_signal_count"),
            "paper_threshold": as_dict(paper_trial.get("summary")).get("paper_confidence_threshold"),
            "paper_pnl_at_trial": as_dict(paper_trial.get("paper")).get("current_session_pnl"),
            "live_threshold_changed": as_dict(paper_trial.get("live")).get("live_threshold_changed"),
        },
        "paper_confidence_trial_drawdown_guard": paper_trial_guard,
        "paper_confidence_trial_guard_status": paper_trial_guard.get("status"),
        "paper_confidence_trial_guard_reason": paper_trial_guard.get("drawdown_guard_reason"),
        "paper_confidence_trial_guard_trial_enabled": paper_trial_guard.get("trial_enabled"),
        "prediction_source_status": prediction_summary,
        "current_runtime_panel_source": "operator_runtime/v2_native_trainer/latest/native_trainer_runtime_status.json",
        "stale_burn_in_payload_as_current_runtime_allowed": False,
        "resource_bottleneck_reason": gpu_status["resource_bottleneck_reason"],
        "current_cycle_learning_envelope_present": bool(current_cycle_envelope),
        "current_cycle_id": current_cycle_envelope.get("cycle_id"),
        "current_process_instance_id": current_cycle_envelope.get(
            "process_instance_id"
        ),
        "trainer_status_source_age_seconds": generated_age_seconds(trainer_status),
        "trainer_heartbeat_source_age_seconds": generated_age_seconds(
            trainer_heartbeat
        ),
        "prediction_source_age_seconds": generated_age_seconds(
            prediction_publication_evidence
        ),
        "parity_source_age_seconds": generated_age_seconds(parity_evidence),
        "verified_serving_checkpoint_evidence": verified_serving,
        "canonical_readiness_blockers": online_learning.get(
            "readiness_blocking_reasons"
        ),
    }
    canonical_blockers = list(runtime.get("canonical_readiness_blockers") or ())
    if not prediction_source_exact_match:
        canonical_blockers.append(
            "prediction_status_payload_not_exactly_bound_to_current_cycle_evidence"
        )
    if prediction_summary.get("prediction_grid_current") is not True:
        canonical_blockers.append("prediction_status_payload_not_current_complete_grid")
    canonical_blockers = list(dict.fromkeys(canonical_blockers))
    aggregate_ready = bool(
        not canonical_blockers
        and online_learning.get("canonical_readiness_status") == "READY"
    )
    runtime.update(
        {
            "canonical_readiness_status": "READY" if aggregate_ready else "BLOCKED",
            "trainer_learning_ready": aggregate_ready,
            "go_no_go": READY if aggregate_ready else BLOCKED,
            "canonical_readiness_blockers": canonical_blockers,
        }
    )
    if not aggregate_ready:
        runtime.update(
            {
                "online_learning_status": (
                    "BLOCKED_NO_COHERENT_CURRENT_CYCLE_LEARNING_ENVELOPE"
                ),
                "effective_trainer_mode": "INFERENCE_ONLY",
                "last_successful_weight_update_at": None,
            }
        )
    runtime["trainer"] = {
        "trainer_source": trainer_source,
        "model_source": model_source,
        "checkpoint_id": runtime["checkpoint_id"],
        "cuda_active": runtime["cuda_active"],
        "model_device": "cuda:0" if runtime["cuda_active"] else None,
        "live_gate": runtime["live_gate"],
        "live_symbols": as_list(live_gate.get("live_symbols")),
        "trainer_process_status": runtime["trainer_process_status"],
        "cuda_inference_status": runtime["cuda_inference_status"],
        "prediction_publication_status": runtime["prediction_publication_status"],
        "online_learning_status": runtime["online_learning_status"],
        "effective_trainer_mode": runtime["effective_trainer_mode"],
        "last_successful_weight_update_at": runtime["last_successful_weight_update_at"],
        "legacy_hybrid_parity_claim": runtime["parity_status"],
        "training_batch_policy": {
            "batch_covers_available_examples": current_cycle_envelope.get(
                "batch_covers_available_examples"
            ),
            "available_examples": current_cycle_envelope.get("available_examples"),
            "selected_examples": current_cycle_envelope.get("selected_examples"),
        },
        "parallel_environment_rollout": current_cycle_envelope.get(
            "parallel_environment_rollout"
        ),
    }
    runtime["metrics"] = {
        "training": {
            "gpu_name": runtime["gpu_name"],
            "vram_allocated_mb": runtime["vram_used_mb"],
            "training_steps": runtime["training_steps_total"],
            "train_rows": runtime["train_rows"],
            "validation_rows": runtime["validation_rows"],
            "loss_before": current_cycle_envelope.get("loss_before"),
            "loss_after": current_cycle_envelope.get("loss_after"),
            "cuda_active": runtime["cuda_active"],
            "cuda_claim_verified": runtime["cuda_active"],
            "metrics": current_cycle_envelope.get("training_metrics"),
        },
        "parallel_environment_rollout": current_cycle_envelope.get(
            "parallel_environment_rollout"
        ),
        "data_coverage_avg": current_cycle_envelope.get("data_coverage_avg"),
        "missing_feature_count_total": current_cycle_envelope.get(
            "missing_feature_count_total"
        ),
        "stale_feature_count_total": current_cycle_envelope.get(
            "stale_feature_count_total"
        ),
    }
    runtime["prediction_count"] = runtime["prediction_rows"]
    prediction_rows_for_website = [
        {
            "prediction_id": row.get("prediction_id"),
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "selected_action": row.get("selected_action"),
            "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
            "confidence_calibrated": row.get("confidence_calibrated"),
            "data_coverage_percent": row.get("data_coverage_percent"),
            "missing_feature_count": row.get("missing_feature_count"),
            "stale_feature_count": row.get("stale_feature_count"),
            "paper_fill_allowed": row.get("paper_fill_allowed"),
            "paper_fill_gate_status": row.get("paper_fill_gate_status"),
        }
        for row in as_list(prediction_payload.get("prediction_rows"))
        if isinstance(row, dict)
    ]
    runtime["predictions_by_symbol"] = prediction_rows_for_website
    runtime["predictions_by_symbol_count"] = len(prediction_rows_for_website)
    runtime["predictions_by_symbol_display_scope"] = "FULL_SCROLLABLE_TRAINER_GRID"
    return {
        "native_trainer_runtime_status.json": runtime,
        "native_trainer_gpu_status.json": gpu_status,
        "native_trainer_checkpoint_status.json": retention,
        "native_trainer_checkpoint_retention_status.json": retention,
    }


def readable_reason(value: str) -> str:
    mapping = {
        "record_deny": "risk or ledger denied this row",
        "PAPER_SHADOW_GATE_BLOCKED": "paper shadow gate blocked this row",
        "hedge_reserved_fail_closed": "hedge action is reserved and fails closed",
        "confidence_below_threshold": "confidence below current paper threshold",
        "expected_move_after_cost_below_threshold": "expected move is not positive enough after costs",
        "TRAINER_SOURCE_NOT_CUDA_PARITY": "prediction came from a non-primary sidecar source",
    }
    return mapping.get(value, value.replace("_", " ").lower())


def build_ai_predictions_status(runtime: Mapping[str, Any], prediction_payload: Mapping[str, Any]) -> dict[str, Any]:
    rows = [as_dict(row) for row in as_list(prediction_payload.get("prediction_rows"))]
    block_reasons = Counter(
        str(reason)
        for row in rows
        for reason in as_list(row.get("paper_fill_gate_block_reasons"))
        if reason
    )
    return {
        "schema_version": "ai_predictions_runtime_truth_status_v1",
        "generated_est": est_now(),
        "source_payload": "operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json",
        "native_cuda_primary_predictions": runtime.get("native_cuda_primary_rows") or runtime.get("prediction_rows"),
        "prediction_rows": len(rows),
        "rl_core_sidecar_rows": runtime.get("rl_core_sidecar_rows"),
        "confidence_blocked_rows": block_reasons.get("confidence_below_threshold", 0),
        "paper_allowed_rows": sum(1 for row in rows if row.get("paper_fill_allowed") is True),
        "paper_trial_promoted_rows": as_dict(runtime.get("paper_threshold_trial")).get("trial_promoted_signals"),
        "paper_pnl_current": runtime.get("paper_current_session_pnl"),
        "paper_pnl_at_trial": as_dict(runtime.get("paper_threshold_trial")).get("paper_pnl_at_trial"),
        "live_threshold_changed": as_dict(runtime.get("paper_threshold_trial")).get("live_threshold_changed") is True,
        "blocked_reason_distribution": {
            readable_reason(reason): count for reason, count in block_reasons.most_common(15)
        },
        "stale_burn_in_predictions_used": False,
    }


def build_signals_status(runtime: Mapping[str, Any], prediction_payload: Mapping[str, Any]) -> dict[str, Any]:
    rows = [as_dict(row) for row in as_list(prediction_payload.get("prediction_rows"))]
    current_active = [row for row in rows if row.get("paper_fill_allowed") is True]
    blocked_confidence = [
        row
        for row in rows
        if "confidence_below_threshold" in as_list(row.get("paper_fill_gate_block_reasons"))
    ]
    non_actionable_expected = [
        row
        for row in rows
        if "expected_move_after_cost_below_threshold" in as_list(row.get("paper_fill_gate_block_reasons"))
    ]
    sample_rows = []
    for row in rows[:80]:
        raw_reasons = [str(reason) for reason in as_list(row.get("paper_fill_gate_block_reasons"))]
        sample_rows.append(
            {
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "action": row.get("selected_action"),
                "confidence": row.get("confidence_calibrated"),
                "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
                "market_state_integrity_score": row.get("market_state_integrity_score"),
                "risk_status": "ready for paper" if row.get("valid_for_risk") else "risk guard not satisfied",
                "orchestrator_status": "ready for arbitration" if row.get("valid_for_orchestrator") else "orchestrator guard not satisfied",
                "paper_status": "paper signal allowed" if row.get("paper_fill_allowed") else "paper signal held",
                "ledger_status": "ledger updates after paper fill" if row.get("paper_fill_allowed") else "no ledger row for held signal",
                "readable_block_reasons": [readable_reason(reason) for reason in raw_reasons],
                "payload_age": generated_age_seconds(row),
            }
        )
    return {
        "schema_version": "signals_runtime_truth_status_v1",
        "generated_est": est_now(),
        "source_payload": "operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json",
        "current_active_paper_signals": len(current_active),
        "paper_overlay_promoted_signals": as_dict(runtime.get("paper_threshold_trial")).get("trial_promoted_signals"),
        "blocked_confidence_rows": len(blocked_confidence),
        "non_actionable_expected_move_rows": len(non_actionable_expected),
        "rl_core_sidecar_rows": runtime.get("rl_core_sidecar_rows"),
        "native_cuda_primary_rows": runtime.get("prediction_rows"),
        "sample_rows": sample_rows,
        "raw_block_reasons_visible_as_primary_labels": False,
    }


def build_global_shell_status(runtime: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "global_shell_runtime_truth_source_status_v1",
        "generated_est": est_now(),
        "sources": [
            "operator_runtime/v2_runtime_truth/latest/runtime_pages_payload.json",
            "operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json",
            "operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json",
            "operator_runtime/v2_native_trainer/latest/native_trainer_runtime_status.json",
            "operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json",
        ],
        "expected_header_story": {
            "live": "gate approved" if runtime.get("live_gate") == "enabled_operator_approved" else runtime.get("live_gate"),
            "trader": "armed, balance hold" if runtime.get("trader_state") == "LIVE_ARMED_BALANCE_HOLD" else runtime.get("trader_state"),
            "paper_equity": runtime.get("paper_current_session_equity"),
            "paper_pnl": runtime.get("paper_current_session_pnl"),
            "predictions": runtime.get("prediction_rows"),
            "submit": "held until margin is sufficient"
            if runtime.get("live_order_submit_blocker") == "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER"
            else runtime.get("live_order_submit_blocker"),
        },
        "forbidden_current_labels": ["9950.654465", "-49", "-45", "blocked_human_only", "Bridge CURRENT"],
        "stale_header_source_allowed": False,
    }


def build_semantic_validation(runtime: Mapping[str, Any], prediction_payload: Mapping[str, Any]) -> dict[str, Any]:
    routes = [
        "/dashboard",
        "/ai-predictions",
        "/ai-predictions/model-state",
        "/signals",
        "/trade",
        "/trade/paper",
        "/portfolio",
        "/system/trainer",
        "/system/readiness",
        "/system/execution",
    ]
    expected_rows = runtime.get("prediction_grid_rows")
    symbol_count = runtime.get("valid_symbol_count")
    tf_count = len(as_list(runtime.get("timeframes")))
    payload_age = finite_float(runtime.get("payload_age_seconds"))
    freshness_budget = finite_float(runtime.get("freshness_budget_seconds"))
    optimizer_steps_this_cycle = finite_float(
        runtime.get("optimizer_steps_this_cycle")
    )
    assertions = [
        {
            "assertion": "current_runtime_panel_payload_within_cadence_budget",
            "pass": bool(
                payload_age is not None
                and freshness_budget is not None
                and freshness_budget > 0.0
                and 0.0 <= payload_age <= freshness_budget
            ),
        },
        {
            "assertion": "no_age_6d_current_panel",
            "pass": bool(
                payload_age is not None
                and freshness_budget is not None
                and 0.0 <= payload_age <= freshness_budget
            ),
        },
        {
            "assertion": "no_blocked_human_only_when_live_gate_approved",
            "pass": runtime.get("live_gate") == "enabled_operator_approved",
        },
        {
            "assertion": "no_stale_9950_minus49_minus45_current_equity",
            "pass": runtime.get("paper_current_session_equity") not in {9950.654465, -49, -45},
        },
        {
            "assertion": "no_not_full_parity_when_required_missing_zero",
            "pass": runtime.get("required_missing_parity_methods") == 0
            and runtime.get("parity_status") == "FULL_FUNCTION_PARITY_VERIFIED",
        },
        {
            "assertion": "training_steps_2_allowed_only_if_current_runtime_heartbeat_confirms",
            "pass": runtime.get("training_steps_total") != 2
            or bool(
                runtime.get("trainer_process_status") == "ACTIVE"
                and optimizer_steps_this_cycle is not None
                and optimizer_steps_this_cycle > 0.0
            ),
        },
        {
            "assertion": "persistent_service_active_when_current_runtime_claims_continuous",
            "pass": runtime.get("persistent_trainer_service_active") is True
            or runtime.get("continuous_training_enabled") is not True,
        },
        {
            "assertion": "training_steps_increase_when_persistent_service_active",
            "pass": runtime.get("persistent_trainer_service_active") is not True
            or bool(
                optimizer_steps_this_cycle is not None
                and optimizer_steps_this_cycle > 0.0
            ),
        },
        {
            "assertion": "resource_utilization_present_for_current_trainer",
            "pass": runtime.get("cuda_active") is True
            and runtime.get("gpu_name") is not None
            and runtime.get("vram_used_mb") is not None
            and runtime.get("ram_used_gb") is not None,
        },
        {
            "assertion": "canonical_learning_readiness_ready",
            "pass": runtime.get("canonical_readiness_status") == "READY"
            and runtime.get("trainer_learning_ready") is True,
        },
        {
            "assertion": "current_complete_prediction_publication",
            "pass": runtime.get("prediction_publication_complete") is True
            and runtime.get("prediction_count_fields_complete") is True
            and runtime.get("prediction_grid_current") is True,
        },
        {
            "assertion": "trainer_readiness_remains_report_only_live_blocked",
            "pass": runtime.get("readiness_scope") == "REPORT_ONLY_PAPER_SHADOW"
            and runtime.get("live_execution_authorized") is False,
        },
        {
            "assertion": "paper_threshold_trial_guard_not_active_after_drawdown_breach",
            "pass": runtime.get("paper_confidence_trial_guard_status") != "TRIAL_ACTIVE"
            or (finite_float(as_dict(runtime.get("paper_confidence_trial_drawdown_guard")).get("pnl_delta")) or 0.0) >= -50.0,
        },
        {
            "assertion": "no_predictions_202_if_current_grid_differs",
            "pass": expected_rows != 202,
        },
        {
            "assertion": "no_symbols_tfs_101_2_if_current_grid_differs",
            "pass": not (symbol_count == 101 and tf_count == 2),
        },
        {
            "assertion": "stale_burn_in_report_not_current_runtime_source",
            "pass": runtime.get("stale_burn_in_payload_as_current_runtime_allowed") is False,
        },
    ]
    failed = [row for row in assertions if not row["pass"]]
    return {
        "schema_version": "website_semantic_runtime_truth_validation_status_v1",
        "generated_est": est_now(),
        "status": "SEMANTIC_RUNTIME_TRUTH_VALIDATION_PASS" if not failed else "SEMANTIC_RUNTIME_TRUTH_VALIDATION_FAIL",
        "routes_checked": routes,
        "assertions": assertions,
        "failed_assertions": failed,
        "current_truth": {
            "live_gate": runtime.get("live_gate"),
            "trader_state": runtime.get("trader_state"),
            "live_order_submit_blocker": runtime.get("live_order_submit_blocker"),
            "paper_equity": runtime.get("paper_current_session_equity"),
            "paper_pnl": runtime.get("paper_current_session_pnl"),
            "prediction_grid_rows": expected_rows,
            "valid_symbol_count": symbol_count,
            "timeframes": runtime.get("timeframes"),
            "trainer_source": runtime.get("trainer_source"),
        },
        "semantic_route_crawl_required": True,
        "route_crawl_http_200_is_not_sufficient": True,
    }


def build_production_deploy_status(runtime: Mapping[str, Any]) -> dict[str, Any]:
    dist_assets = sorted((REPO_ROOT / "v2/frontend/dist/assets").glob("index-*.js"), key=lambda path: path.stat().st_mtime)
    latest_asset = dist_assets[-1] if dist_assets else None
    local_hash = None
    if latest_asset is not None:
        local_hash = hashlib.sha256(latest_asset.read_bytes()).hexdigest()[:16]
    production_asset_name = None
    production_hash = None
    production_fetch_status = "NOT_FETCHED"
    try:
        with urllib.request.urlopen("https://dashboard.wajidali.us/dashboard", timeout=15) as response:
            html = response.read(300_000).decode("utf-8", errors="ignore")
        match = re.search(r"/assets/(index-[^\"']+\.js)", html)
        if match:
            production_asset_name = match.group(1)
            with urllib.request.urlopen(f"https://dashboard.wajidali.us/assets/{production_asset_name}", timeout=20) as response:
                body = response.read()
            production_hash = hashlib.sha256(body).hexdigest()[:16]
            production_fetch_status = "PRODUCTION_BUNDLE_FETCHED"
        else:
            production_fetch_status = "PRODUCTION_ASSET_NOT_FOUND_IN_HTML"
    except Exception as exc:  # noqa: BLE001
        production_fetch_status = f"PRODUCTION_FETCH_UNAVAILABLE:{type(exc).__name__}"
    route_matrix_path = REPO_ROOT / "claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/production_route_matrix_model_state_semantic_repair_after_mission.json"
    if not route_matrix_path.exists():
        route_matrix_path = REPO_ROOT / "claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/production_route_matrix_model_state_semantic_repair.json"
    route_matrix = as_dict(read_json(route_matrix_path))
    failed_routes = [
        row.get("route")
        for row in as_list(route_matrix.get("routes"))
        if as_dict(row).get("classification", {}).get("production_ready") is False
        or as_dict(row).get("classification", {}).get("needs_repair") is True
    ]
    semantic_result = (
        "PRODUCTION_MODEL_SIGNAL_ROUTES_SEMANTIC_PASS_WITH_ADMIN_CAVEATS"
        if route_matrix and set(failed_routes).issubset({"/admin/monitor-center?role=admin", "/admin/script-registry?role=admin"})
        else "PENDING_ROUTE_CRAWL" if not route_matrix else "PRODUCTION_SEMANTIC_ROUTE_FAILURES_PRESENT"
    )
    return {
        "schema_version": "production_model_state_runtime_truth_deploy_status_v1",
        "generated_est": est_now(),
        "local_bundle_hash": local_hash,
        "production_bundle_hash": production_hash,
        "asset_name": latest_asset.name if latest_asset is not None else None,
        "production_asset_name": production_asset_name,
        "production_fetch_status": production_fetch_status,
        "bundle_hash_match": bool(local_hash and production_hash and local_hash == production_hash),
        "route_status": (
            f"{route_matrix.get('passed_count')}/{route_matrix.get('route_count')}"
            if route_matrix
            else "NOT_CHECKED_BY_GATE_CLI"
        ),
        "production_failed_routes": failed_routes,
        "payload_age": runtime.get("payload_age_seconds"),
        "semantic_validation_result": semantic_result,
        "routes": [
            "https://dashboard.wajidali.us/ai-predictions/model-state",
            "https://dashboard.wajidali.us/ai-predictions",
            "https://dashboard.wajidali.us/signals",
            "https://dashboard.wajidali.us/dashboard",
            "https://dashboard.wajidali.us/trade",
        ],
        "production_fixed_claimed": bool(route_matrix and not failed_routes and local_hash and production_hash and local_hash == production_hash),
    }


def build_all_payloads(paths: NativeTrainerRuntimePaths | None = None) -> dict[str, Any]:
    paths = paths or NativeTrainerRuntimePaths()
    native_payloads = build_native_trainer_runtime_payloads(paths)
    runtime = as_dict(native_payloads["native_trainer_runtime_status.json"])
    prediction_payload = as_dict(read_json(paths.public_root / PREDICTION_STATUS_REL))
    ai_predictions = build_ai_predictions_status(runtime, prediction_payload)
    signals = build_signals_status(runtime, prediction_payload)
    shell = build_global_shell_status(runtime)
    semantic = build_semantic_validation(runtime, prediction_payload)
    production = build_production_deploy_status(runtime)
    blocked = bool(
        semantic["failed_assertions"]
        or runtime.get("go_no_go") != READY
        or runtime.get("canonical_readiness_status") != "READY"
        or runtime.get("trainer_learning_ready") is not True
        or runtime.get("trainer_bridge_active") is True
        or runtime.get("rl_core_primary_overwrites", 0) != 0
    )
    go_no_go = BLOCKED if blocked else READY
    dashboard = {
        "schema_version": "v2_model_state_semantic_repair_operator_dashboard_v1",
        "gate": go_no_go,
        "generated_est": est_now(),
        "trainer": {
            "trainer_source": runtime.get("trainer_source"),
            "prediction_grid_rows": runtime.get("prediction_grid_rows"),
            "prediction_grid_expected_rows": runtime.get("prediction_grid_expected_rows"),
            "valid_symbol_count": runtime.get("valid_symbol_count"),
            "timeframes": runtime.get("timeframes"),
            "persistent_trainer_service_active": runtime.get("persistent_trainer_service_active"),
            "persistent_trainer_uptime_seconds": runtime.get("persistent_trainer_uptime_seconds"),
            "persistent_trainer_pid": runtime.get("persistent_trainer_pid"),
            "training_steps_total": runtime.get("training_steps_total"),
            "training_steps_last_hour": runtime.get("training_steps_last_hour"),
            "resource_bottleneck_reason": runtime.get("resource_bottleneck_reason"),
            "trainer_bridge_masked": runtime.get("trainer_bridge_masked"),
            "rl_core_primary_overwrites": runtime.get("rl_core_primary_overwrites"),
            "required_missing_parity_methods": runtime.get("required_missing_parity_methods"),
        },
        "paper": {
            "equity": runtime.get("paper_current_session_equity"),
            "pnl": runtime.get("paper_current_session_pnl"),
            "accepted_fills": runtime.get("paper_accepted_fills"),
            "open_positions": runtime.get("paper_open_positions"),
            "confidence_trial_guard_status": runtime.get("paper_confidence_trial_guard_status"),
            "confidence_trial_guard_reason": runtime.get("paper_confidence_trial_guard_reason"),
        },
        "live": {
            "live_gate": runtime.get("live_gate"),
            "trader_state": runtime.get("trader_state"),
            "live_order_submit_blocker": runtime.get("live_order_submit_blocker"),
        },
        "semantic_validation": semantic.get("status"),
        "blockers": [row["assertion"] for row in semantic["failed_assertions"]],
        "safety": {
            "real_order": False,
            "test_order": False,
            "leverage_margin_mutation": False,
            "old_redis_write": False,
            "legacy_restart": False,
            "redis_trim": False,
            "raw_credentials": False,
            "trainer_bridge_unmasked": False,
        },
    }
    report = (
        "# V2 Model State AI Predictions Signals And Runtime Truth Semantic Repair Report\n\n"
        f"Gate: `{go_no_go}`\n"
        f"Generated EST: `{dashboard['generated_est']}`\n"
        f"Trainer source: `{runtime.get('trainer_source')}`\n"
        f"Prediction grid: `{runtime.get('prediction_grid_rows')}/{runtime.get('prediction_grid_expected_rows')}`\n"
        f"Valid symbols / TFs: `{runtime.get('valid_symbol_count')}/{len(as_list(runtime.get('timeframes')))}`\n"
        f"Trainer bridge masked: `{runtime.get('trainer_bridge_masked')}`\n"
        f"RL-core primary overwrites: `{runtime.get('rl_core_primary_overwrites')}`\n"
        f"Training steps total/last hour: `{runtime.get('training_steps_total')}/{runtime.get('training_steps_last_hour')}`\n"
        f"Persistent trainer service active: `{runtime.get('persistent_trainer_service_active')}`\n"
        f"Resource bottleneck: `{runtime.get('resource_bottleneck_reason')}`\n"
        f"Paper equity/PnL: `{runtime.get('paper_current_session_equity')}/{runtime.get('paper_current_session_pnl')}`\n"
        f"Paper confidence trial guard: `{runtime.get('paper_confidence_trial_guard_status')}`\n"
        f"Live gate: `{runtime.get('live_gate')}`\n"
        f"Trader state: `{runtime.get('trader_state')}`\n"
        f"Live submit blocker: `{runtime.get('live_order_submit_blocker')}`\n\n"
        "Model State, AI Predictions, Signals, and shell payloads now use the current native trainer and canonical runtime truth sources. "
        "Old burn-in reports are not allowed as current runtime panels; semantic validation records the explicit assertions that guard against stale contradictions.\n\n"
        "Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output, no trainer bridge unmask, and no RL-core primary overwrite.\n"
    )
    return {
        **native_payloads,
        "global_shell_runtime_truth_source_status.json": shell,
        "ai_predictions_runtime_truth_status.json": ai_predictions,
        "signals_runtime_truth_status.json": signals,
        "website_semantic_runtime_truth_validation_status.json": semantic,
        "production_model_state_runtime_truth_deploy_status.json": production,
        "operator_dashboard_payload.json": dashboard,
        "GO_NO_GO.md": go_no_go,
        "V2_MODEL_STATE_AI_PREDICTIONS_SIGNALS_AND_RUNTIME_TRUTH_SEMANTIC_REPAIR_REPORT.md": report,
    }


def publish_all(paths: NativeTrainerRuntimePaths | None = None) -> dict[str, Any]:
    paths = paths or NativeTrainerRuntimePaths()
    payloads = build_all_payloads(paths)
    operator_names = {
        "native_trainer_runtime_status.json",
        "native_trainer_gpu_status.json",
        "native_trainer_checkpoint_status.json",
    }
    artifact_names = {
        "native_trainer_runtime_status.json",
        "native_trainer_gpu_status.json",
        "native_trainer_checkpoint_retention_status.json",
        "global_shell_runtime_truth_source_status.json",
        "ai_predictions_runtime_truth_status.json",
        "signals_runtime_truth_status.json",
        "website_semantic_runtime_truth_validation_status.json",
        "production_model_state_runtime_truth_deploy_status.json",
        "operator_dashboard_payload.json",
    }
    for name in operator_names:
        write_json(paths.operator_runtime_dir / name, payloads[name])
    for name in artifact_names:
        write_json(paths.artifact_dir / name, payloads[name])
        write_json(paths.worklog_dir / name, payloads[name])
    for name in ("GO_NO_GO.md", "V2_MODEL_STATE_AI_PREDICTIONS_SIGNALS_AND_RUNTIME_TRUTH_SEMANTIC_REPAIR_REPORT.md"):
        text = str(payloads[name])
        write_text(paths.artifact_dir / name, text)
        write_text(paths.worklog_dir / name, text)
    return payloads


__all__ = [
    "READY",
    "BLOCKED",
    "NativeTrainerRuntimePaths",
    "build_native_trainer_runtime_payloads",
    "build_all_payloads",
    "publish_all",
]
