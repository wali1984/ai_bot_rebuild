"""Feature snapshot schema per 12B §9.2 (chain root).

Required-non-null on the wire: `feature_snapshot_id`. All downstream IDs in
the lineage block MUST be explicit `null`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.lineage import LineageBlock


class FeatureSnapshotIngest(BaseModel):
    """Ingest payload for `POST /api/v1/feature-snapshots`."""

    model_config = ConfigDict(extra="forbid")

    feature_snapshot_id: str
    symbol: str
    timeframe: str
    captured_at: str
    feature_manifest_id: str
    completeness_pct: float = Field(ge=0.0, le=100.0)
    source_grounding: dict[str, str] = Field(default_factory=dict)
    lineage: LineageBlock


class FeatureSnapshotRead(FeatureSnapshotIngest):
    """Read-side payload for `GET /api/v1/feature-snapshots/{id}`."""
