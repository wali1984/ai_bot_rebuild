"""`/live/` endpoints — default-deny, L5-gated (§7).

Scaffold-only: `prefix=` is `/live`. EVERY request to a path under `/api/v1/live`
is intercepted by `live_block_guard` middleware (layer 10 of the §3 stack)
and returned 403 with `live.blocked_default`. The OPTIONS shim is similarly
intercepted; this is intentional and proves the default-deny invariant.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/live", tags=["live"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "live",
    "prefix": "/live",
    "endpoints": ("/orders", "/positions", "/cancel"),
    "rbac": "live_admin",
    "approval_required": "L5",
    "default_deny": True,
    "milestone_d_status": "skeleton-blocked",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
