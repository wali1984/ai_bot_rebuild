"""Layer 5 (post-auth): step-up MFA gate for L3+ routes.

Scaffold-only passthrough. The `auth_session` middleware described in §3.4 of
the route plan is intentionally out of scope for this skeleton; step-up
enforcement lands in milestone D proper.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class StepUpMfaMiddleware:
    """ASGI middleware shell for step-up MFA."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)
