import pytest

from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_OPEN_LONG,
    DECISION_REASON_PROCEED_LONG,
    DECISION_REASON_PROCEED_SHORT,
    OrchestratorDecisionDomainError,
    OrchestratorDecisionRecord,
)


def test_open_long_requires_proceed_long_reason_and_long_direction():
    base = {
        "decision_id": "decision-1",
        "prediction_id": "prediction-1",
        "feature_snapshot_id": "snapshot-1",
        "symbol": "BTCUSDT",
        "decision_ts_ms": 1,
        "decision_action": DECISION_ACTION_OPEN_LONG,
        "decision_reason_code": DECISION_REASON_PROCEED_LONG,
        "input_prediction_direction": "long",
        "input_prediction_confidence_calibrated": 0.85,
        "input_prediction_freshness_flag": "fresh",
        "input_worker_health_status": "HEALTHY",
        "live_blocked": True,
    }
    with pytest.raises(OrchestratorDecisionDomainError) as exc_info:
        OrchestratorDecisionRecord(
            **{**base, "decision_reason_code": DECISION_REASON_PROCEED_SHORT}
        )
    assert exc_info.value.field == "decision_reason_code"
    assert exc_info.value.reason == "open_long_requires_proceed_long_reason"
    with pytest.raises(OrchestratorDecisionDomainError) as exc_info:
        OrchestratorDecisionRecord(
            **{**base, "input_prediction_direction": "short"}
        )
    assert exc_info.value.field == "input_prediction_direction"
    assert exc_info.value.reason == "open_long_requires_long_input_direction"
