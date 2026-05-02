"""`/execution-intents/` endpoints — full upstream chain (§7, 12B §9.7).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
Live-mode submissions are still default-denied by `live_block_guard`; lineage
validation runs BEFORE the live-block check per 12B §9.7.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/execution-intents", tags=["execution-intents"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "execution_intents",
    "prefix": "/execution-intents",
    "endpoints": ("/", "/{execution_intent_id}", "/{execution_intent_id}/explain"),
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
