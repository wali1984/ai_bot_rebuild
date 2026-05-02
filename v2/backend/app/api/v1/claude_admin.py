"""`/claude-admin/` endpoints — Claude AI supervision (§7).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/claude-admin", tags=["claude-admin"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "claude_admin",
    "prefix": "/claude-admin",
    "endpoints": ("/sessions", "/tasks", "/health"),
    "rbac": "admin",
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
