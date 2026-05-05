import pytest

from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_OPEN_LONG,
    DECISION_REASON_PROCEED_LONG,
    OrchestratorDecisionDomainError,
    OrchestratorDecisionRecord,
)


def test_record_validates_decision_ts_ms_type_and_range():
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
    for value in (1.0, "100", True, False):
        with pytest.raises(OrchestratorDecisionDomainError) as exc_info:
            OrchestratorDecisionRecord(**{**base, "decision_ts_ms": value})
        assert exc_info.value.field == "decision_ts_ms"
        assert exc_info.value.reason == "must_be_int"
    with pytest.raises(OrchestratorDecisionDomainError) as exc_info:
        OrchestratorDecisionRecord(**{**base, "decision_ts_ms": -1})
    assert exc_info.value.reason == "must_be_nonnegative"
    assert OrchestratorDecisionRecord(**{**base, "decision_ts_ms": 0}).decision_ts_ms == 0
