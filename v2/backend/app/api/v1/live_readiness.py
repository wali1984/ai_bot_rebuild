"""`/live-readiness/` — readiness banner state (residual from module map).

This router is NOT under `/live/`, so it is NOT default-denied by the
live-block guard. It exposes a strictly read-only banner view that the
GUI uses to render the online-readiness status without re-running the
write-side aggregator.

`GET /banner` calls
`app.proof.online_readiness_aggregator.build_online_readiness_rollup`
(the read-only build path) and returns the resulting dict as JSON. The
write-side helper `write_online_readiness_rollup` is intentionally NOT
imported here — this endpoint must never produce on-disk rollup files,
mutate Redis, contact an exchange, or spawn a child process.

Live trading remains BLOCKED; the response body always carries
`live_gate_status="blocked_human_only"`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.proof.online_readiness_aggregator import build_online_readiness_rollup

router = APIRouter(prefix="/live-readiness", tags=["live-readiness"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "live_readiness",
    "prefix": "/live-readiness",
    "endpoints": ("/", "/banner"),
    "rbac": "read",
    "milestone_d_status": "skeleton",
}

_REPO_ROOT_ENV = "V2_ONLINE_READINESS_REPO_ROOT"


def _resolve_repo_root() -> Path:
    """Resolve the repository root used to locate marker files.

    Resolution precedence:
    1. `V2_ONLINE_READINESS_REPO_ROOT` env var (used by tests with
       synthetic fixtures)
    2. derived from this file's location:
       `v1` → `api` → `app` → `backend` → `v2` → repo root
    """
    override = os.environ.get(_REPO_ROOT_ENV, "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[5]


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA


@router.get("/banner")
async def get_banner() -> dict[str, Any]:
    """Return the online-readiness rollup dict for the GUI banner.

    Strictly read-only: this handler opens marker files only via
    `Path.read_text(...)` inside the aggregator, never writes any file,
    and imports no Redis / exchange / subprocess surface.
    """
    return build_online_readiness_rollup(_resolve_repo_root())
