"""Risk decision schema per 12B §9.6.

Required-non-null on the wire through `decision_id` + `risk_decision_id`. The
`(allow ↔ block_reason)` conditional is enforced server-side; this schema
expresses the wire shape only.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.api.schemas.lineage import LineageBlock


class AllowBlock(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"


class RiskDecisionIngest(BaseModel):
    """Ingest payload for `POST /api/v1/risk-decisions`."""

    model_config = ConfigDict(extra="forbid")

    risk_decision_id: str
    allow_block: AllowBlock
    block_reason: str | None = None
    policy_checks_json: dict[str, Any]
    policy_bundle_id: str
    lineage: LineageBlock


class RiskDecisionRead(RiskDecisionIngest):
    """Read-side payload for `GET /api/v1/risk-decisions/{id}`."""
