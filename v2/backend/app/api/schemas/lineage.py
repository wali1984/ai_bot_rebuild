"""Canonical lineage block per 12B closure §1.3.1.

Every lineage-bearing request and response carries a seven-key `lineage`
object: six chain IDs plus `lineage_gap_reason`. Upstream IDs MUST be non-null
for the stage; downstream IDs MUST be explicit `null` (omission is malformed).

No I/O at import.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class LineageGapReason(str, Enum):
    """Permitted reasons for a null upstream ID inside the chain."""

    UPSTREAM_MISSING = "upstream_missing"
    DOWNSTREAM_NOT_YET_EMITTED = "downstream_not_yet_emitted"
    INGEST_PRE_ATTRIBUTION = "ingest_pre_attribution"
    REPLAY_PARTIAL = "replay_partial"


class LineageBlock(BaseModel):
    """Seven-key lineage block carried on every lineage-bearing payload.

    Per 12B §1.3.1 the keys MUST always be present; downstream slots are set
    to `null` rather than omitted. Schema validation rejects extra keys.
    """

    model_config = ConfigDict(extra="forbid")

    feature_snapshot_id: str | None = None
    prediction_id: str | None = None
    signal_id: str | None = None
    decision_id: str | None = None
    risk_decision_id: str | None = None
    execution_intent_id: str | None = None
    lineage_gap_reason: LineageGapReason | None = None


CHAIN_FIELDS: tuple[str, ...] = (
    "feature_snapshot_id",
    "prediction_id",
    "signal_id",
    "decision_id",
    "risk_decision_id",
    "execution_intent_id",
)
