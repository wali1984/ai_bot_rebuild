"""Request envelope models (mirrors `app.api.errors.envelope` for input).

Every request that carries a body uses `RequestEnvelope` so middleware can
read `request_id` / `idempotency_key` / `etag` uniformly.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class RequestEnvelope(BaseModel):
    """Top-level wrapper for incoming bodies."""

    model_config = ConfigDict(extra="forbid")

    request_id: str | None = None
    idempotency_key: str | None = None
    if_match: str | None = None
    data: Any | None = None
