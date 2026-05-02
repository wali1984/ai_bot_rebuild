"""`/paper-trades/` endpoints — paper-mode acks, full chain (§7, 12B §9.7).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/paper-trades", tags=["paper-trades"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "paper_trades",
    "prefix": "/paper-trades",
    "endpoints": ("/", "/{paper_trade_id}", "/{paper_trade_id}/explain"),
    "rbac": "mixed",
    "lineage_bearing": True,
    "stage_required_ids": (
        "feature_snapshot_id",
        "prediction_id",
        "signal_id",
        "decision_id",
        "risk_decision_id",
        "execution_intent_id",
    ),
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
