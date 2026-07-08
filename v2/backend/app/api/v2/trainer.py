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
from pathlib import Path
from typing import Any

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
PREEMPTIVE_COUNTERFACTUAL_STATUS_KEY = (
    "v2:trainer:preemptive_blocked_counterfactual_status"
)
DEFAULT_TTL_S = 30


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
            return redis_shape
        shape = _empty_shape("MISSING_EVIDENCE")
        shape = _attach_champion_challenger_status(shape, r)
        shape = _attach_preemptive_feedback_status(shape, r)
        _audit(
            r,
            source="trainer.summary.stub",
            payload=json.dumps(shape, sort_keys=True),
            decision_id=decision_id,
        )
        return shape

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
                cached = _attach_champion_challenger_status(cached, r)
                cached = _attach_preemptive_feedback_status(cached, r)
                _audit(
                    r,
                    source="trainer.summary.cache_hit",
                    payload=json.dumps(cached, sort_keys=True),
                    decision_id=decision_id,
                )
                return cached

    shape = _run_trainer_status()

    # If subprocess returned MISSING_EVIDENCE, try Redis fallback before giving up
    if shape.get("state") == "MISSING_EVIDENCE":
        redis_shape = _redis_fallback_shape(r)
        if redis_shape is not None:
            shape = redis_shape
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

    return shape
