"""`/risk-decisions/` endpoints — risk-gateway decisions (§7, 12B §9.6).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
This is the dedicated risk-decision lineage endpoint per the §7 split from
the broader `/risk/` policy/kill-switch surface.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/risk-decisions", tags=["risk-decisions"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "risk_decisions",
    "prefix": "/risk-decisions",
    "endpoints": ("/", "/{risk_decision_id}", "/{risk_decision_id}/explain"),
    "rbac": "internal",
    "lineage_bearing": True,
    "stage_required_ids": (
        "feature_snapshot_id",
        "prediction_id",
        "signal_id",
        "decision_id",
        "risk_decision_id",
    ),
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
