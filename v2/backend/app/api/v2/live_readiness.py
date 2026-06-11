"""B7: live-readiness gates route.

Returns the 8-gate matrix used by section 09 of the redesigned landing.
All derivation is delegated to `app.services.live_readiness.derive_gates`.

G8 (L5 approval recorded) is ALWAYS `blocked` until
`audit:live_enable:last_approval_id` exists in Redis. There is no UI
control wired anywhere that can flip this.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis
from app.services.live_readiness import derive_gates

router = APIRouter(prefix="/live-readiness", tags=["v2-landing"])


@router.get("/gates")
async def get_live_readiness_gates() -> list[dict[str, Any]]:
    r = get_redis()
    return derive_gates(r)
