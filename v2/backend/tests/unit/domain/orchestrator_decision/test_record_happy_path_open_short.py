from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_OPEN_SHORT,
    DECISION_REASON_PROCEED_SHORT,
    OrchestratorDecisionRecord,
)


def test_record_happy_path_open_short_preserves_fields():
    record = OrchestratorDecisionRecord(
        decision_id="decision-short",
        prediction_id="prediction-short",
        feature_snapshot_id="snapshot-short",
        symbol="ETHUSDT",
        decision_ts_ms=101,
        decision_action=DECISION_ACTION_OPEN_SHORT,
        decision_reason_code=DECISION_REASON_PROCEED_SHORT,
        input_prediction_direction="short",
        input_prediction_confidence_calibrated=0.75,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )
    assert record.decision_action == DECISION_ACTION_OPEN_SHORT
    assert record.decision_reason_code == DECISION_REASON_PROCEED_SHORT
    assert record.input_prediction_direction == "short"
