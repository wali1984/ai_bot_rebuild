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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from app.api.v2._common import get_redis, write_audit_trainer_read

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


def _with_control_center_contract(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    out = dict(payload)
    state = str(out.get("state") or "").upper()
    data_quality = "partial" if state in {"", "MISSING_EVIDENCE"} else "fresh"
    out["schema_version"] = str(out.get("schema_version") or "trainer_status_v2")
    out["generated_at_utc"] = _utc_now()
    out["generated_at_et"] = _display_time_et()
    out["source"] = source
    out["staleness_seconds"] = 0
    out["freshness_status"] = "fresh"
    out["canonical_owner"] = "/api/v2/trainer/status"
    out["live_gate"] = "blocked_human_only"
    out["places_real_order"] = False
    out["routes_to_live"] = False
    out["data_quality_status"] = data_quality
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
            return _with_control_center_contract(redis_shape, source="trainer.summary.redis_fallback")
        shape = _empty_shape("MISSING_EVIDENCE")
        shape = _attach_champion_challenger_status(shape, r)
        shape = _attach_preemptive_feedback_status(shape, r)
        _audit(
            r,
            source="trainer.summary.stub",
            payload=json.dumps(shape, sort_keys=True),
            decision_id=decision_id,
        )
        return _with_control_center_contract(shape, source="trainer.summary.stub")

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
                cached = _attach_champion_challenger_status(cached, r)
                cached = _attach_preemptive_feedback_status(cached, r)
                _audit(
                    r,
                    source="trainer.summary.cache_hit",
                    payload=json.dumps(cached, sort_keys=True),
                    decision_id=decision_id,
                )
                return _with_control_center_contract(cached, source="trainer.summary.cache_hit")

    shape = _run_trainer_status()

    # If subprocess returned MISSING_EVIDENCE, try Redis fallback before giving up
    if shape.get("state") == "MISSING_EVIDENCE":
        redis_shape = _redis_fallback_shape(r)
        if redis_shape is not None:
            shape = redis_shape
    shape = _attach_hybrid_cuda_learning_status(shape, r)
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

    return _with_control_center_contract(shape, source="trainer.summary.subprocess")


PAPER_EXPLORATION_BRIDGE_KEYS = {
    "supply_status": "v2:paper:exploration:supply_status",
    "materialization_queue_status": "v2:paper:exploration:materialization_queue_status",
    "materialization_status": "v2:paper:exploration:materialization_status",
}
PAPER_EXPLORATION_COUNTERFACTUAL_KEY = (
    "v2:trainer:paper_exploration_materialization_counterfactual_feedback"
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
    compact_queue = {
        key: value
        for key, value in queue_status.items()
        if key
        not in {"active_rows", "expired_rows", "unsafe_rows", "rejected_after_queue_rows"}
    }
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
    }
