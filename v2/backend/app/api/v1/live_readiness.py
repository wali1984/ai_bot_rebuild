"""`/live-readiness/` — readiness banner state (residual from module map).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
This router is NOT under `/live/`, so it is NOT default-denied. It exposes
read-only banner state for the GUI; mutation lands behind L4 in milestone D.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/live-readiness", tags=["live-readiness"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "live_readiness",
    "prefix": "/live-readiness",
    "endpoints": ("/", "/banner"),
    "rbac": "read",
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
