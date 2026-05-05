from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_ABSTAIN,
    DECISION_REASON_ABSTAIN_LOW_CONFIDENCE,
    OrchestratorDecisionRecord,
)


def test_record_happy_path_abstain_low_confidence_accepts_valid_inputs():
    record = OrchestratorDecisionRecord(
        decision_id="decision-abstain-low",
        prediction_id="prediction-abstain-low",
        feature_snapshot_id="snapshot-abstain-low",
        symbol="BTCUSDT",
        decision_ts_ms=103,
        decision_action=DECISION_ACTION_ABSTAIN,
        decision_reason_code=DECISION_REASON_ABSTAIN_LOW_CONFIDENCE,
        input_prediction_direction="long",
        input_prediction_confidence_calibrated=0.10,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )
    assert record.decision_reason_code == DECISION_REASON_ABSTAIN_LOW_CONFIDENCE
