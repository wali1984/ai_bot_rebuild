"""`/exchanges/` endpoints — connectors, capabilities, health, credentials (§7).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/exchanges", tags=["exchanges"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "exchanges",
    "prefix": "/exchanges",
    "endpoints": ("/", "/{exchange_id}", "/{exchange_id}/capabilities", "/{exchange_id}/health"),
    "rbac": "mixed",
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
