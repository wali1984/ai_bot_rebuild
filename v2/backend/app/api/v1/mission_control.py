"""`/mission-control/` — overview surface (residual from module map).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/mission-control", tags=["mission-control"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "mission_control",
    "prefix": "/mission-control",
    "endpoints": ("/",),
    "rbac": "read",
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
