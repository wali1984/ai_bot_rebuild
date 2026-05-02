"""Layer 3: per-actor token-bucket rate limit.

Scaffold-only passthrough. Bucket implementation lands in milestone D proper.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class RateLimitMiddleware:
    """ASGI middleware shell for rate limit."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)
