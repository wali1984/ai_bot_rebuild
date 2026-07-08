"""B7: live-readiness gates route.

Returns the 8-gate matrix used by section 09 of the redesigned landing.
All derivation is delegated to `app.services.live_readiness.derive_gates`.

G8 (L5 approval recorded) is ALWAYS `blocked` until
`audit:live_enable:last_approval_id` exists in Redis. There is no UI
control wired anywhere that can flip this.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis
from app.services.live_readiness import derive_gates

router = APIRouter(prefix="/live-readiness", tags=["v2-landing"])


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read_json_key(r: Any, key: str) -> Any:
    try:
        raw = r.get(key)
    except Exception:
        return None
    if raw in (None, ""):
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _preemptive_live_readiness_context(r: Any) -> dict[str, Any]:
    status = _read_json_key(r, "v2:paper:preemptive_edge_control_status")
    matrix = _read_json_key(r, "v2:paper:preemptive_candidate_decision_matrix")
    status = status if isinstance(status, dict) else {}
    matrix = matrix if isinstance(matrix, dict) else {}
    rows = matrix.get("rows") or matrix.get("sample_decisions") or []
    rows = rows if isinstance(rows, list) else []
    first = rows[0] if rows and isinstance(rows[0], dict) else {}
    decision_counts = status.get("decision_counts")
    decision_counts = decision_counts if isinstance(decision_counts, dict) else {}
    action_counts = status.get("action_counts")
    action_counts = action_counts if isinstance(action_counts, dict) else {}
    allow_count = int(
        action_counts.get("ALLOW_A_PLUS_CANDIDATE")
        or decision_counts.get("ALLOW")
        or 0
    )
    candidate_count = int(status.get("candidate_count") or matrix.get("candidate_count") or 0)
    available = bool(status)
    return {
        "schema_version": "live_readiness_preemptive_edge_control_v1",
        "status": (
            "PREEMPTIVE_EDGE_CONTROL_ACTIVE"
            if available
            else "PREEMPTIVE_EDGE_CONTROL_NOT_YET_PUBLISHED"
        ),
        "source_key": "v2:paper:preemptive_edge_control_status",
        "matrix_source_key": "v2:paper:preemptive_candidate_decision_matrix",
        "generated_utc": status.get("generated_utc") or matrix.get("generated_utc"),
        "candidate_count": candidate_count,
        "accepted_count": int(status.get("accepted_count") or 0),
        "decision_counts": decision_counts,
        "action_counts": action_counts,
        "preemptive_decision_id": first.get("preemptive_decision_id"),
        "preemptive_decision": first.get("preemptive_decision"),
        "preemptive_action": first.get("preemptive_action"),
        "preemptive_allowed": first.get("preemptive_allowed") is True,
        "preemptive_block_reasons": first.get("preemptive_block_reasons")
        or first.get("preemptive_decision_reasons")
        or [],
        "pre_trade_loss_probability": first.get("pre_trade_loss_probability"),
        "pre_trade_expected_net_pnl_usd": first.get(
            "pre_trade_expected_net_pnl_usd"
        ),
        "why_blocked": first.get("preemptive_decision_reasons") or [],
        "accepted_without_preemptive_decision": int(
            status.get("accepted_without_preemptive_decision") or 0
        ),
        "accepted_high_loss_probability_count": int(
            status.get("accepted_high_loss_probability_count") or 0
        ),
        "reduced_size_without_guardian_approval_count": int(
            status.get("reduced_size_without_guardian_approval_count") or 0
        ),
        "hard_fail": status.get("hard_fail") is True,
        "live_dry_run_requires_preemptive_decision": True,
        "live_dry_run_allows_only": "ALLOW_A_PLUS_CANDIDATE",
        "allow_live_dry_run_candidate_count": allow_count,
        "live_dry_run_currently_blocked_by_preemptive": (
            candidate_count > 0 and allow_count <= 0
        ),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _live_readiness_payload() -> dict[str, Any]:
    r = get_redis()
    gates = derive_gates(r)
    blocking = [gate for gate in gates if gate.get("state") != "passed"]
    preemptive = _preemptive_live_readiness_context(r)
    ts = _utc_now()
    return {
        "data": {
            "gates": gates,
            "gate_count": len(gates),
            "passed_gate_count": len(gates) - len(blocking),
            "blocking_gates": blocking,
            "live_ready": not blocking,
            "live_submit_allowed": False,
            "live_gate": "blocked_human_only",
            "requires_human_approval_key": "audit:live_enable:last_approval_id",
            "preemptive_edge_control": preemptive,
            "live_dry_run_preemptive_policy": {
                "requires_preemptive_decision": True,
                "allow_decision": "ALLOW_A_PLUS_CANDIDATE",
                "fail_closed_if_missing": True,
                "fail_closed_if_not_allow": True,
                "places_real_order": False,
            },
        },
        "source": "app.services.live_readiness.derive_gates",
        "source_type": "redis_live",
        "endpoint": "/api/v2/live-readiness",
        "timestamp": ts,
        "received_at": ts,
        "lag_ms": 0,
        "stale": False,
        "missing_fields": [gate.get("source_route_or_key") for gate in blocking],
        "warnings": [
            "Live readiness is read-only and cannot enable exchange submission",
            "G8 remains blocked unless audit:live_enable:last_approval_id exists",
            "Live dry-run fails closed unless preemptive_edge_control.preemptive_decision is ALLOW",
        ],
        "mode": "live_blocked",
    }


@router.get("")
async def get_live_readiness_status() -> dict[str, Any]:
    return _live_readiness_payload()


@router.get("/")
async def get_live_readiness_status_slash() -> dict[str, Any]:
    return _live_readiness_payload()


@router.get("/gates")
async def get_live_readiness_gates() -> list[dict[str, Any]]:
    r = get_redis()
    return derive_gates(r)
