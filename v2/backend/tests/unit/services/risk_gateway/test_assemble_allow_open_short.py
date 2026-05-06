from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.services.risk_gateway import assemble_risk_decision_record


def test_assemble_allow_open_short() -> None:
    decision = OrchestratorDecisionRecord(
        decision_id="dec_allow_short",
        prediction_id="pred_allow_short",
        feature_snapshot_id="snap_allow_short",
        symbol="BTCUSDT",
        decision_ts_ms=10,
        decision_action="open_short",
        decision_reason_code="proceed_short",
        input_prediction_direction="short",
        input_prediction_confidence_calibrated=0.85,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )
    record = assemble_risk_decision_record(decision=decision, now_ms_clock=lambda: 1000)

    assert record.risk_action == "allow"
    assert record.risk_reason_code == "allow_proceed_short"
    assert record.input_decision_action == "open_short"
    assert record.input_decision_reason_code == "proceed_short"
