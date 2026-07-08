"""FastAPI application factory for the V2 backend.

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

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.services.backend_shutdown import cancel_and_wait_for_registered_tasks, reset_shutdown_signal

from app.api.middleware import MIDDLEWARE_ORDER
from app.api.auth_rbac import router as auth_rbac_router
from app.api.v2 import router as v2_router
from app.api.v2.market_contracts import stream_router as market_stream_router
from app.api.v1 import (
    accounts,
    audit,
    auth,
    chart,
    claude_admin,
    live_gate,
    codex_review,
    decisions,
    derivatives,
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
        chart.router,
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
        derivatives.router,
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
        live_gate.public_status_router,
        live_gate.router,
    )
    for r in routers:
        app.include_router(r, prefix="/api/v1")
    app.include_router(auth_rbac_router)
    app.include_router(v2_router)
    app.include_router(market_stream_router)


def _register_health_aliases(app: FastAPI) -> None:
    """Register canonical /health and /api/health endpoints.

    The v1 health router lives at /api/v1/_meta/health; these aliases give
    load-balancers and Playwright tests a stable canonical liveness check
    without depending on versioned paths.
    """
    @app.get("/health", tags=["health"], include_in_schema=False)
    async def root_health() -> dict:
        return {
            "status": "ok",
            "service": "v2-backend",
            "places_real_order": False,
            "live_gate": "blocked_human_only",
            "generated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

    @app.get("/api/health", tags=["health"], include_in_schema=False)
    async def api_health() -> dict:
        return {
            "status": "ok",
            "service": "v2-backend",
            "places_real_order": False,
            "live_gate": "blocked_human_only",
            "generated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }


_REBUILD_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_PUBLIC_DIR = os.path.join(_REBUILD_ROOT, "frontend", "public")
_DIST_DIR = os.path.join(_REBUILD_ROOT, "frontend", "dist")
_OPERATOR_RUNTIME_STATIC_DIR_ENV = "V2_OPERATOR_RUNTIME_STATIC_DIR"


def _operator_runtime_static_dir() -> str | None:
    configured = os.environ.get(_OPERATOR_RUNTIME_STATIC_DIR_ENV, "").strip()
    if configured:
        candidate = os.path.abspath(os.path.expanduser(configured))
        return candidate if os.path.isdir(candidate) else None

    for base_dir in (_PUBLIC_DIR, _DIST_DIR):
        candidate = os.path.join(base_dir, "operator_runtime")
        if os.path.isdir(candidate):
            return candidate
    return None


def _register_spa(app: FastAPI) -> None:
    """Serve the built React SPA from v2/frontend/dist/.

    Mount order matters — /assets and /operator_runtime are mounted as
    StaticFiles sub-apps first so they take prefix-matched precedence over the
    catch-all SPA route. The catch-all is registered last so it never shadows
    API routes that were registered earlier via _register_routers().
    """
    if not os.path.isdir(_DIST_DIR):
        return

    assets_dir = os.path.join(_DIST_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="static-assets")

    operator_runtime_dir = _operator_runtime_static_dir()
    if operator_runtime_dir:
        app.mount(
            "/operator_runtime",
            StaticFiles(directory=operator_runtime_dir),
            name="operator-runtime",
        )

    index_html = os.path.join(_DIST_DIR, "index.html")
    sw_js = os.path.join(_DIST_DIR, "service-worker.js")
    manifest_file = os.path.join(_DIST_DIR, "manifest.webmanifest")

    if os.path.isfile(sw_js):
        @app.get("/service-worker.js", include_in_schema=False)
        async def serve_sw() -> FileResponse:
            return FileResponse(sw_js, media_type="application/javascript")

    if os.path.isfile(manifest_file):
        @app.get("/manifest.webmanifest", include_in_schema=False)
        async def serve_manifest() -> FileResponse:
            return FileResponse(manifest_file, media_type="application/manifest+json")

    if os.path.isfile(index_html):
        # Serve the SPA shell from memory: FileResponse waits on the shared
        # anyio threadpool, which market-data calls can saturate, turning a
        # 1ms index.html into multi-second TTFB. The shell is tiny and only
        # changes on deploy (process restart), so cache the bytes once.
        index_bytes = open(index_html, "rb").read()
        index_mtime = os.path.getmtime(index_html)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            nonlocal index_bytes, index_mtime
            requested_file = _safe_dist_file_path(full_path)
            if requested_file:
                return FileResponse(requested_file)
            try:
                current_mtime = os.path.getmtime(index_html)
            except OSError:
                return PlainTextResponse("Frontend build is temporarily unavailable.", status_code=503)
            if current_mtime != index_mtime:
                index_bytes = open(index_html, "rb").read()
                index_mtime = current_mtime
            return HTMLResponse(index_bytes)


def _safe_dist_file_path(full_path: str) -> str | None:
    """Return an existing file under dist for static Vite public assets."""
    dist_root = os.path.abspath(_DIST_DIR)
    candidate = os.path.abspath(os.path.join(dist_root, full_path.lstrip("/")))
    try:
        if os.path.commonpath([dist_root, candidate]) != dist_root:
            return None
    except ValueError:
        return None
    if os.path.isfile(candidate):
        return candidate
    return None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    reset_shutdown_signal()
    # Market-data endpoints run blocking HTTP fetches in the shared anyio
    # threadpool (default 40 tokens); WS resource streams + SWR refreshes can
    # exhaust it and stall every other threadpool user. Raise the ceiling.
    try:
        import anyio.to_thread

        anyio.to_thread.current_default_thread_limiter().total_tokens = int(
            os.environ.get("V2_THREADPOOL_TOKENS", "120")
        )
    except Exception:
        pass
    try:
        yield
    finally:
        pending = await cancel_and_wait_for_registered_tasks(timeout_seconds=2.0)
        app.state.shutdown_pending_tasks = [
            {
                "label": item.label,
                "task_name": item.task_name,
                "done": item.done,
                "cancelled": item.cancelled,
                "age_ms": item.age_ms,
            }
            for item in pending
        ]


def create_app() -> FastAPI:
    """Construct the FastAPI app. No startup side effects beyond router/middleware
    registration and the middleware-order assertion."""
    app = FastAPI(title="NERVYX ONE", version="0.0.0", docs_url="/api/docs", lifespan=_lifespan)
    _register_middleware(app)
    _register_routers(app)
    _register_health_aliases(app)
    _assert_middleware_order(app)
    _register_spa(app)
    return app
