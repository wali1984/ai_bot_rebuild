"""FastAPI application factory for AI BOT V2.

This module performs no I/O at import. The factory `create_app()` constructs
a FastAPI app and registers v1 routers. Routers expose no handler bodies in
the milestone B scaffold; handlers are added in later milestones.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.v1 import (
    audit,
    claude_admin,
    codex_review,
    decisions,
    discovery,
    evidence,
    exchanges,
    features,
    fleet,
    governance,
    health,
    ingestors,
    intents,
    live_mode,
    live_readiness,
    mission_control,
    monitor,
    ollama_assistant,
    paper,
    predictions,
    replay,
    risk,
    selection,
    signals,
    universe,
)


def create_app() -> FastAPI:
    """Construct the FastAPI app. No startup side effects."""
    app = FastAPI(title="AI BOT V2", version="0.0.0", docs_url="/api/docs")
    routers = (
        audit.router,
        claude_admin.router,
        codex_review.router,
        decisions.router,
        discovery.router,
        evidence.router,
        exchanges.router,
        features.router,
        fleet.router,
        governance.router,
        health.router,
        ingestors.router,
        intents.router,
        live_mode.router,
        live_readiness.router,
        mission_control.router,
        monitor.router,
        ollama_assistant.router,
        paper.router,
        predictions.router,
        replay.router,
        risk.router,
        selection.router,
        signals.router,
        universe.router,
    )
    for r in routers:
        app.include_router(r, prefix="/api/v1")
    return app