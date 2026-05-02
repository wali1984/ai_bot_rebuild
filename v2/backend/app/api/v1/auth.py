"""`/auth/` endpoints — login, logout, MFA, step-up, refresh, revocation (§7).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
No handler bodies that perform DB/Redis I/O.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "auth",
    "prefix": "/auth",
    "endpoints": (
        "/login",
        "/logout",
        "/mfa",
        "/step-up",
        "/session/refresh",
        "/tokens/revoke",
    ),
    "rbac": "public",
    "milestone_d_status": "skeleton",
}


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA
