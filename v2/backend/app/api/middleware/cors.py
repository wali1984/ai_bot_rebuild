"""CORS middleware for browser requests."""

from __future__ import annotations

from starlette.middleware.cors import CORSMiddleware as StarletteCORSMiddleware


class CORSMiddleware(StarletteCORSMiddleware):
    """Configure CORS to allow frontend dev server and production deployments."""

    def __init__(self, app):
        super().__init__(
            app=app,
            allow_origins=[
                "http://localhost:5173",  # Frontend dev server
                "http://localhost:3000",  # Alternative dev port
                "http://127.0.0.1:5173",
                "http://127.0.0.1:3000",
            ],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["content-length"],
        )
