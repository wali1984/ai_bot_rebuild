"""Layer 1 of the §3 stack: X-Request-Id (UUIDv7) assignment/validation.

Scaffold-only: passthrough. No I/O. Header parsing/assignment lands in
milestone D proper.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class RequestIdMiddleware:
    """ASGI middleware shell for X-Request-Id."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)
