from __future__ import annotations

from typing import Any

from .contracts import IntegrityThresholds
from .scoring import score_market_state


def classify_training_sample(row: dict[str, Any], thresholds: IntegrityThresholds | None = None) -> dict[str, Any]:
    score = score_market_state(row, thresholds=thresholds)
    accepted = score.valid_for_training
    reasons = list(score.reject_reasons)
    if score.market_state_integrity_score < (thresholds or IntegrityThresholds()).training_min_score:
        reasons.append("MARKET_STATE_INTEGRITY_SCORE_BELOW_TRAINING_MIN")
    return {
        "market_state_id": score.market_state_id,
        "feature_snapshot_id": row.get("feature_snapshot_id"),
        "prediction_id": row.get("prediction_id"),
        "accepted_for_training": accepted,
        "market_state_integrity_score": score.market_state_integrity_score,
        "valid_for_training": score.valid_for_training,
        "reject_reasons": sorted(set(reasons)),
        "source_lineage": score.source_lineage,
    }
