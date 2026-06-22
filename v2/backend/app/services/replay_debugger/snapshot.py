from __future__ import annotations

from typing import Any

from v2.backend.app.services.market_state_integrity.replay_snapshot import build_replay_snapshot


def snapshot_from_prediction(
    prediction: dict[str, Any],
    integrity: dict[str, Any] | None = None,
    *,
    paper_candidate: dict[str, Any] | None = None,
    risk_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision_id = str(prediction.get("prediction_id") or prediction.get("feature_snapshot_id") or "missing_decision_id")
    return build_replay_snapshot(
        decision_id=decision_id,
        prediction=prediction,
        integrity=integrity or {},
        paper_candidate=paper_candidate,
        risk_decision=risk_decision,
    )
