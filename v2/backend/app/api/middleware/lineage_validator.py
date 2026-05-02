"""Layer 8: pre-handler lineage validation per 12B §9.1.

Scaffold-only passthrough. The nine validators (shape, type, stage-required,
gap-reason, parent-existence, cross-symbol, chain-coherence, immutability,
single-parent uniqueness) land in milestone D proper.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class LineageValidatorMiddleware:
    """ASGI middleware shell for lineage validation."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)
