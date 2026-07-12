"""V2 live-gate status — canonical single source of truth.

Exposes ``GET /api/v2/live-gate/status`` via the canonical
``get_canonical_live_gate_status()`` function so that frontend, backend, and
tests all agree on the gate value.  This route is read-only and cannot mutate
the gate state; the actual gate state is always ``blocked_human_only`` until
the full human approval flow in ``/api/v1/live-gate`` is completed.

The canonical function adds a ``conflict_check`` field proving there is no
split-brain between ``enabled_operator_approved`` and ``blocked_human_only``
display.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis
from app.api.v2.control_center_status import (
    _current_a_grade_blocker_truth,
    _real_trader_readiness_from_a_grade_truth,
)
from app.services.live_gate.runtime_execution_state import get_canonical_live_gate_status

router = APIRouter(prefix="/live-gate", tags=["v2-live-gate"])


@router.get("/status")
async def get_v2_live_gate_status() -> dict[str, Any]:
    """Canonical live-gate status.  Always blocked until full operator flow."""
    payload = dict(get_canonical_live_gate_status())
    truth = _current_a_grade_blocker_truth(get_redis())
    readiness = _real_trader_readiness_from_a_grade_truth(truth)
    payload["real_trader_readiness"] = readiness
    payload["a_grade_blocker_truth"] = truth
    payload["exact_no_live_reason"] = readiness["exact_no_live_reason"]
    payload["readiness_blockers"] = readiness["readiness_blockers"]
    payload["top_blockers"] = readiness["readiness_blockers"][:8]
    payload["live_ready"] = False
    payload["live_submit_allowed"] = False
    payload["routes_to_live"] = False
    payload["places_real_order"] = False
    payload["order_submitted"] = False
    payload["test_order_submitted"] = False
    payload["leverage_mutated"] = False
    payload["margin_mutated"] = False
    return payload
