from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_OPEN_LONG,
    DECISION_REASON_PROCEED_LONG,
    OrchestratorDecisionRecord,
)


def test_record_happy_path_open_long_preserves_fields():
    record = OrchestratorDecisionRecord(
        decision_id="decision-long",
        prediction_id="prediction-long",
        feature_snapshot_id="snapshot-long",
        symbol="BTCUSDT",
        decision_ts_ms=100,
        decision_action=DECISION_ACTION_OPEN_LONG,
        decision_reason_code=DECISION_REASON_PROCEED_LONG,
        input_prediction_direction="long",
        input_prediction_confidence_calibrated=0.85,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )
    assert record.decision_id == "decision-long"
    assert record.prediction_id == "prediction-long"
    assert record.feature_snapshot_id == "snapshot-long"
    assert record.symbol == "BTCUSDT"
    assert record.decision_ts_ms == 100
    assert record.decision_action == DECISION_ACTION_OPEN_LONG
    assert record.decision_reason_code == DECISION_REASON_PROCEED_LONG
    assert record.input_prediction_direction == "long"
    assert record.input_prediction_confidence_calibrated == 0.85
    assert record.input_prediction_freshness_flag == "fresh"
    assert record.input_worker_health_status == "HEALTHY"
    assert record.live_blocked is True
