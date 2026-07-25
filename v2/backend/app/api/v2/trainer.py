"""B4: trainer summary route.

Crosses the subprocess boundary defined in CLAUDE.md "Protected Runtime
Policy" and 06_SAFETY_BOUNDARIES.md "Trainer subprocess boundary". Never
imports trainer modules into the FastAPI process.

Behavior:
- If `V2_TRAINER_MODE=stub` OR `LEGACY_TRAINER_PYTHON` / `LEGACY_BOT_ROOT`
  is missing -> `{ state: 'MISSING_EVIDENCE', ... }`.
- Otherwise: run the trainer_status.py script via subprocess in `status`
  mode and request JSON output. Argv is fixed and inspected by
  `validate_trainer_argv()` -- any forbidden token aborts the call.
- Cache the response in Redis under `v2:trainer:summary` with TTL
  `V2_TRAINER_STATUS_TTL_S` (default 30s).
- Every invocation (allowed AND blocked) is appended to
  `audit:trainer:reads` via `write_audit_trainer_read()`.

Shape (all fields nullable):
{ state, checkpoint_id, uptime_days, win_rate_30d, episodes_total,
  drift_watch_count, drift_alarm_count, promotion_locked,
  promotion_min_role }
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from app.api.v2._common import get_redis, write_audit_trainer_read
from app.api.v2.control_center_status import (
    _current_a_grade_blocker_truth,
    _first,
    _materialization_no_fill_detail,
    _real_trader_readiness_from_a_grade_truth,
)

router = APIRouter(prefix="/trainer", tags=["v2-landing"])

# ---------------------------------------------------------------------------
# Argv allowlist -- single source of truth for the subprocess boundary.
# ---------------------------------------------------------------------------

ALLOWED_MODES: frozenset[str] = frozenset({"status", "export", "read_only"})


class TrainerArgvViolation(Exception):
    """Raised when proposed trainer argv would breach the safety allowlist."""


# Tokens that are categorically forbidden in trainer argv. The actual
# "--mode <something-disallowed>" sequence is validated separately by
# pair-walking the flags so that "--mode status" remains valid.
_FORBIDDEN_FLAGS_EXACT: frozenset[str] = frozenset(
    {
        "--enable-trader",
        "--write",
        "--kill-switch-off",
        "--margin",
    }
)


def validate_trainer_argv(argv: list[str]) -> None:
    """Strict validator. Raises TrainerArgvViolation on any disallowed token.

    Allowed argv shape: [<interpreter>, <script_path>, "--mode", <mode>, "--json"]
    where <mode> in ALLOWED_MODES. The equals form "--mode=<mode>" is also
    accepted when <mode> in ALLOWED_MODES.
    """
    if len(argv) < 3:
        raise TrainerArgvViolation(f"argv_too_short: {argv}")
    # We don't restrict the interpreter or script path here; the caller
    # picks them from env. We DO restrict every flag past the script path.
    flags = argv[2:]

    # First: scan for outright-forbidden tokens.
    for tok in flags:
        if tok in _FORBIDDEN_FLAGS_EXACT:
            raise TrainerArgvViolation(f"forbidden_flag: {tok!r}")
        if tok.startswith("--margin="):
            raise TrainerArgvViolation(f"forbidden_flag: {tok!r}")
        if tok.startswith("--mode="):
            mode_val = tok.split("=", 1)[1].strip()
            if mode_val not in ALLOWED_MODES:
                raise TrainerArgvViolation(f"mode_not_allowed: {tok!r}")

    # Pair-based: `--mode <value>` must be followed by an allowed mode.
    i = 0
    saw_allowed_mode = False
    while i < len(flags):
        tok = flags[i]
        if tok == "--mode":
            if i + 1 >= len(flags):
                raise TrainerArgvViolation("mode_missing_value")
            val = flags[i + 1].strip()
            if val not in ALLOWED_MODES:
                raise TrainerArgvViolation(f"mode_not_allowed: --mode {val!r}")
            saw_allowed_mode = True
            i += 2
            continue
        if tok.startswith("--mode="):
            saw_allowed_mode = True
            i += 1
            continue
        i += 1
    if not saw_allowed_mode:
        raise TrainerArgvViolation("mode_flag_missing")


# ---------------------------------------------------------------------------
# Cache + shape helpers
# ---------------------------------------------------------------------------

CACHE_KEY = "v2:trainer:summary"
CHAMPION_CHALLENGER_STATUS_KEY = "v2:trainer:champion_challenger_status"
HYBRID_CUDA_METRICS_KEY = "v2:trainer:hybrid_cuda:metrics"
PREEMPTIVE_COUNTERFACTUAL_STATUS_KEY = (
    "v2:trainer:preemptive_blocked_counterfactual_status"
)
DEFAULT_TTL_S = 30
DISPLAY_TZ = ZoneInfo("America/New_York")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _display_time_et() -> str:
    return datetime.now(DISPLAY_TZ).isoformat(timespec="seconds")


def _attach_a_grade_blocker_truth(payload: dict[str, Any], r: Any) -> dict[str, Any]:
    out = dict(payload)
    truth = _current_a_grade_blocker_truth(r)
    readiness = _real_trader_readiness_from_a_grade_truth(truth)
    out["real_trader_readiness"] = readiness
    out["a_grade_blocker_truth"] = truth
    out["exact_no_live_reason"] = readiness["exact_no_live_reason"]
    out["readiness_blockers"] = readiness["readiness_blockers"]
    out["top_blockers"] = readiness["readiness_blockers"][:8]
    out["live_ready"] = False
    out["live_submit_allowed"] = False
    return out


def _source_age_seconds(value: Any) -> float | None:
    """Age in seconds of an ISO-8601 source timestamp, or None if unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds())


def _freshness_from_age(age_s: float | None) -> str:
    if age_s is None:
        return "fresh"  # no measurable source age (healthy subprocess path)
    if age_s <= 300:
        return "fresh"
    if age_s <= 1800:
        return "degraded"
    return "stale"


INFERENCE_SIDECAR_HEARTBEAT_KEY = "v2:trainer:heartbeat"
INFERENCE_SIDECAR_STATUS_TEXT_KEY = "v2:trainer:status"
_INFERENCE_SIDECAR_BLOCKED_SAMPLE_LIMIT = 5


def _inference_sidecar_reject_reason_counts(heartbeat: dict[str, Any]) -> dict[str, int]:
    """Aggregate trust-gate reject reasons across symbols (bounded, counts only)."""
    counts: dict[str, int] = {}
    rejections = heartbeat.get("trust_gate_rejections")
    if isinstance(rejections, list) and rejections:
        for row in rejections:
            if not isinstance(row, dict):
                continue
            reasons = row.get("reject_reasons")
            if not isinstance(reasons, list):
                continue
            for reason in reasons:
                if reason in (None, ""):
                    continue
                key = str(reason)
                counts[key] = counts.get(key, 0) + 1
        return counts
    # Fallback: parse "SYMBOL:TRUST_GATE_REJECTED:reason1,reason2" strings.
    blocked = heartbeat.get("predictions_blocked")
    if isinstance(blocked, list):
        for entry in blocked:
            parts = str(entry).split(":", 2)
            if len(parts) < 3:
                continue
            for reason in parts[2].split(","):
                reason = reason.strip()
                if reason:
                    counts[reason] = counts.get(reason, 0) + 1
    return counts


def _read_redis_text(r: Any, key: str) -> str | None:
    if r is None:
        return None
    try:
        raw = r.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    text = str(raw).strip()
    if not text or text.startswith("{") or text.startswith("["):
        return None
    return text


def _attach_inference_sidecar_status(payload: dict[str, Any], r: Any) -> dict[str, Any]:
    """Expose the RL-core inference sidecar's trust-gate blockers on /trainer/status.

    Source keys are the stable read-only v2:trainer:heartbeat / v2:trainer:status
    pair written by v2_rl_core_inference_loop — NOT the held profiled-publisher
    prediction keys. Additive; never overwrites existing shape fields.
    """
    out = dict(payload)
    heartbeat = _read_redis_json(r, INFERENCE_SIDECAR_HEARTBEAT_KEY)
    status_text = _read_redis_text(r, INFERENCE_SIDECAR_STATUS_TEXT_KEY)
    if not heartbeat and status_text is None:
        out["inference_sidecar"] = {
            "available": False,
            "reason": "INFERENCE_SIDECAR_HEARTBEAT_MISSING",
            "source_keys": [
                INFERENCE_SIDECAR_HEARTBEAT_KEY,
                INFERENCE_SIDECAR_STATUS_TEXT_KEY,
            ],
        }
        return out
    blocked = heartbeat.get("predictions_blocked")
    blocked_list = blocked if isinstance(blocked, list) else []
    symbols = heartbeat.get("symbols")
    heartbeat_age = _source_age_seconds(
        heartbeat.get("finished_at") or heartbeat.get("started_at")
    )
    out["inference_sidecar"] = {
        "available": True,
        "schema_version": "trainer_inference_sidecar_v1",
        "worker_id": heartbeat.get("worker_id"),
        "role": heartbeat.get("role"),
        "classification": heartbeat.get("classification") or status_text,
        "status_text": status_text,
        "started_at": heartbeat.get("started_at"),
        "finished_at": heartbeat.get("finished_at"),
        "heartbeat_age_seconds": (
            round(heartbeat_age, 1) if heartbeat_age is not None else None
        ),
        "timeframe": heartbeat.get("timeframe"),
        "symbols_count": len(symbols) if isinstance(symbols, list) else None,
        "predictions_count": heartbeat.get("predictions_count"),
        "trust_gate_rejection_count": heartbeat.get("trust_gate_rejection_count"),
        "trust_gate_reject_reason_counts": _inference_sidecar_reject_reason_counts(
            heartbeat
        ),
        "trust_gate_blocked_sample": [
            str(entry)
            for entry in blocked_list[:_INFERENCE_SIDECAR_BLOCKED_SAMPLE_LIMIT]
        ],
        "checkpoint_blocker": heartbeat.get("checkpoint_blocker"),
        "checkpoint_weight_status": heartbeat.get("checkpoint_weight_status"),
        "checkpoint_evidence_status": heartbeat.get("checkpoint_evidence_status"),
        "checkpoint_id": heartbeat.get("checkpoint_id"),
        "v2_prediction_keys_written_count": heartbeat.get(
            "v2_prediction_keys_written_count"
        ),
        "production_signal_only": heartbeat.get("production_signal_only"),
        "routes_to_orchestrator": heartbeat.get("routes_to_orchestrator"),
        "routes_to_risk_gateway": heartbeat.get("routes_to_risk_gateway"),
        "sidecar_prediction_namespace": heartbeat.get(
            "sidecar_prediction_namespace"
        ),
        "primary_prediction_owner": heartbeat.get("primary_prediction_owner"),
        "source_keys": [
            INFERENCE_SIDECAR_HEARTBEAT_KEY,
            INFERENCE_SIDECAR_STATUS_TEXT_KEY,
        ],
        "live_gate": heartbeat.get("live_gate") or "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
    }
    return out


def _with_control_center_contract(
    payload: dict[str, Any],
    *,
    source: str,
    redis_client: Any | None = None,
) -> dict[str, Any]:
    out = dict(payload)
    state = str(out.get("state") or "").upper()
    # Honest freshness: when the shape carries the underlying evidence timestamp
    # (e.g. the Redis prediction fallback), grade freshness by its real age rather
    # than hardcoding staleness=0/fresh — otherwise a trainer that is DOWN and
    # serving 45h-old fallback evidence is reported as ACTIVE + fresh.
    source_age = _source_age_seconds(out.pop("_source_generated_utc", None))
    freshness = _freshness_from_age(source_age)
    if state in {"", "MISSING_EVIDENCE"}:
        data_quality = "partial"
    elif freshness == "stale":
        data_quality = "stale"
    elif freshness == "degraded":
        data_quality = "degraded"
    else:
        data_quality = "fresh"
    # A fallback that is genuinely stale should not keep an ACTIVE state label.
    if freshness == "stale" and state == "ACTIVE_REDIS_EVIDENCE":
        state = "STALE_REDIS_EVIDENCE"
        out["state"] = state
    out["schema_version"] = str(out.get("schema_version") or "trainer_status_v2")
    out["generated_at_utc"] = _utc_now()
    out["generated_at_et"] = _display_time_et()
    out["source"] = source
    out["staleness_seconds"] = round(source_age, 3) if source_age is not None else 0
    out["freshness_status"] = freshness
    out["canonical_owner"] = "/api/v2/trainer/status"
    out["live_gate"] = "blocked_human_only"
    out["places_real_order"] = False
    out["routes_to_live"] = False
    out["data_quality_status"] = data_quality
    out = _attach_inference_sidecar_status(out, redis_client)
    out = _attach_a_grade_blocker_truth(out, redis_client)
    return out


def _ttl_seconds() -> int:
    raw = os.environ.get("V2_TRAINER_STATUS_TTL_S", "").strip()
    if not raw:
        return DEFAULT_TTL_S
    try:
        v = int(raw)
        return v if v > 0 else DEFAULT_TTL_S
    except ValueError:
        return DEFAULT_TTL_S


def _empty_shape(state: str) -> dict[str, Any]:
    return {
        "state": state,
        "checkpoint_id": None,
        "uptime_days": None,
        "win_rate_30d": None,
        "episodes_total": None,
        "drift_watch_count": None,
        "drift_alarm_count": None,
        "promotion_locked": None,
        "promotion_min_role": None,
        "champion_challenger_status": _missing_champion_challenger_status(),
    }


def _read_redis_json(r: Any, key: str) -> dict[str, Any]:
    if r is None:
        return {}
    try:
        raw = r.get(key)
    except Exception:
        return {}
    if raw is None:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_metric(metrics: dict[str, Any], training: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in metrics and metrics[key] is not None:
            return metrics[key]
        if key in training and training[key] is not None:
            return training[key]
    return None


def _numeric_metric(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if value == value and value not in {float("inf"), float("-inf")} else None
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _positive_metric(value: Any) -> bool:
    parsed = _numeric_metric(value)
    return parsed is not None and float(parsed) > 0.0


def _attach_hybrid_cuda_learning_status(shape: dict[str, Any], r: Any) -> dict[str, Any]:
    """Attach current V2 trainer learning/PPO evidence from Redis.

    This route must remain a read-only status surface.  The trainer runtime
    already publishes the metrics; the API should not report inference as
    learning or leave PPO fields null when the runtime has explicit values.
    """
    payload = _read_redis_json(r, HYBRID_CUDA_METRICS_KEY)
    if not payload:
        return shape

    out = dict(shape)
    training = _dict_value(payload.get("training"))
    metrics = _dict_value(training.get("metrics"))
    checkpoint = _dict_value(payload.get("checkpoint"))
    checkpoint_load = _dict_value(payload.get("checkpoint_load"))

    ppo_on_policy_rows = _numeric_metric(
        _first_metric(metrics, training, "ppo_on_policy_rows")
    )
    ppo_rows_rejected = _numeric_metric(
        _first_metric(metrics, training, "ppo_rows_rejected_missing_on_policy_fields")
    )
    ppo_objective_used = (
        _first_metric(metrics, training, "ppo_objective_used") is True
    )
    outcome_supervised_update_used = (
        _first_metric(metrics, training, "outcome_supervised_update_used") is True
    )
    parameter_hash_before = _first_metric(metrics, training, "parameter_hash_before")
    parameter_hash_after = _first_metric(metrics, training, "parameter_hash_after")
    weight_delta_norm = _first_metric(metrics, training, "weight_delta_norm")
    weights_updating = bool(
        parameter_hash_before
        and parameter_hash_after
        and parameter_hash_before != parameter_hash_after
        and _positive_metric(weight_delta_norm)
    )
    feedback_rows = _numeric_metric(
        _first_metric(metrics, training, "feedback_rows_entered_batch")
    )
    trusted_replay_rows = _numeric_metric(
        _first_metric(metrics, training, "trusted_replay_rows_loaded")
    )
    learning_active = bool(
        weights_updating
        or ppo_objective_used
        or outcome_supervised_update_used
        or _positive_metric(_first_metric(metrics, training, "optimizer_steps_this_cycle"))
    )

    ppo_status = {
        "schema_version": "trainer_status_ppo_runtime_v1",
        "source": f"redis:{HYBRID_CUDA_METRICS_KEY}",
        "ppo_objective_used": ppo_objective_used,
        "ppo_clipped_surrogate_active": ppo_objective_used,
        "ppo_value_entropy_active": (
            _first_metric(metrics, training, "ppo_value_loss") is not None
            and _first_metric(metrics, training, "ppo_entropy") is not None
        ),
        "ppo_on_policy_rows": ppo_on_policy_rows,
        "ppo_rows_consumed": ppo_on_policy_rows if ppo_objective_used else 0,
        "ppo_rows_pending": 0 if ppo_objective_used else ppo_on_policy_rows,
        "ppo_rows_rejected_missing_on_policy_fields": ppo_rows_rejected,
        "ppo_requires_on_policy_fields": (
            _first_metric(metrics, training, "ppo_requires_on_policy_fields") is not False
        ),
        "ppo_policy_loss": _first_metric(metrics, training, "ppo_policy_loss"),
        "ppo_value_loss": _first_metric(metrics, training, "ppo_value_loss"),
        "ppo_entropy": _first_metric(metrics, training, "ppo_entropy"),
        "exact_blocker": (
            None
            if ppo_objective_used
            else "NO_ON_POLICY_PPO_ROWS_AVAILABLE_OUTCOME_SUPERVISED_ACTIVE"
        ),
        "off_policy_rows_reported_as_ppo": False,
    }
    learning_status = {
        "schema_version": "trainer_status_learning_runtime_v1",
        "source": f"redis:{HYBRID_CUDA_METRICS_KEY}",
        "learning_active": learning_active,
        "weights_updating": weights_updating,
        "learning_update_lane": _first_metric(metrics, training, "learning_update_lane"),
        "outcome_supervised_update_used": outcome_supervised_update_used,
        "feedback_rows_consumed": feedback_rows,
        "trusted_replay_rows_loaded": trusted_replay_rows,
        "loss_before": _first_metric(metrics, training, "loss_before"),
        "loss_after": _first_metric(metrics, training, "loss_after"),
        "optimizer_steps_this_cycle": _first_metric(
            metrics, training, "optimizer_steps_this_cycle"
        ),
        "optimizer_steps_last_hour": _first_metric(
            metrics, training, "optimizer_steps_last_hour"
        ),
        "optimizer_steps_total": _first_metric(metrics, training, "optimizer_steps_total"),
        "parameter_hash_before": parameter_hash_before,
        "parameter_hash_after": parameter_hash_after,
        "weight_delta_norm": weight_delta_norm,
        "last_successful_weight_update_at": _first_metric(
            metrics, training, "last_successful_weight_update_at"
        ),
        "checkpoint_hash": _first_metric(metrics, training, "checkpoint_hash")
        or payload.get("checkpoint_hash"),
        "checkpoint_id": checkpoint.get("checkpoint_id") or out.get("checkpoint_id"),
        "checkpoint_reload_verified": payload.get("checkpoint_reload_verified") is True
        or checkpoint_load.get("load_status") == "LOADED",
        "checkpoint_weight_blob_written": _first_metric(
            metrics, training, "checkpoint_weight_blob_written"
        )
        is True
        or checkpoint.get("weight_blob_written") is True,
        "uses_expected_move_as_realized_reward": _first_metric(
            metrics, training, "uses_expected_move_as_realized_reward"
        )
        is True,
    }

    out["trainer_learning_status"] = learning_status
    out["ppo_runtime_status"] = ppo_status

    # Top-level aliases keep dashboard/iOS cards from treating learning/PPO as
    # null while preserving the detailed nested contracts above.
    out["learning_active"] = learning_active
    out["weights_updating"] = weights_updating
    out["last_training_step"] = learning_status["last_successful_weight_update_at"]
    out["checkpoint_hash"] = learning_status["checkpoint_hash"]
    out["checkpoint_reload_verified"] = learning_status["checkpoint_reload_verified"]
    out["feedback_rows_consumed"] = feedback_rows
    out["trusted_replay_rows_loaded"] = trusted_replay_rows
    out["PPO_clipped_surrogate_active"] = ppo_status["ppo_clipped_surrogate_active"]
    out["PPO_value_entropy_active"] = ppo_status["ppo_value_entropy_active"]
    out["PPO_rows_consumed"] = ppo_status["ppo_rows_consumed"]
    out["PPO_rows_pending"] = ppo_status["ppo_rows_pending"]
    out["PPO_policy_loss"] = ppo_status["ppo_policy_loss"]
    out["PPO_value_loss"] = ppo_status["ppo_value_loss"]
    out["PPO_entropy"] = ppo_status["ppo_entropy"]
    out["PPO_exact_blocker"] = ppo_status["exact_blocker"]
    return out


def _latest_scheduled_pretrain_report() -> dict[str, Any] | None:
    """Newest scheduled-pretrain flywheel report (offline train + H2L gate)."""
    try:
        # trainer.py lives at v2/backend/app/api/v2/ -> repo root is 5 levels up.
        repo_root = Path(__file__).resolve().parents[5]
        reports = sorted(
            (repo_root / "claude_worklog" / "trainer_atlas").glob("scheduled_pretrain_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not reports:
            return None
        return json.loads(reports[0].read_text())
    except Exception:  # pragma: no cover - status surface must never fail the route
        return None


_PROFILED_RESEARCH_STATUS_PATH = os.environ.get(
    "V2_TRAINER_PROFILED_RESEARCH_STATUS_PATH",
    "/home/wali/ai_bot_local_data/v2_native_trainer/local_profiled_research_v1/status.json",
)


def _read_profiled_research_cuda_runtime() -> dict[str, Any] | None:
    """Read the running profiled-research trainer's ``cuda_runtime`` block.

    The RTX 5080 GPU telemetry is written to the trainer's ``status.json`` on
    disk, but the legacy gpu_runtime builder reads ``v2:trainer:hybrid_cuda:status``
    which the profiled-research trainer never populates — so the GPU was invisible
    to every UI even though the block exists. Read-only file read; failure-safe.
    """
    try:
        p = Path(_PROFILED_RESEARCH_STATUS_PATH)
        if not p.is_file():
            return None
        data = json.loads(p.read_text())
        cr = data.get("cuda_runtime") if isinstance(data, dict) else None
        return cr if isinstance(cr, dict) else None
    except Exception:  # noqa: BLE001 - telemetry read must never break the route
        return None


def _attach_model_identity_status(shape: dict[str, Any], r: Any) -> dict[str, Any]:
    """Attach model-identity runtime truths (WI-1/WI-2 era) from Redis + reports.

    The trainer runtime publishes input_dim / feature_dim / model_architecture
    (incl. the temporal encoder) to ``v2:trainer:hybrid_cuda:status``; the offline
    pretrain flywheel writes its H2L Sortino/CVaR gate result to a report file.
    Without this attach the status route silently drops all of it and GUI slots
    like "Tensor input dim" / "Feature count" render as pending.
    """
    out = dict(shape)
    payload = _read_redis_json(r, TRAINER_HYBRID_CUDA_STATUS_KEY) or {}
    arch = _dict_value(payload.get("model_architecture"))
    input_dim = payload.get("input_dim") or arch.get("input_dim")
    if input_dim is not None:
        out["input_dim"] = input_dim
    if payload.get("feature_dim") is not None:
        # feature_dim == len(FEATURE_SPEC): the model's base feature count.
        out["feature_count"] = payload.get("feature_dim")
    if payload.get("feature_schema_status") is not None:
        out["feature_schema_status"] = payload.get("feature_schema_status")
    if arch:
        out["model_architecture"] = arch
        out["temporal_encoder"] = arch.get("temporal_encoder") or ""
        out["temporal_encoder_enabled"] = bool(arch.get("temporal_encoder_enabled"))
        out["temporal_seq_len"] = arch.get("temporal_seq_len") or 0
    for key in ("model_id", "checkpoint_id", "checkpoint_source"):
        if not out.get(key) and payload.get(key):
            out[key] = payload.get(key)

    # ── GPU / throughput telemetry (RTX runtime), model-edge backtest, runtime
    # mode and validation metrics. These are published to the status key but were
    # never surfaced by this read-only route, so the AI page could not show them.
    gpu = _dict_value(payload.get("cuda_cpu_resource_utilization"))
    if gpu:
        backtest = _dict_value(gpu.get("policy_backtest"))
        vram_target = _dict_value(gpu.get("vram_target_mb"))
        out["gpu_runtime"] = {
            "schema_version": "trainer_status_gpu_runtime_v1",
            "source": f"redis:{TRAINER_HYBRID_CUDA_STATUS_KEY}",
            "gpu_name": gpu.get("gpu_name"),
            "cuda_available": gpu.get("cuda_available"),
            "model_device": payload.get("model_device"),
            "current_vram_used_mb": _numeric_metric(gpu.get("current_vram_used_mb")),
            "vram_reserved_mb": _numeric_metric(gpu.get("vram_reserved_mb")),
            "vram_cap_mb": _numeric_metric(vram_target.get("cap")),
            "gpu_utilization_limit_percent": _numeric_metric(vram_target.get("gpu_utilization_limit_percent")),
            "gpu_train_time_ms": _numeric_metric(gpu.get("gpu_train_time_ms")),
            "data_loader_time_ms": _numeric_metric(gpu.get("data_loader_time_ms")),
            "backtest_rows_per_second": _numeric_metric(gpu.get("backtest_rows_per_second")),
            "throughput_predictions_per_second": _numeric_metric(gpu.get("throughput_predictions_per_second")),
            "training_steps_per_minute": _numeric_metric(gpu.get("training_steps_per_minute")),
            "mixed_precision_enabled": gpu.get("mixed_precision_enabled"),
            "oom_count": _numeric_metric(gpu.get("oom_count")),
            "target_batch_size": _numeric_metric(gpu.get("target_batch_size")),
            "actual_batch_size": _numeric_metric(gpu.get("actual_batch_size")),
            "cpu_prep_bottleneck": _dict_value(payload.get("training_batch_policy")).get("cpu_prep_bottleneck"),
        }
        if backtest:
            out["model_edge_backtest"] = {
                "schema_version": "trainer_status_model_edge_backtest_v1",
                "source": f"redis:{TRAINER_HYBRID_CUDA_STATUS_KEY}",
                "win_rate": _numeric_metric(backtest.get("win_rate")),
                "expectancy_after_cost_bps": _numeric_metric(backtest.get("expectancy_after_cost_bps")),
                "profit_factor_proxy": _numeric_metric(backtest.get("profit_factor_proxy")),
                "rows_evaluated": _numeric_metric(backtest.get("rows_evaluated")),
                "a_plus_readiness_signal": backtest.get("a_plus_readiness_signal"),
                "evidence_class": backtest.get("evidence_class"),
                "status": backtest.get("status"),
            }
    # RTX 5080 GPU telemetry from the RUNNING profiled-research trainer's
    # status.json (the gpu block above reads a Redis key the trainer never sets).
    _cuda_runtime = _read_profiled_research_cuda_runtime()
    if _cuda_runtime:
        _allocated = _cuda_runtime.get("memory_allocated_bytes")
        out["cuda_runtime"] = {
            "schema_version": "trainer_status_cuda_runtime_v1",
            "source": "file:local_profiled_research_v1/status.json",
            "gpu_name": _cuda_runtime.get("gpu_name"),
            "cuda_available": _cuda_runtime.get("cuda_available"),
            "compute_capability": _cuda_runtime.get("compute_capability"),
            "torch_version": _cuda_runtime.get("torch_version"),
            "torch_cuda_version": _cuda_runtime.get("torch_cuda_version"),
            "device_count": _cuda_runtime.get("device_count"),
            "memory_total_bytes": _cuda_runtime.get("memory_total_bytes"),
            "memory_free_bytes": _cuda_runtime.get("memory_free_bytes"),
            "memory_allocated_bytes": _allocated,
            "memory_reserved_bytes": _cuda_runtime.get("memory_reserved_bytes"),
            "peak_memory_allocated_bytes": _cuda_runtime.get("peak_memory_allocated_bytes"),
            # GPU present + available but zero memory allocated == idle because the
            # trainer is data-starved (distinct from "no GPU present").
            "gpu_idle_data_starved": bool(_cuda_runtime.get("cuda_available")) and (_allocated or 0) == 0,
        }
        if not out.get("gpu_runtime") and _cuda_runtime.get("cuda_available") is not None:
            out["gpu_runtime"] = {
                "schema_version": "trainer_status_gpu_runtime_v1",
                "source": "file:local_profiled_research_v1/status.json",
                "gpu_name": _cuda_runtime.get("gpu_name"),
                "cuda_available": _cuda_runtime.get("cuda_available"),
                "current_vram_used_mb": round((_allocated or 0) / 1e6, 1),
                "vram_cap_mb": round((_cuda_runtime.get("memory_total_bytes") or 0) / 1e6, 1),
            }
    learning_metrics = _dict_value(payload.get("learning_metrics"))
    out["runtime_mode"] = {
        "schema_version": "trainer_status_runtime_mode_v1",
        "source": f"redis:{TRAINER_HYBRID_CUDA_STATUS_KEY}",
        "effective_trainer_mode": payload.get("effective_trainer_mode"),
        "online_learning_status": payload.get("online_learning_status"),
        "cuda_inference_status": payload.get("cuda_inference_status"),
        "trainer_process_status": payload.get("trainer_process_status"),
        "prediction_publication_status": payload.get("prediction_publication_status"),
        "prediction_examples_built": _numeric_metric(payload.get("prediction_examples_built")),
        "prediction_failure_count": _numeric_metric(payload.get("prediction_failure_count")),
        "replay_buffer_size": _numeric_metric(payload.get("replay_buffer_size")),
        "replay_buffer_limit": _numeric_metric(payload.get("replay_buffer_limit")),
        "symbols_count": _numeric_metric(payload.get("symbols_count")),
        "timeframes": payload.get("timeframes") if isinstance(payload.get("timeframes"), list) else None,
        "examples_built": _numeric_metric(payload.get("examples_built")),
        "paper_shadow_only": payload.get("paper_shadow_only"),
        "checkpoint_promoted_this_cycle": payload.get("checkpoint_promoted_this_cycle"),
        "checkpoint_promotion_reason": payload.get("checkpoint_promotion_reason"),
    }
    if learning_metrics:
        out["learning_metrics_extra"] = {
            "schema_version": "trainer_status_learning_metrics_extra_v1",
            "source": f"redis:{TRAINER_HYBRID_CUDA_STATUS_KEY}",
            "train_val_generalization_gap": _numeric_metric(learning_metrics.get("train_val_generalization_gap")),
            "validation_loss_delta": _numeric_metric(learning_metrics.get("validation_loss_delta")),
            "validation_supervised_loss": _numeric_metric(learning_metrics.get("validation_supervised_loss")),
            "validation_improved": learning_metrics.get("validation_improved"),
            "overfit_gap_warning": learning_metrics.get("overfit_gap_warning"),
            "expected_move_loss": _numeric_metric(learning_metrics.get("expected_move_loss")),
            "masa_loss": _numeric_metric(learning_metrics.get("masa_loss")),
            "confidence_loss": _numeric_metric(learning_metrics.get("confidence_loss")),
            "entropy_coefficient": _numeric_metric(learning_metrics.get("entropy_coefficient")),
        }

    pretrain = _latest_scheduled_pretrain_report()
    if pretrain:
        h2h = _dict_value(pretrain.get("head_to_head"))
        # The H2L risk gate reports under risk_adjusted_validation.gate.
        risk = _dict_value(_dict_value(h2h.get("risk_adjusted_validation")).get("gate"))
        out["offline_pretrain_status"] = {
            "schema_version": "trainer_status_offline_pretrain_v1",
            "source": "file:claude_worklog/trainer_atlas/scheduled_pretrain_*.json",
            "generated_utc": pretrain.get("generated_utc"),
            "phase": pretrain.get("phase"),
            "promoted": pretrain.get("promoted"),
            "auto_promote": pretrain.get("auto_promote"),
            "require_risk_gate": pretrain.get("require_risk_gate"),
            "duration_seconds": pretrain.get("duration_seconds"),
            "h2l_decision": h2h.get("decision"),
            "h2l_input_dim": h2h.get("input_dim"),
            "risk_gate": risk or None,
            "sortino_offline": risk.get("offline_sortino") if risk else None,
            "sortino_live": risk.get("live_sortino") if risk else None,
            "cvar_offline": risk.get("offline_cvar") if risk else None,
            "cvar_live": risk.get("live_cvar") if risk else None,
        }
    return out


def _missing_champion_challenger_status() -> dict[str, Any]:
    return {
        "schema_version": "v2_trainer_champion_challenger_status_v1",
        "status": "MISSING_RUNTIME_EVIDENCE",
        "available": False,
        "source": f"redis:{CHAMPION_CHALLENGER_STATUS_KEY}",
        "redis_key": CHAMPION_CHALLENGER_STATUS_KEY,
        "best_challenger_id": None,
        "promotion_allowed": False,
        "promotion_reason": "runtime key missing",
        # Strict train-row telemetry (Phase 1) — honest-empty defaults that match
        # the live schema so consumers never see a missing key vs a real None.
        "train_rows": None,
        "last_terminal_train_rows": None,
        "last_successful_train_rows": None,
        "paper_train_rows_required": 100,
        "paper_train_rows_remaining": None,
        "strict_champion_min_train_rows": 1000,
        "strict_train_rows_required": 1000,
        "strict_train_rows_remaining": None,
        "current_candidate_rows": None,
        "current_admitted_rows": None,
        "current_rejected_rows": None,
        "current_manifest_candidate_rows": None,
        "current_manifest_admitted_rows": None,
        "current_manifest_rejected_rows": None,
        "label_unavailable_rows": None,
        "cost_unavailable_rows": None,
        "duplicate_rows": None,
        "pit_rejected_rows": None,
        "latest_unclosed_rejected_rows": None,
        "admission_yield_ratio": None,
        "estimated_commits_needed": None,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _read_champion_challenger_status(r: Any) -> dict[str, Any]:
    if r is None:
        return _missing_champion_challenger_status()
    try:
        raw = r.get(CHAMPION_CHALLENGER_STATUS_KEY)
    except Exception:
        return _missing_champion_challenger_status()
    if raw is None:
        return _missing_champion_challenger_status()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        missing = _missing_champion_challenger_status()
        missing["status"] = "INVALID_RUNTIME_EVIDENCE"
        missing["promotion_reason"] = "runtime key is not valid JSON"
        return missing
    if not isinstance(payload, dict):
        missing = _missing_champion_challenger_status()
        missing["status"] = "INVALID_RUNTIME_EVIDENCE"
        missing["promotion_reason"] = "runtime key JSON is not an object"
        return missing
    out = dict(payload)
    out.setdefault("schema_version", "v2_trainer_champion_challenger_status_v1")
    out.setdefault("source", f"redis:{CHAMPION_CHALLENGER_STATUS_KEY}")
    out.setdefault("redis_key", CHAMPION_CHALLENGER_STATUS_KEY)
    out["available"] = True
    out["promotion_allowed"] = out.get("promotion_allowed") is True
    out.setdefault("promotion_reason", "runtime status published")
    out.setdefault("best_challenger_id", None)
    out.setdefault("paper_only", True)
    out.setdefault("routes_to_live", False)
    out.setdefault("places_real_order", False)
    safety = out.get("safety")
    if isinstance(safety, dict):
        out["paper_only"] = safety.get("paper_only") is not False
        out["routes_to_live"] = safety.get("routes_to_live") is True
        out["places_real_order"] = safety.get("places_real_order") is True
    return out


def _attach_champion_challenger_status(shape: dict[str, Any], r: Any) -> dict[str, Any]:
    out = dict(shape)
    status = _read_champion_challenger_status(r)
    out["champion_challenger_status"] = status
    return out


def _read_preemptive_feedback_status(r: Any) -> dict[str, Any]:
    fallback = {
        "schema_version": "preemptive_trainer_feedback_status_v1",
        "status": "PREEMPTIVE_COUNTERFACTUAL_STATUS_UNAVAILABLE",
        "available": False,
        "source": f"redis:{PREEMPTIVE_COUNTERFACTUAL_STATUS_KEY}",
        "blocked_candidate_counterfactual_rows": 0,
        "counterfactual_labels_pending": 0,
        "consumable_labeled_counterfactual_rows": 0,
        "trainer_consumption_state": "MISSING_RUNTIME_EVIDENCE",
        "no_future_leakage": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    if r is None:
        return fallback
    try:
        raw = r.get(PREEMPTIVE_COUNTERFACTUAL_STATUS_KEY)
    except Exception:
        return fallback
    if raw is None:
        return fallback
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        out = dict(fallback)
        out["status"] = "PREEMPTIVE_COUNTERFACTUAL_STATUS_INVALID_JSON"
        return out
    if not isinstance(payload, dict):
        return fallback
    out = dict(payload)
    out.setdefault("schema_version", "preemptive_trainer_feedback_status_v1")
    out.setdefault("source", f"redis:{PREEMPTIVE_COUNTERFACTUAL_STATUS_KEY}")
    out["available"] = True
    out.setdefault("no_future_leakage", True)
    out.setdefault("paper_only", True)
    out.setdefault("routes_to_live", False)
    out.setdefault("places_real_order", False)
    return out


def _attach_preemptive_feedback_status(shape: dict[str, Any], r: Any) -> dict[str, Any]:
    out = dict(shape)
    status = _read_preemptive_feedback_status(r)
    out["preemptive_trainer_feedback_status"] = status
    out["preemptive_edge_control_feedback"] = {
        "blocked_candidates_persisted": (
            int(status.get("blocked_candidate_counterfactual_rows") or 0) > 0
        ),
        "blocked_candidates_can_become_trainer_samples": True,
        "consumable_labeled_counterfactual_rows": int(
            status.get("consumable_labeled_counterfactual_rows") or 0
        ),
        "future_labels_used_as_features": False,
        "trainer_consumption_state": status.get("trainer_consumption_state"),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    return out


def _normalize_subprocess_output(data: dict[str, Any]) -> dict[str, Any]:
    out = _empty_shape(state=str(data.get("state") or "unknown"))
    for k in (
        "checkpoint_id",
        "uptime_days",
        "win_rate_30d",
        "episodes_total",
        "drift_watch_count",
        "drift_alarm_count",
        "promotion_locked",
        "promotion_min_role",
    ):
        if k in data:
            out[k] = data[k]
    return out


def _audit(r: Any, *, source: str, payload: str, decision_id: str) -> None:
    """Append a single audit event for this trainer-read."""
    write_audit_trainer_read(
        r,
        actor="v2.api.trainer.summary",
        source=source,
        prior_state_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16],
        payload=payload,
        decision_id=decision_id,
        chain_pointer="audit:trainer:reads",
    )


def _stub_mode_active() -> bool:
    if os.environ.get("V2_TRAINER_MODE", "").strip().lower() == "stub":
        return True
    if not os.environ.get("LEGACY_TRAINER_PYTHON", "").strip():
        return True
    if not os.environ.get("LEGACY_BOT_ROOT", "").strip():
        return True
    return False


def _run_trainer_status() -> dict[str, Any]:
    """Invoke the trainer-status subprocess once. Returns the normalized
    shape with `state='MISSING_EVIDENCE'` on any error.
    """
    interp = os.environ.get("LEGACY_TRAINER_PYTHON", "").strip()
    root = os.environ.get("LEGACY_BOT_ROOT", "").strip()
    if not interp or not root:
        return _empty_shape("MISSING_EVIDENCE")
    script = str(Path(root) / "scripts" / "trainer_status.py")
    argv = [interp, script, "--mode", "status", "--json"]
    try:
        validate_trainer_argv(argv)
    except TrainerArgvViolation:
        return _empty_shape("MISSING_EVIDENCE")

    try:
        proc = subprocess.run(  # noqa: S603 -- argv is allowlist-validated
            argv,
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _empty_shape("MISSING_EVIDENCE")

    if proc.returncode != 0:
        return _empty_shape("MISSING_EVIDENCE")

    try:
        data = json.loads(proc.stdout)
    except (ValueError, TypeError):
        return _empty_shape("MISSING_EVIDENCE")
    if not isinstance(data, dict):
        return _empty_shape("MISSING_EVIDENCE")
    return _normalize_subprocess_output(data)


def _redis_fallback_shape(r: Any) -> dict[str, Any] | None:
    """Try to build a trainer status shape directly from Redis prediction evidence.

    Returns a shape dict if useful evidence is found, else None.
    """
    if r is None:
        return None
    try:
        raw = r.get("v2:prediction:BTCUSDT:1h")
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        pred = json.loads(str(raw))
    except (ValueError, TypeError):
        return None
    if not isinstance(pred, dict):
        return None

    checkpoint_id = pred.get("checkpoint_id")
    cuda_active = pred.get("cuda_active")
    data_coverage = pred.get("data_coverage_percent")
    model_source = pred.get("model_source") or pred.get("trainer_source") or pred.get("checkpoint_source")
    model_id = pred.get("model_id")

    shape = _empty_shape("ACTIVE_REDIS_EVIDENCE")
    # Carry the underlying evidence timestamp so the contract can grade real
    # freshness (this prediction key drives the fallback; if it is hours old the
    # trainer is effectively down and must not be reported as fresh).
    shape["_source_generated_utc"] = (
        pred.get("generated_utc") or pred.get("generated_at") or pred.get("created_at")
    )
    shape["checkpoint_id"] = checkpoint_id
    # cuda_active is a bool; store as-is
    if cuda_active is not None:
        shape["cuda_active"] = cuda_active  # type: ignore[assignment]
    if data_coverage is not None:
        shape["data_coverage"] = float(data_coverage)  # type: ignore[assignment]
    if model_source is not None:
        shape["model_source"] = str(model_source)  # type: ignore[assignment]
    if model_id is not None:
        shape["model_id"] = str(model_id)  # type: ignore[assignment]
    return shape


@router.get("/status")
@router.get("/summary")
async def get_trainer_summary() -> dict[str, Any]:
    r = get_redis()
    decision_id = f"trainer-summary-{uuid.uuid4().hex[:12]}"

    if _stub_mode_active():
        # Before returning MISSING_EVIDENCE, try Redis fallback
        redis_shape = _redis_fallback_shape(r)
        if redis_shape is not None:
            redis_shape = _attach_hybrid_cuda_learning_status(redis_shape, r)
            redis_shape = _attach_model_identity_status(redis_shape, r)
            redis_shape = _attach_champion_challenger_status(redis_shape, r)
            redis_shape = _attach_preemptive_feedback_status(redis_shape, r)
            _audit(
                r,
                source="trainer.summary.redis_fallback",
                payload=json.dumps(redis_shape, sort_keys=True),
                decision_id=decision_id,
            )
            if r is not None:
                try:
                    r.set(CACHE_KEY, json.dumps(redis_shape), ex=_ttl_seconds())
                except Exception:
                    pass
            return _with_control_center_contract(
                redis_shape,
                source="trainer.summary.redis_fallback",
                redis_client=r,
            )
        shape = _empty_shape("MISSING_EVIDENCE")
        shape = _attach_champion_challenger_status(shape, r)
        shape = _attach_preemptive_feedback_status(shape, r)
        _audit(
            r,
            source="trainer.summary.stub",
            payload=json.dumps(shape, sort_keys=True),
            decision_id=decision_id,
        )
        return _with_control_center_contract(
            shape,
            source="trainer.summary.stub",
            redis_client=r,
        )

    if r is not None:
        try:
            cached_raw = r.get(CACHE_KEY)
        except Exception:
            cached_raw = None
        if cached_raw is not None:
            try:
                cached = json.loads(cached_raw)
            except (ValueError, TypeError):
                cached = None
            if isinstance(cached, dict):
                cached = _attach_hybrid_cuda_learning_status(cached, r)
                cached = _attach_model_identity_status(cached, r)
                cached = _attach_champion_challenger_status(cached, r)
                cached = _attach_preemptive_feedback_status(cached, r)
                _audit(
                    r,
                    source="trainer.summary.cache_hit",
                    payload=json.dumps(cached, sort_keys=True),
                    decision_id=decision_id,
                )
                return _with_control_center_contract(
                    cached,
                    source="trainer.summary.cache_hit",
                    redis_client=r,
                )

    shape = _run_trainer_status()

    # If subprocess returned MISSING_EVIDENCE, try Redis fallback before giving up
    if shape.get("state") == "MISSING_EVIDENCE":
        redis_shape = _redis_fallback_shape(r)
        if redis_shape is not None:
            shape = redis_shape
    shape = _attach_hybrid_cuda_learning_status(shape, r)
    shape = _attach_model_identity_status(shape, r)
    shape = _attach_champion_challenger_status(shape, r)
    shape = _attach_preemptive_feedback_status(shape, r)

    _audit(
        r,
        source="trainer.summary.subprocess",
        payload=json.dumps(shape, sort_keys=True),
        decision_id=decision_id,
    )

    if r is not None:
        try:
            r.set(CACHE_KEY, json.dumps(shape), ex=_ttl_seconds())
        except Exception:
            pass

    return _with_control_center_contract(
        shape,
        source="trainer.summary.subprocess",
        redis_client=r,
    )


_BASE_PUBLISHER_STATUS_PATH = os.environ.get(
    "V2_BASE_PUBLISHER_STATUS_PATH",
    "/home/wali/ai_bot_local_data/v2_native_trainer/profiled_base_publisher_v1/"
    "profiled_base_publisher_status_v1.json",
)
_COVERAGE_SYNC_STATUS_PATH = os.environ.get(
    "V2_COVERAGE_SYNC_STATUS_PATH",
    str(Path(__file__).resolve().parents[5]
        / "v2/frontend/public/operator_runtime/v2_universe_coverage_sync/latest/"
          "v2_universe_coverage_sync_status.json"),
)


@router.get("/supply")
async def get_trainer_supply_status() -> dict[str, Any]:
    """Read-only base-publisher supply status: explains WHY the trainer / paper
    pipeline panels are empty right now (published_symbol_count=0, the window
    failure reasons) and confirms coverage-sync is in census-only mode so no REST
    row contaminates the WSS-only decision windows. Populated by disk status files
    that previously had no API reader. Never mutates anything."""
    from collections import Counter

    out: dict[str, Any] = {
        "schema_version": "trainer_supply_status_v1",
        "source": "file:profiled_base_publisher_v1/status_v1.json",
    }
    try:
        p = Path(_BASE_PUBLISHER_STATUS_PATH)
        if p.is_file():
            d = json.loads(p.read_text())
            reasons: Counter[str] = Counter()
            for f in d.get("failures", []) or []:
                if isinstance(f, dict):
                    for rz in (f.get("reasons") or []):
                        reasons[str(rz)] += 1
            published = d.get("published_symbol_count")
            out.update({
                "cycle_completed_at": d.get("cycle_completed_at"),
                "published_symbol_count": published,
                "discovered_symbol_count": d.get("discovered_symbol_count"),
                "eligible_symbol_count": d.get("eligible_symbol_count"),
                "selected_symbol_count": d.get("selected_symbol_count"),
                "failed_symbol_count": d.get("failed_symbol_count"),
                "failure_reasons": dict(reasons),
                "publishing": bool(published),
            })
        else:
            out["base_publisher_status_available"] = False
    except Exception:  # noqa: BLE001 - read-only telemetry must not error the route
        out["base_publisher_status_available"] = False
    try:
        cp = Path(_COVERAGE_SYNC_STATUS_PATH)
        if cp.is_file():
            cs = json.loads(cp.read_text())
            bf = cs.get("backfill") or {}
            out["coverage_sync"] = {
                "census_only": bool(bf.get("dry_run")),
                "completion_status": bf.get("completion_status"),
                "gap_pairs_found": bf.get("gap_pairs_found"),
                "rest_writes_attempted": bf.get("attempted"),
                "note": "census-only (--no-backfill): no REST rows enter the WSS-only windows",
            }
    except Exception:  # noqa: BLE001
        pass
    return out


PAPER_EXPLORATION_BRIDGE_KEYS = {
    "supply_status": "v2:paper:exploration:supply_status",
    "materialization_queue_status": "v2:paper:exploration:materialization_queue_status",
    "materialization_status": "v2:paper:exploration:materialization_status",
}
PAPER_EXPLORATION_COUNTERFACTUAL_KEY = (
    "v2:trainer:paper_exploration_materialization_counterfactual_feedback"
)
TRAINER_HYBRID_CUDA_STATUS_KEY = "v2:trainer:hybrid_cuda:status"
A_GRADE_GATE_BURNDOWN_STATUS_KEY = "v2:paper:a_grade_gate_burndown_status"
PREEMPTIVE_EDGE_CONTROL_STATUS_KEY = "v2:paper:preemptive_edge_control_status"
PREEMPTIVE_CANDIDATE_DECISION_MATRIX_KEY = (
    "v2:paper:preemptive_candidate_decision_matrix"
)
CONTINUOUS_EDGE_GUARDIAN_EXECUTION_GATE_KEY = (
    "v2:continuous_edge_guardian:a_grade_execution_gate"
)
PAPER_EXPLORATION_BRIDGE_ROW_SAMPLE_LIMIT = 10
PAPER_EXPLORATION_BRIDGE_ROW_ARRAY_KEYS = (
    "active_rows",
    "pending_source_rows",
    "expired_rows",
    "unsafe_rows",
    "rejected_after_queue_rows",
)
PAPER_EXPLORATION_BRIDGE_ROW_SAMPLE_FIELDS = (
    "queue_id",
    "materialization_queue_id",
    "candidate_id",
    "prediction_id",
    "signal_id",
    "symbol",
    "timeframe",
    "side",
    "tier",
    "paper_opportunity_tier",
    "materialization_queue_result",
    "materialization_no_fill_reason",
    "materialization_no_fill_exact_reasons",
    "guardian_status",
    "guardian_new_entries_allowed",
    "guardian_block_reasons",
    "guardian_allowed_runtime_actions",
    "continuous_edge_guardian_status",
    "continuous_edge_guardian_new_entries_allowed",
    "continuous_edge_guardian_block_reasons",
    "continuous_edge_guardian_allowed_runtime_actions",
    "paper_only",
    "routes_to_live",
    "places_real_order",
    "live_order",
    "test_order",
    "order_submitted",
    "test_order_submitted",
    "leverage_mutated",
    "margin_mutated",
    "counts_as_A_plus",
    "counts_as_final_A_plus",
    "counts_as_final_a_plus",
    "counts_as_live_ready",
)


def _read_bridge_json(r: Any, key: str) -> dict[str, Any]:
    if r is None:
        return {}
    try:
        raw = r.get(key)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _float_or_none(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def _int_or_zero(value: Any) -> int:
    parsed = _float_or_none(value)
    return int(parsed) if parsed is not None else 0


def _distribution(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p50": ordered[len(ordered) // 2],
        "p90": ordered[int((len(ordered) - 1) * 0.9)],
        "max": ordered[-1],
    }


def _preemptive_matrix_rows(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    rows = matrix.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _preemptive_matrix_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    loss_probabilities: list[float] = []
    after_cost_edges: list[float] = []
    profit_factors: list[float] = []
    for row in rows:
        for key in (
            "block_reasons",
            "preemptive_block_reasons",
            "paper_exploration_paper_fill_block_reasons",
            "reasons",
        ):
            value = row.get(key)
            if isinstance(value, list):
                reasons.update(str(item) for item in value)
        for key in ("pre_trade_loss_probability", "loss_probability"):
            parsed = _float_or_none(row.get(key))
            if parsed is not None:
                loss_probabilities.append(parsed)
                break
        for key in (
            "expected_edge_after_cost_bps",
            "edge_after_cost_bps",
            "expected_net_edge_bps",
        ):
            parsed = _float_or_none(row.get(key))
            if parsed is not None:
                after_cost_edges.append(parsed)
                break
        for key in (
            "recent_bucket_profit_factor",
            "bucket_profit_factor",
            "profit_factor",
        ):
            parsed = _float_or_none(row.get(key))
            if parsed is not None:
                profit_factors.append(parsed)
                break
    return {
        "row_count": len(rows),
        "top_block_reasons": [
            {"reason": reason, "count": count}
            for reason, count in reasons.most_common(20)
        ],
        "loss_probability": _distribution(loss_probabilities),
        "expected_edge_after_cost_bps": _distribution(after_cost_edges),
        "bucket_profit_factor": _distribution(profit_factors),
    }


def _adaptation_diagnosis_from_payloads(
    *,
    trainer_status: dict[str, Any],
    a_grade_status: dict[str, Any],
    preemptive_status: dict[str, Any],
    preemptive_matrix: dict[str, Any],
    paper_supply: dict[str, Any],
    paper_queue: dict[str, Any],
    guardian_gate: dict[str, Any],
) -> dict[str, Any]:
    learning_metrics = (
        trainer_status.get("learning_metrics")
        if isinstance(trainer_status.get("learning_metrics"), dict)
        else {}
    )
    rows = _preemptive_matrix_rows(preemptive_matrix)
    preemptive = _preemptive_matrix_diagnostics(rows)
    loss_stats = preemptive.get("loss_probability") or {}
    pf_stats = preemptive.get("bucket_profit_factor") or {}
    edge_stats = preemptive.get("expected_edge_after_cost_bps") or {}

    ppo_entropy = _float_or_none(learning_metrics.get("ppo_entropy"))
    validation_gap = _float_or_none(
        learning_metrics.get("train_val_generalization_gap")
    )
    validation_loss = _float_or_none(
        learning_metrics.get("validation_supervised_loss")
    )
    validation_loss_before = _float_or_none(
        _first(
            learning_metrics.get("validation_supervised_loss_before"),
            trainer_status.get("validation_supervised_loss_before"),
        )
    )
    validation_loss_after = _float_or_none(
        _first(
            learning_metrics.get("validation_supervised_loss_after"),
            trainer_status.get("validation_supervised_loss_after"),
            learning_metrics.get("validation_supervised_loss"),
            trainer_status.get("validation_supervised_loss"),
        )
    )
    validation_loss_delta = _float_or_none(
        _first(
            learning_metrics.get("validation_loss_delta"),
            trainer_status.get("validation_loss_delta"),
        )
    )
    loss_after = _float_or_none(learning_metrics.get("loss_after"))
    online_learning_status = str(trainer_status.get("online_learning_status") or "")
    checkpoint_promotion_reason = str(
        _first(
            learning_metrics.get("checkpoint_promotion_reason"),
            trainer_status.get("checkpoint_promotion_reason"),
        )
        or ""
    )
    checkpoint_promotion_rejected = _first(
        learning_metrics.get("checkpoint_promotion_rejected"),
        trainer_status.get("checkpoint_promotion_rejected"),
    )
    hard_promotion_rejection = _first(
        learning_metrics.get("hard_promotion_rejection_reason"),
        trainer_status.get("hard_promotion_rejection_reason"),
    )
    a_grade_rows = _int_or_zero(
        a_grade_status.get("A_grade_rows")
        if a_grade_status.get("A_grade_rows") is not None
        else a_grade_status.get("a_grade_rows")
    )
    near_a_grade_rows = _int_or_zero(
        a_grade_status.get("near_A_grade_rows")
        if a_grade_status.get("near_A_grade_rows") is not None
        else a_grade_status.get("near_a_grade_rows")
    )
    paper_fill_allowed_rows = _int_or_zero(
        a_grade_status.get("paper_fill_allowed_rows")
        or preemptive_status.get("accepted_count")
    )
    materialized_positions = _int_or_zero(
        paper_queue.get("same_cycle_materialized_count")
        or paper_supply.get("materialized_positions_last_cycle")
    )
    guardian_status = str(
        guardian_gate.get("status")
        or a_grade_status.get("guardian_status")
        or paper_queue.get("guardian_status")
        or ""
    )
    guardian_allows_entries = (
        guardian_gate.get("a_grade_new_entries_allowed")
        if guardian_gate.get("a_grade_new_entries_allowed") is not None
        else a_grade_status.get("guardian_new_entries_allowed")
    )
    no_fill_detail = _materialization_no_fill_detail(paper_queue)

    findings: list[dict[str, Any]] = []
    if (
        checkpoint_promotion_rejected is True
        and checkpoint_promotion_reason
        in {"VALIDATION_LOSS_REGRESSED", "TRAIN_VAL_OVERFIT_GAP"}
    ):
        findings.append(
            {
                "id": checkpoint_promotion_reason,
                "severity": "learning_checkpoint_blocker",
                "online_learning_status": online_learning_status or None,
                "checkpoint_promotion_rejected": True,
                "hard_promotion_rejection_reason": hard_promotion_rejection,
                "validation_loss_delta": validation_loss_delta,
                "validation_supervised_loss_before": validation_loss_before,
                "validation_supervised_loss_after": validation_loss_after,
                "why_it_matters": (
                    "The trainer refused to persist this checkpoint because "
                    "held-out validation evidence got worse or remained overfit."
                ),
                "code_defect": False,
                "next_action": "Run offline sweep/retrain; do not force-promote hard validation failures.",
            }
        )
    if online_learning_status == "BLOCKED_NO_DURABLE_WEIGHT_UPDATE":
        findings.append(
            {
                "id": "BLOCKED_NO_DURABLE_WEIGHT_UPDATE",
                "severity": "learning_checkpoint_blocker",
                "checkpoint_promotion_reason": checkpoint_promotion_reason or None,
                "checkpoint_promotion_rejected": checkpoint_promotion_rejected,
                "hard_promotion_rejection_reason": hard_promotion_rejection,
                "why_it_matters": (
                    "The trainer is active but did not save a durable checkpoint "
                    "this cycle because the validation guard rejected it."
                ),
                "code_defect": False,
                "next_action": "Recover through validated offline retrain/sweep, not live guard weakening.",
            }
        )
    if ppo_entropy is not None and ppo_entropy >= 0.8:
        findings.append(
            {
                "id": "PPO_ENTROPY_HIGH_POLICY_NOT_CONVERGED",
                "severity": "learning_blocker",
                "observed": ppo_entropy,
                "why_it_matters": (
                    "The policy is still close to high-entropy exploration, so "
                    "confidence has not hardened into a repeatable edge."
                ),
                "code_defect": False,
                "next_action": "Run offline hyperparameter sweep/retrain; do not tune live blindly.",
            }
        )
    if validation_gap is not None and validation_gap > 1.0:
        findings.append(
            {
                "id": "TRAIN_VAL_GENERALIZATION_GAP_HIGH",
                "severity": "learning_blocker",
                "observed": validation_gap,
                "validation_supervised_loss": validation_loss,
                "loss_after": loss_after,
                "why_it_matters": (
                    "Training loss is improving, but held-out validation remains "
                    "worse enough that strict A-grade evidence cannot trust it."
                ),
                "code_defect": False,
                "next_action": "Prefer offline sweep/retrain and validation-gated promotion.",
            }
        )
    if (loss_stats.get("p50") or 0.0) >= 0.8:
        findings.append(
            {
                "id": "PREEMPTIVE_LOSS_PROBABILITY_TOO_HIGH",
                "severity": "paper_gate_blocker",
                "observed_p50": loss_stats.get("p50"),
                "observed_p90": loss_stats.get("p90"),
                "why_it_matters": (
                    "The paper risk gateway sees most candidates as high loss "
                    "probability, so they cannot become A-grade closes."
                ),
                "code_defect": False,
                "next_action": "Improve genuine model edge; do not lower the risk gate.",
            }
        )
    if (pf_stats.get("p90") or 0.0) < 2.0 and pf_stats:
        findings.append(
            {
                "id": "BUCKET_PROFIT_FACTOR_BELOW_A_GRADE_STANDARD",
                "severity": "economic_blocker",
                "observed_p50": pf_stats.get("p50"),
                "observed_p90": pf_stats.get("p90"),
                "required": 2.0,
                "why_it_matters": (
                    "Even stronger buckets in the current candidate matrix do "
                    "not meet the strict profit-factor standard."
                ),
                "code_defect": False,
                "next_action": "Accumulate or learn genuinely profitable after-cost buckets.",
            }
        )
    if a_grade_rows <= 0:
        findings.append(
            {
                "id": "A_GRADE_SUPPLY_ZERO",
                "severity": "a_grade_blocker",
                "observed": a_grade_rows,
                "near_a_grade_rows": near_a_grade_rows,
                "why_it_matters": (
                    "No current row is allowed to count as strict A-grade, so "
                    "the runtime runway cannot fill."
                ),
                "code_defect": False,
                "next_action": "Keep exploration/shadow rows non-A-grade until strict evidence is earned.",
            }
        )
    if materialized_positions <= 0 or paper_fill_allowed_rows <= 0:
        findings.append(
            {
                "id": "PAPER_OUTCOME_FEEDER_STARVED_BY_TRUE_GATES",
                "severity": "learning_data_blocker",
                "materialized_positions": materialized_positions,
                "paper_fill_allowed_rows": paper_fill_allowed_rows,
                **no_fill_detail,
                "why_it_matters": (
                    "The trainer cannot learn many fresh on-policy paper closes "
                    "while true performance/risk/guardian gates reject fills."
                ),
                "code_defect": False,
                "next_action": "Expose exact blockers and repair only false positives; do not fabricate fills.",
            }
        )
    if guardian_status.upper() == "A_GRADE_HALTED_PERFORMANCE" or guardian_allows_entries is False:
        findings.append(
            {
                "id": "GUARDIAN_HALTED_PERFORMANCE",
                "severity": "a_grade_blocker",
                "guardian_status": guardian_status or None,
                "guardian_new_entries_allowed": guardian_allows_entries,
                "why_it_matters": (
                    "The continuous edge guardian is intentionally preventing "
                    "new A-grade entries until real evidence meets thresholds."
                ),
                "code_defect": False,
                "next_action": "Keep passing this blocker through to paper/operator surfaces.",
            }
        )

    headline = (
        "Trainer is active, but A-grade adaptation is not proven: high policy "
        "entropy/generalization risk plus high preemptive loss probability leave "
        "paper/A-grade outcome feeders starved."
    )
    if not findings:
        headline = "No active adaptation blocker was detected from the sampled runtime keys."

    return {
        "schema_version": "trainer_adaptation_diagnosis_v1",
        "generated_utc": _utc_now(),
        "headline": headline,
        "status": "A_GRADE_ADAPTATION_NOT_PROVEN" if findings else "NO_ACTIVE_BLOCKER_DETECTED",
        "learning_active": trainer_status.get("online_learning_status") == "WEIGHTS_UPDATING",
        "live_gate": "blocked_human_only",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "trainer": {
            "online_learning_status": online_learning_status or None,
            "effective_trainer_mode": trainer_status.get("effective_trainer_mode"),
            "checkpoint_promotion_reason": checkpoint_promotion_reason or None,
            "checkpoint_promotion_rejected": checkpoint_promotion_rejected,
            "hard_promotion_rejection_reason": hard_promotion_rejection,
            "checkpoint_promoted_this_cycle": learning_metrics.get(
                "checkpoint_promoted_this_cycle"
            )
            if learning_metrics.get("checkpoint_promoted_this_cycle") is not None
            else trainer_status.get("checkpoint_promoted_this_cycle"),
            "ppo_entropy": ppo_entropy,
            "train_val_generalization_gap": validation_gap,
            "validation_supervised_loss": validation_loss,
            "validation_supervised_loss_before": validation_loss_before,
            "validation_supervised_loss_after": validation_loss_after,
            "validation_loss_delta": validation_loss_delta,
            "loss_after": loss_after,
            "entropy_coefficient": learning_metrics.get("entropy_coefficient"),
            "supervised_entropy_bonus": learning_metrics.get(
                "supervised_entropy_bonus"
            ),
        },
        "a_grade": {
            "A_grade_rows": a_grade_rows,
            "near_A_grade_rows": near_a_grade_rows,
            "status": a_grade_status.get("status"),
            "closest_gap_reason": a_grade_status.get("closest_gap_reason"),
            "guardian_status": guardian_status or None,
            "guardian_new_entries_allowed": guardian_allows_entries,
        },
        "preemptive": {
            "candidate_count": preemptive_status.get("candidate_count"),
            "accepted_count": preemptive_status.get("accepted_count"),
            **preemptive,
        },
        "paper_learning_feeder": {
            "fresh_strategy_supply_rows": paper_supply.get("fresh_strategy_supply_rows"),
            "fresh_exploration_candidates": paper_supply.get(
                "fresh_exploration_candidates"
            ),
            "materialized_positions_last_cycle": paper_supply.get(
                "materialized_positions_last_cycle"
            ),
            "queued_count": paper_queue.get("queued_count"),
            "active_count": paper_queue.get("active_count"),
            "same_cycle_materialized_count": paper_queue.get(
                "same_cycle_materialized_count"
            ),
            "rejected_after_queue_count": paper_queue.get(
                "rejected_after_queue_count"
            ),
            **no_fill_detail,
        },
        "findings": findings,
        "forbidden_shortcuts_refused": [
            "lowering A-grade, holdout, profit-factor, or live gates",
            "counting exploration/probation rows as A+ or live-ready",
            "fabricating paper closes, test orders, or live orders",
            "disabling guardian/risk gates to create cosmetic evidence",
        ],
        "next_legitimate_actions": [
            "run offline hyperparameter sweep/retrain if entropy or validation gap persist",
            "continue paper/shadow accumulation while preserving exact blocker pass-through",
            "repair only verified false-positive blockers; leave true performance/risk blocks strict",
        ],
    }


@router.get("/adaptation-diagnosis")
async def get_trainer_adaptation_diagnosis() -> dict[str, Any]:
    """Why training has not yet produced strict A-grade evidence.

    Read-only operator diagnostic. It composes existing Redis truth and never
    changes trainer state, paper state, exchange state, thresholds, or gates.
    """
    r = get_redis()
    return _adaptation_diagnosis_from_payloads(
        trainer_status=_read_bridge_json(r, TRAINER_HYBRID_CUDA_STATUS_KEY),
        a_grade_status=_read_bridge_json(r, A_GRADE_GATE_BURNDOWN_STATUS_KEY),
        preemptive_status=_read_bridge_json(r, PREEMPTIVE_EDGE_CONTROL_STATUS_KEY),
        preemptive_matrix=_read_bridge_json(r, PREEMPTIVE_CANDIDATE_DECISION_MATRIX_KEY),
        paper_supply=_read_bridge_json(
            r, PAPER_EXPLORATION_BRIDGE_KEYS["supply_status"]
        ),
        paper_queue=_read_bridge_json(
            r, PAPER_EXPLORATION_BRIDGE_KEYS["materialization_queue_status"]
        ),
        guardian_gate=_read_bridge_json(r, CONTINUOUS_EDGE_GUARDIAN_EXECUTION_GATE_KEY),
    )


def _paper_exploration_bridge_row_sample(
    queue_status: dict[str, Any],
    row_key: str,
) -> tuple[int, list[dict[str, Any]]]:
    rows = queue_status.get(row_key)
    if not isinstance(rows, list):
        return 0, []
    sample: list[dict[str, Any]] = []
    for row in rows[:PAPER_EXPLORATION_BRIDGE_ROW_SAMPLE_LIMIT]:
        if not isinstance(row, dict):
            continue
        compact = {
            field: row[field]
            for field in PAPER_EXPLORATION_BRIDGE_ROW_SAMPLE_FIELDS
            if field in row
        }
        if compact:
            sample.append(compact)
    return len(rows), sample


def _paper_exploration_bridge_queue_status(
    queue_status: dict[str, Any],
) -> dict[str, Any]:
    compact_queue = {
        key: value
        for key, value in queue_status.items()
        if key not in set(PAPER_EXPLORATION_BRIDGE_ROW_ARRAY_KEYS)
    }
    for row_key in PAPER_EXPLORATION_BRIDGE_ROW_ARRAY_KEYS:
        total, sample = _paper_exploration_bridge_row_sample(queue_status, row_key)
        compact_queue[f"{row_key}_sample_count"] = len(sample)
        compact_queue[f"{row_key}_total_count"] = total
        compact_queue[f"{row_key}_sample_limit"] = (
            PAPER_EXPLORATION_BRIDGE_ROW_SAMPLE_LIMIT
        )
        compact_queue[f"{row_key}_omitted_from_main_payload"] = total > 0
        compact_queue[f"{row_key}_sample"] = sample
    return compact_queue


@router.get("/paper-exploration-bridge")
async def get_paper_exploration_bridge_truth() -> dict[str, Any]:
    """Supply-bridge truth: strategy supply -> materialization queue -> paper loop.

    Read-only mirror of the three exploration bridge Redis statuses plus the
    per-cycle counterfactual feedback rows, so the GUI can show why fresh
    exploration candidates materialized or were rejected without guessing.
    """
    r = get_redis()
    payloads = {
        name: _read_bridge_json(r, key)
        for name, key in PAPER_EXPLORATION_BRIDGE_KEYS.items()
    }
    counterfactual_rows: list[dict[str, Any]] = []
    if r is not None:
        try:
            raw = r.get(PAPER_EXPLORATION_COUNTERFACTUAL_KEY)
            parsed = json.loads(raw) if raw else []
            if isinstance(parsed, list):
                counterfactual_rows = [row for row in parsed if isinstance(row, dict)]
        except Exception:
            counterfactual_rows = []
    supply = payloads["supply_status"]
    queue_status = payloads["materialization_queue_status"]
    compact_queue = _paper_exploration_bridge_queue_status(queue_status)
    return {
        "schema_version": "paper_exploration_bridge_truth_api_v1",
        "generated_utc": _utc_now(),
        "available": bool(supply or queue_status),
        "redis_keys": {
            **PAPER_EXPLORATION_BRIDGE_KEYS,
            "counterfactual_feedback": PAPER_EXPLORATION_COUNTERFACTUAL_KEY,
        },
        "supply_status": supply,
        "materialization_queue_status": compact_queue,
        "materialization_status": payloads["materialization_status"],
        "counterfactual_feedback_row_count": len(counterfactual_rows),
        "counterfactual_feedback_rows": counterfactual_rows[:25],
        "funnel": {
            "fresh_strategy_supply_rows": supply.get("fresh_strategy_supply_rows"),
            "fresh_exploration_candidates": supply.get("fresh_exploration_candidates"),
            "queued_count": queue_status.get("queued_count"),
            "same_cycle_materialized_count": queue_status.get(
                "same_cycle_materialized_count"
            ),
            "rejected_after_queue_count": queue_status.get("rejected_after_queue_count"),
            "rejected_after_queue_reason_counts": queue_status.get(
                "rejected_after_queue_reason_counts"
            ),
            "exact_no_fill_reason": queue_status.get("exact_no_fill_reason"),
            "expired_count": queue_status.get("expired_count"),
            "counterfactual_count": queue_status.get("counterfactual_count"),
        },
        "live_gate": supply.get("live_gate") or "blocked_human_only",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        **_attach_a_grade_blocker_truth({}, r),
    }
