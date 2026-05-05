from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_ABSTAIN,
    DECISION_REASON_ABSTAIN_FRESHNESS_STALE,
    OrchestratorDecisionRecord,
)


def test_record_happy_path_abstain_freshness_stale_accepts_valid_inputs():
    record = OrchestratorDecisionRecord(
        decision_id="decision-abstain-stale",
        prediction_id="prediction-abstain-stale",
        feature_snapshot_id="snapshot-abstain-stale",
        symbol="ETHUSDT",
        decision_ts_ms=104,
        decision_action=DECISION_ACTION_ABSTAIN,
        decision_reason_code=DECISION_REASON_ABSTAIN_FRESHNESS_STALE,
        input_prediction_direction="short",
        input_prediction_confidence_calibrated=0.65,
        input_prediction_freshness_flag="stale",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )
    assert record.input_prediction_freshness_flag == "stale"
