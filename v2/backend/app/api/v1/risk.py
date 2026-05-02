"""`/risk/` endpoints — policy bundles, kill switch, live readiness (§7).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/risk", tags=["risk"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "risk",
    "prefix": "/risk",
    "endpoints": ("/policy-bundles", "/kill-switch", "/live-readiness"),
    "rbac": "admin",
    "approval_required": "L4",
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
