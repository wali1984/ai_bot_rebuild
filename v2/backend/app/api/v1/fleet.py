"""`/fleet/` endpoints — multi-trader fleet, paper-only (§7).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/fleet", tags=["fleet"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "fleet",
    "prefix": "/fleet",
    "endpoints": ("/", "/{trader_id}"),
    "rbac": "admin",
    "live_capable": False,
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
