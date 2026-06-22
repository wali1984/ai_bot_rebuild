"""Layer 8: pre-handler lineage validation per 12B §9.1.

Scaffold-only passthrough. The nine validators (shape, type, stage-required,
gap-reason, parent-existence, cross-symbol, chain-coherence, immutability,
single-parent uniqueness) land in milestone D proper.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class LineageValidatorMiddleware(BaseHTTPMiddleware):
    """ASGI middleware shell for lineage validation."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        return await call_next(request)
