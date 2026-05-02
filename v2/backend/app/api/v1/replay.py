"""`/replay/` endpoints — deterministic replay (§7).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/replay", tags=["replay"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "replay",
    "prefix": "/replay",
    "endpoints": ("/", "/{replay_id}"),
    "rbac": "admin",
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
