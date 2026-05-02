"""`/feature-snapshots/` endpoints — chain root, lineage-bearing (§7, 12B §9.2).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/feature-snapshots", tags=["feature-snapshots"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "feature_snapshots",
    "prefix": "/feature-snapshots",
    "endpoints": ("/", "/{feature_snapshot_id}", "/{feature_snapshot_id}/explain"),
    "rbac": "mixed",
    "lineage_bearing": True,
    "stage_required_ids": ("feature_snapshot_id",),
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
