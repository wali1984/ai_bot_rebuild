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
    admin,
    alerts_contracts,
    audit_ledger,
    brand,
    codex_reviews,
    hourly_monitor,
    live_gate_status,
    live_readiness,
    market_contracts,
    mobile,
    monitoring_contracts,
    ollama,
    pipeline,
    public_status,
    replay,
    status_contracts,
    trainer,
    trader_snapshot,
)

router = APIRouter(prefix="/api/v2", tags=["v2-landing"])

router.include_router(admin.router)
router.include_router(market_contracts.router)
router.include_router(brand.router)
router.include_router(alerts_contracts.router)
router.include_router(status_contracts.router)
router.include_router(audit_ledger.router)
router.include_router(codex_reviews.router)
router.include_router(trainer.router)
router.include_router(ollama.router)
router.include_router(replay.router)
router.include_router(pipeline.router)
router.include_router(live_readiness.router)
router.include_router(live_gate_status.router)
router.include_router(public_status.router)
router.include_router(monitoring_contracts.router)
router.include_router(hourly_monitor.router)
router.include_router(mobile.router)
router.include_router(trader_snapshot.router)

__all__ = ["router"]
