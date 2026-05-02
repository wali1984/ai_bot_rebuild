"""Layer 11: SQLAlchemy/PG error → taxonomy mapper.

Scaffold-only passthrough. Constraint-name → error-class mapping lands in
milestone D proper per §6 of the route plan.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class DbErrorTranslatorMiddleware:
    """ASGI middleware shell for DB error translation."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)
