"""Response envelope models for NERVYX ONE API.

The envelope is the single canonical wrapper for every API response. Success
responses carry `data`; failure responses carry `error` populated with a class
from `app.api.errors.taxonomy`.

No I/O at import.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    """Failure envelope error body. `class_` is serialized as `class` on the wire."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    class_: str = Field(alias="class")
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class ResponseEnvelope(BaseModel):
    """Top-level wrapper. Exactly one of `data` or `error` is non-null."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = ""
    data: Any | None = None
    error: ErrorBody | None = None
