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
    }


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


@router.get("/summary")
async def get_trainer_summary() -> dict[str, Any]:
    r = get_redis()
    decision_id = f"trainer-summary-{uuid.uuid4().hex[:12]}"

    if _stub_mode_active():
        shape = _empty_shape("MISSING_EVIDENCE")
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
                _audit(
                    r,
                    source="trainer.summary.cache_hit",
                    payload=json.dumps(cached, sort_keys=True),
                    decision_id=decision_id,
                )
                return cached

    shape = _run_trainer_status()
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
