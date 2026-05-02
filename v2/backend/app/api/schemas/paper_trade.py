"""Paper trade schema per 12B §9.7 (paper variant).

Carries the full upstream lineage chain.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.lineage import LineageBlock


class PaperTradeAck(BaseModel):
    """Ack payload for `POST /api/v1/paper-trades`."""

    model_config = ConfigDict(extra="forbid")

    paper_trade_id: str
    fill_price: float = Field(ge=0.0)
    fill_qty: float = Field(ge=0.0)
    fill_ts: str
    lineage: LineageBlock


class PaperTradeRead(PaperTradeAck):
    """Read-side payload for `GET /api/v1/paper-trades/{id}`."""
