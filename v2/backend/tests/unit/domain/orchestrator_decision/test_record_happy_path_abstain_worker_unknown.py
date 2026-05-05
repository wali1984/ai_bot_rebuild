from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_ABSTAIN,
    DECISION_REASON_ABSTAIN_WORKER_UNKNOWN,
    OrchestratorDecisionRecord,
)


def test_record_happy_path_abstain_worker_unknown_accepts_valid_inputs():
    record = OrchestratorDecisionRecord(
        decision_id="decision-abstain-unknown",
        prediction_id="prediction-abstain-unknown",
        feature_snapshot_id="snapshot-abstain-unknown",
        symbol="BNBUSDT",
        decision_ts_ms=108,
        decision_action=DECISION_ACTION_ABSTAIN,
        decision_reason_code=DECISION_REASON_ABSTAIN_WORKER_UNKNOWN,
        input_prediction_direction="flat",
        input_prediction_confidence_calibrated=0.55,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="UNKNOWN",
        live_blocked=True,
    )
    assert record.input_worker_health_status == "UNKNOWN"
