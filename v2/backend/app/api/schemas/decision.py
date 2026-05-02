"""Orchestrator decision schema per 12B §9.5.

Required-non-null on the wire through `decision_id`.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.api.schemas.lineage import LineageBlock


class DecisionAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"


class DecisionIngest(BaseModel):
    """Ingest payload for `POST /api/v1/decisions`."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    decision_action: DecisionAction
    policy_trace_json: dict[str, Any]
    policy_version: str
    lineage: LineageBlock


class DecisionRead(DecisionIngest):
    """Read-side payload for `GET /api/v1/decisions/{id}`."""
