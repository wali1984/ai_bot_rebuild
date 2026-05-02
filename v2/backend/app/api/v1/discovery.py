"""`/discovery/` endpoints — passive market discovery feed (§7).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/discovery", tags=["discovery"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "discovery",
    "prefix": "/discovery",
    "endpoints": ("/", "/{discovery_id}"),
    "rbac": "read",
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
