"""`/predictions/` endpoints — lineage-bearing (§7, 12B §9.3).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/predictions", tags=["predictions"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "predictions",
    "prefix": "/predictions",
    "endpoints": ("/", "/{prediction_id}", "/{prediction_id}/explain"),
    "rbac": "mixed",
    "lineage_bearing": True,
    "stage_required_ids": ("feature_snapshot_id", "prediction_id"),
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
