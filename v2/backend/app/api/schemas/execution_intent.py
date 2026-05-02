"""Execution intent schema per 12B §9.7.

Full upstream chain through `risk_decision_id` is required. The resolved
`risk_decisions.allow_block` MUST be `'allow'` server-side; live-mode adds
the §7 live-block AFTER lineage validation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.lineage import LineageBlock


class ExecutionIntentSubmit(BaseModel):
    """Submit payload for `POST /api/v1/execution-intents`."""

    model_config = ConfigDict(extra="forbid")

    execution_intent_id: str
    symbol: str
    side: str
    qty: float = Field(gt=0.0)
    order_type: str
    mode: str = Field(default="paper")
    lineage: LineageBlock


class ExecutionIntentRead(ExecutionIntentSubmit):
    """Read-side payload for `GET /api/v1/execution-intents/{id}`."""
