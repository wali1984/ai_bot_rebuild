"""Layer 2: admin-surface IP allowlist (per §3 of 04 plan).

Scaffold-only passthrough. Allowlist evaluation lands in milestone D proper.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class IpAllowlistMiddleware:
    """ASGI middleware shell for IP allowlist."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)
