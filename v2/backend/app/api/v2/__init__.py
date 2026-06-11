"""V2 landing router package — Phase B routes for the redesigned landing.

All routes registered here are READ-ONLY. They never:
- place exchange orders / cancel orders / mutate leverage or margin
- write to legacy Redis keys
- restart or mutate any live runtime
- import trainer modules directly into the FastAPI process

The single aggregate router is exposed as `router` and mounted by
`app.main.create_app()` under `/api/v2`.

Each individual route module declares its own `APIRouter` and is
included into the aggregate router below.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v2 import (
    audit_ledger,
    codex_reviews,
    live_readiness,
    ollama,
    pipeline,
    public_status,
    replay,
    trainer,
)

router = APIRouter(prefix="/api/v2", tags=["v2-landing"])

router.include_router(audit_ledger.router)
router.include_router(codex_reviews.router)
router.include_router(trainer.router)
router.include_router(ollama.router)
router.include_router(replay.router)
router.include_router(pipeline.router)
router.include_router(live_readiness.router)
router.include_router(public_status.router)

__all__ = ["router"]
