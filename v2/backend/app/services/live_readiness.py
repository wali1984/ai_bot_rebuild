"""Live-readiness gate derivation service.

The landing's `§ 09 Live Readiness gates` table lists 8 boolean-ish gates.
This module is the **only** place allowed to compute those states from
heterogeneous sources (Redis, payloads). Routes call `derive_gates()` and
serialize the result.

Hard rule from `06_SAFETY_BOUNDARIES.md`:

> G8 (L5 approval recorded) is ALWAYS `blocked` unless the Redis key
> `audit:live_enable:last_approval_id` exists. There is no UI control
> that can flip it from inside this process.

If any Redis lookup raises, the affected gate's state is `pending`. G8
stays `blocked` regardless.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Any, Literal

GateState = Literal["passed", "pending", "locked", "blocked"]


@dataclass(frozen=True)
class Gate:
    id: str
    name: str
    sub: str
    source_route_or_key: str
    state: GateState


def _safe_get(r: Any, key: str) -> tuple[Any, bool]:
    """Return (value, ok) where ok=False indicates an exception or no client."""
    if r is None:
        return None, False
    try:
        return r.get(key), True
    except Exception:
        return None, False


def _safe_exists(r: Any, key: str) -> tuple[bool, bool]:
    """Return (exists, ok) where ok=False indicates an exception or no client."""
    if r is None:
        return False, False
    try:
        return bool(r.exists(key)), True
    except Exception:
        return False, False


def _truthy_string(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    return s in {"true", "1", "ok", "go", "pass", "passed", "current", "ready"}


def _g1_coverage_atlas(r: Any) -> GateState:
    """G1 — Coverage / Atlas complete -> `systemAtlas.go_no_go`.

    Redis keys we try (in order):
    - v2:system_atlas:go_no_go
    - system_atlas:go_no_go
    """
    for key in ("v2:system_atlas:go_no_go", "system_atlas:go_no_go"):
        v, ok = _safe_get(r, key)
        if not ok:
            return "pending"
        if v is None:
            continue
        s = str(v).strip().lower()
        if s in {"go", "passed", "pass", "true", "current"}:
            return "passed"
        return "pending"
    return "pending"


def _g2_trainer_atlas(r: Any) -> GateState:
    v, ok = _safe_get(r, "trainer_atlas:status")
    if not ok:
        return "pending"
    if v is None:
        return "pending"
    s = str(v).strip().lower()
    if s in {"complete", "passed", "tier_a_complete", "current"}:
        return "passed"
    if s in {"locked", "blocked"}:
        return "locked"
    return "pending"


def _g3_codex_review(r: Any) -> GateState:
    """G3 — Codex adversarial review -> codex:reviews:latest.

    Counts the blockers; zero blockers AND a recorded pass id -> passed.
    """
    v, ok = _safe_get(r, "codex:reviews:latest")
    if not ok:
        return "pending"
    if v is None:
        return "pending"
    try:
        data = json.loads(v) if isinstance(v, str) else None
    except (ValueError, TypeError):
        data = None
    if not isinstance(data, dict):
        return "pending"
    try:
        blockers = int(data.get("blocker_count", 0))
    except (TypeError, ValueError):
        blockers = 0
    pass_id = data.get("last_pass_id")
    if blockers == 0 and pass_id:
        return "passed"
    if blockers > 0:
        return "blocked"
    return "pending"


def _g4_operator_truth(r: Any) -> GateState:
    """G4 — Operator truth current -> NOT supervisor_status.stale_or_conflicting.

    Redis stores the latest operator-truth supervisor status under either
    `operator:truth:supervisor` (JSON) or a stale-flag key. Truthy stale
    -> pending; explicitly current -> passed.
    """
    v, ok = _safe_get(r, "operator:truth:supervisor")
    if ok and v is not None:
        try:
            data = json.loads(v) if isinstance(v, str) else None
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            stale = data.get("stale_or_conflicting")
            if stale is False:
                return "passed"
            if stale is True:
                return "pending"

    # Fallback to a discrete flag key.
    flag, ok2 = _safe_get(r, "operator:truth:supervisor:stale_or_conflicting")
    if not ok2:
        return "pending"
    if flag is None:
        return "pending"
    s = str(flag).strip().lower()
    if s in {"false", "0", "no"}:
        return "passed"
    return "pending"


def _g5_canary_delta(r: Any) -> GateState:
    """G5 — Paper canary delta <= 0.05% x 14d -> pnl:decomp:canary_14d.

    The key may store either a raw boolean-ish flag or a JSON payload with
    a `within_threshold` field.
    """
    v, ok = _safe_get(r, "pnl:decomp:canary_14d")
    if not ok:
        return "pending"
    if v is None:
        return "pending"
    if isinstance(v, str) and v.strip().startswith("{"):
        try:
            data = json.loads(v)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            wt = data.get("within_threshold")
            if wt is True:
                return "passed"
            if wt is False:
                return "blocked"
            return "pending"
    return "passed" if _truthy_string(v) else "pending"


def _g6_risk_envelope(r: Any) -> GateState:
    v, ok = _safe_get(r, "risk:envelope:stress_test_passed")
    if not ok:
        return "pending"
    if v is None:
        return "pending"
    return "passed" if _truthy_string(v) else "pending"


def _g7_build_validation(r: Any) -> GateState:
    v, ok = _safe_get(r, "build:validation:status")
    if not ok:
        return "pending"
    if v is None:
        return "pending"
    s = str(v).strip().lower()
    if s in {"current", "passed", "pass", "ok", "green"}:
        return "passed"
    if s in {"locked", "blocked"}:
        return "blocked"
    return "pending"


def _g8_l5_approval(r: Any) -> GateState:
    """G8 — L5 approval recorded.

    **ALWAYS `blocked` unless `audit:live_enable:last_approval_id` exists.**
    Per `06_SAFETY_BOUNDARIES.md`, there is no UI path that flips this.
    """
    exists, ok = _safe_exists(r, "audit:live_enable:last_approval_id")
    if not ok:
        return "blocked"
    return "passed" if exists else "blocked"


def derive_gates(r: Any) -> list[dict[str, Any]]:
    """Compute all 8 gates and return them in fixed order G1..G8.

    Every gate is wrapped in a try/except so a single failure cannot break
    the response. G8 is special-cased: even if the entire function path
    explodes, the fallback returns `blocked` for G8.
    """
    gates: list[Gate] = []

    def add(gid: str, name: str, sub: str, src: str, compute) -> None:
        try:
            state = compute(r)
        except Exception:
            state = "pending"  # type: ignore[assignment]
        gates.append(Gate(id=gid, name=name, sub=sub, source_route_or_key=src, state=state))

    add(
        "G1",
        "Coverage / Atlas complete",
        "system atlas go_no_go",
        "systemAtlas.go_no_go",
        _g1_coverage_atlas,
    )
    add(
        "G2",
        "Trainer atlas Tier A",
        "trainer_atlas:status",
        "trainer_atlas:status",
        _g2_trainer_atlas,
    )
    add(
        "G3",
        "Codex adversarial review",
        "codex:reviews:latest",
        "codex:reviews:latest",
        _g3_codex_review,
    )
    add(
        "G4",
        "Operator truth current",
        "supervisor_status.stale_or_conflicting=false",
        "operator:truth:supervisor",
        _g4_operator_truth,
    )
    add(
        "G5",
        "Paper canary delta <= 0.05% x 14d",
        "pnl:decomp:canary_14d",
        "pnl:decomp:canary_14d",
        _g5_canary_delta,
    )
    add(
        "G6",
        "Risk envelope",
        "stress_test_passed",
        "risk:envelope:stress_test_passed",
        _g6_risk_envelope,
    )
    add(
        "G7",
        "Build validation current",
        "build:validation:status",
        "build:validation:status",
        _g7_build_validation,
    )

    # G8 always blocked unless the approval key exists. Guard against any
    # exception so the final state is never something else.
    try:
        g8_state = _g8_l5_approval(r)
    except Exception:
        g8_state = "blocked"
    gates.append(
        Gate(
            id="G8",
            name="L5 approval recorded",
            sub="audit:live_enable:last_approval_id",
            source_route_or_key="audit:live_enable:last_approval_id",
            state=g8_state if g8_state in {"passed", "blocked"} else "blocked",
        )
    )

    return [asdict(g) for g in gates]
