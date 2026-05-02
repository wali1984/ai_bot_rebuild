"""FastAPI application factory for AI BOT V2.

This module performs no I/O at import. The factory `create_app()`:

1. constructs a FastAPI app
2. registers middleware in the canonical order from
   `claude_worklog/v2_scaffold_planning/04_API_ROUTE_SCAFFOLD_PLAN.md` §3
3. registers v1 routers (every §7 endpoint group) under `/api/v1`
4. asserts the registered middleware order matches `MIDDLEWARE_ORDER`

Routers expose no handler bodies in this skeleton; only OPTIONS shims that
return route metadata. Handlers, validators, and DB/Redis I/O land in
milestone D proper.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.middleware import MIDDLEWARE_ORDER
from app.api.v1 import (
    accounts,
    audit,
    auth,
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
    risk_decisions,
    selection,
    signals,
    universe,
)


def _register_middleware(app: FastAPI) -> None:
    """Register middleware so MIDDLEWARE_ORDER[0] is the outermost layer.

    Starlette wraps middleware via `reversed(self.user_middleware)`, and
    `add_middleware()` inserts at index 0, so iterating MIDDLEWARE_ORDER in
    its declared (outermost→innermost) order and calling `add_middleware`
    each pass yields the correct stack: the first declared layer ends up
    outermost at request time.
    """
    for cls in MIDDLEWARE_ORDER:
        app.add_middleware(cls)


def _assert_middleware_order(app: FastAPI) -> None:
    """Startup assertion per §3: any reorder fails app construction."""
    actual = tuple(m.cls for m in app.user_middleware)
    expected = tuple(reversed(MIDDLEWARE_ORDER))
    if actual != expected:
        raise RuntimeError(
            "Middleware stack drifted from MIDDLEWARE_ORDER. "
            f"Expected {[c.__name__ for c in expected]}, "
            f"got {[c.__name__ for c in actual]}."
        )


def _register_routers(app: FastAPI) -> None:
    """Mount every §7 endpoint group under `/api/v1`."""
    routers = (
        # §7: /_meta/, /auth/, /accounts/
        health.router,
        auth.router,
        accounts.router,
        # §7: /exchanges/, /universe/, /discovery/, /selection/
        exchanges.router,
        universe.router,
        discovery.router,
        selection.router,
        # §7: lineage chain — /feature-snapshots/, /predictions/, /signals/,
        #                     /decisions/, /risk-decisions/, /execution-intents/,
        #                     /paper-trades/
        features.router,
        predictions.router,
        signals.router,
        decisions.router,
        risk_decisions.router,
        intents.router,
        paper.router,
        # §7: /risk/, /replay/, /fleet/, /monitor/, /evidence/, /audit/, /governance/
        risk.router,
        replay.router,
        fleet.router,
        monitor.router,
        evidence.router,
        audit.router,
        governance.router,
        # §7: /claude-admin/, /codex/, /ollama/
        claude_admin.router,
        codex_review.router,
        ollama_assistant.router,
        # §7: /live/ — default-denied by live_block_guard
        live_mode.router,
        # Module-map residuals (not in §7 but planned by 02): mission-control,
        # ingestors, live-readiness. These remain skeleton-only.
        mission_control.router,
        ingestors.router,
        live_readiness.router,
    )
    for r in routers:
        app.include_router(r, prefix="/api/v1")


def create_app() -> FastAPI:
    """Construct the FastAPI app. No startup side effects beyond router/middleware
    registration and the middleware-order assertion."""
    app = FastAPI(title="AI BOT V2", version="0.0.0", docs_url="/api/docs")
    _register_middleware(app)
    _register_routers(app)
    _assert_middleware_order(app)
    return app
