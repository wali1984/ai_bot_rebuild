"""`/accounts/` endpoints — users, role binding (admin) (§7).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/accounts", tags=["accounts"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "accounts",
    "prefix": "/accounts",
    "endpoints": ("/", "/{account_id}", "/{account_id}/roles"),
    "rbac": "admin",
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
