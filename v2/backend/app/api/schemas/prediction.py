"""Prediction schema per 12B §9.3.

Required-non-null on the wire: `feature_snapshot_id`, `prediction_id`. All
downstream IDs in the lineage block MUST be explicit `null`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.lineage import LineageBlock


class PredictionIngest(BaseModel):
    """Ingest payload for `POST /api/v1/predictions`."""

    model_config = ConfigDict(extra="forbid")

    prediction_id: str
    model_version: str
    checkpoint_id: str
    raw_output_json: dict[str, Any]
    confidence_score: float = Field(ge=0.0, le=1.0)
    lineage: LineageBlock


class PredictionRead(PredictionIngest):
    """Read-side payload for `GET /api/v1/predictions/{id}`."""
