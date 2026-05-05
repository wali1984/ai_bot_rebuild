from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_ABSTAIN,
    DECISION_REASON_ABSTAIN_WORKER_CRITICAL,
    OrchestratorDecisionRecord,
)


def test_record_happy_path_abstain_worker_critical_accepts_valid_inputs():
    record = OrchestratorDecisionRecord(
        decision_id="decision-abstain-critical",
        prediction_id="prediction-abstain-critical",
        feature_snapshot_id="snapshot-abstain-critical",
        symbol="XRPUSDT",
        decision_ts_ms=107,
        decision_action=DECISION_ACTION_ABSTAIN,
        decision_reason_code=DECISION_REASON_ABSTAIN_WORKER_CRITICAL,
        input_prediction_direction="short",
        input_prediction_confidence_calibrated=0.70,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="CRITICAL",
        live_blocked=True,
    )
    assert record.input_worker_health_status == "CRITICAL"
