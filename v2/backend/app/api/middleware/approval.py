"""Layer 9: single-use consumption of L4/L5 approval tokens.

Scaffold-only passthrough. Token consumption / subject-mismatch detection
lands in milestone D proper.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class ApprovalMiddleware:
    """ASGI middleware shell for approval gate."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)
