"""Layer 6: route-level RBAC role check.

Scaffold-only passthrough. Role mapping lands in milestone D proper.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class RbacMiddleware:
    """ASGI middleware shell for RBAC."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)
