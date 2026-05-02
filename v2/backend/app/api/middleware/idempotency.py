"""Layer 7: idempotency-key dedup for POST/PUT/PATCH/DELETE.

Scaffold-only passthrough. Replay-byte-identical store lands in milestone D
proper. Lineage is included in body_hash per 12B §4.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class IdempotencyMiddleware:
    """ASGI middleware shell for idempotency."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)
