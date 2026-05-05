from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_HOLD,
    DECISION_REASON_HOLD_FLAT_DIRECTION,
    OrchestratorDecisionRecord,
)


def test_record_happy_path_hold_accepts_flat_direction():
    record = OrchestratorDecisionRecord(
        decision_id="decision-hold",
        prediction_id="prediction-hold",
        feature_snapshot_id="snapshot-hold",
        symbol="SOLUSDT",
        decision_ts_ms=102,
        decision_action=DECISION_ACTION_HOLD,
        decision_reason_code=DECISION_REASON_HOLD_FLAT_DIRECTION,
        input_prediction_direction="flat",
        input_prediction_confidence_calibrated=0.50,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )
    assert record.decision_action == DECISION_ACTION_HOLD
    assert record.input_prediction_direction == "flat"
