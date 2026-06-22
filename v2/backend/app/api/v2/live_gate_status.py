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

from app.services.live_gate.runtime_execution_state import get_canonical_live_gate_status

router = APIRouter(prefix="/live-gate", tags=["v2-live-gate"])


@router.get("/status")
async def get_v2_live_gate_status() -> dict[str, Any]:
    """Canonical live-gate status.  Always blocked until full operator flow."""
    return get_canonical_live_gate_status()
