"""Layer 10: default-deny guard for `/api/v1/live/**`.

The §3 contract is binding: any request whose path is `/api/v1/live` or
begins with `/api/v1/live/` is rejected with HTTP 403 and the canonical
`live.blocked_default` envelope. This default holds until L5 readiness gating
flips the state in milestone L.

This is the ONLY middleware shell that ships with behavior in the milestone D
skeleton, because the default-deny invariant must be honored from the moment
a router is added under `/live`.
"""

from __future__ import annotations

import json
from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_BLOCKED_BODY: Final[bytes] = json.dumps(
    {
        "request_id": "",
        "data": None,
        "error": {
            "class": "live.blocked_default",
            "message": "Live mode is blocked by default. L5 readiness gate has not flipped.",
            "details": {"banner": "LIVE TRADING: BLOCKED"},
        },
    },
    separators=(",", ":"),
).encode("utf-8")


class LiveBlockGuardMiddleware:
    """Default-deny every `/api/v1/live/**` route."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "http":
            path = scope.get("path", "")
            if path == "/api/v1/live" or path.startswith("/api/v1/live/"):
                start: Message = {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(_BLOCKED_BODY)).encode("ascii")),
                        (b"x-live-blocked", b"default"),
                    ],
                }
                body: Message = {"type": "http.response.body", "body": _BLOCKED_BODY}
                await send(start)
                await send(body)
                return
        await self.app(scope, receive, send)
