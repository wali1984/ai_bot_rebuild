"""`/selection/` endpoints — adaptive selection what-if and outputs (§7).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/selection", tags=["selection"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "selection",
    "prefix": "/selection",
    "endpoints": ("/", "/what-if", "/outputs"),
    "rbac": "read",
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
