from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_ABSTAIN,
    DECISION_REASON_ABSTAIN_FRESHNESS_MISSING,
    OrchestratorDecisionRecord,
)


def test_record_happy_path_abstain_freshness_missing_accepts_valid_inputs():
    record = OrchestratorDecisionRecord(
        decision_id="decision-abstain-missing",
        prediction_id="prediction-abstain-missing",
        feature_snapshot_id="snapshot-abstain-missing",
        symbol="SOLUSDT",
        decision_ts_ms=105,
        decision_action=DECISION_ACTION_ABSTAIN,
        decision_reason_code=DECISION_REASON_ABSTAIN_FRESHNESS_MISSING,
        input_prediction_direction="flat",
        input_prediction_confidence_calibrated=0.0,
        input_prediction_freshness_flag="missing",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )
    assert record.input_prediction_freshness_flag == "missing"
