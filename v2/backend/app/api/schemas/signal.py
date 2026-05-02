"""Signal schema per 12B §9.4.

Required-non-null on the wire through `signal_id`. Single-parent de-dup is
enforced server-side by `(prediction_id, publish_window_ms)`.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.lineage import LineageBlock


class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class SignalPublish(BaseModel):
    """Publish payload for `POST /api/v1/signals`."""

    model_config = ConfigDict(extra="forbid")

    signal_id: str
    action: SignalAction
    confidence: float = Field(ge=0.0, le=1.0)
    reason_json: dict[str, Any]
    publish_window_ms: int = Field(ge=0)
    lineage: LineageBlock


class SignalRead(SignalPublish):
    """Read-side payload for `GET /api/v1/signals/{id}`."""
