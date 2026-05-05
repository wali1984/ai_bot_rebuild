import pytest

from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_HOLD,
    DECISION_REASON_HOLD_FLAT_DIRECTION,
    DECISION_REASON_PROCEED_LONG,
    OrchestratorDecisionDomainError,
    OrchestratorDecisionRecord,
)


def test_hold_requires_hold_flat_direction_reason_and_flat_direction():
    base = {
        "decision_id": "decision-1",
        "prediction_id": "prediction-1",
        "feature_snapshot_id": "snapshot-1",
        "symbol": "BTCUSDT",
        "decision_ts_ms": 1,
        "decision_action": DECISION_ACTION_HOLD,
        "decision_reason_code": DECISION_REASON_HOLD_FLAT_DIRECTION,
        "input_prediction_direction": "flat",
        "input_prediction_confidence_calibrated": 0.85,
        "input_prediction_freshness_flag": "fresh",
        "input_worker_health_status": "HEALTHY",
        "live_blocked": True,
    }
    with pytest.raises(OrchestratorDecisionDomainError) as exc_info:
        OrchestratorDecisionRecord(
            **{**base, "decision_reason_code": DECISION_REASON_PROCEED_LONG}
        )
    assert exc_info.value.field == "decision_reason_code"
    assert exc_info.value.reason == "hold_requires_hold_flat_direction_reason"
    with pytest.raises(OrchestratorDecisionDomainError) as exc_info:
        OrchestratorDecisionRecord(**{**base, "input_prediction_direction": "long"})
    assert exc_info.value.field == "input_prediction_direction"
    assert exc_info.value.reason == "hold_requires_flat_input_direction"
