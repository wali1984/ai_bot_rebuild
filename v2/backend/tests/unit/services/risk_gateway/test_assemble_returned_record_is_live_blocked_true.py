from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.services.risk_gateway import assemble_risk_decision_record


def test_assemble_returned_record_is_live_blocked_true() -> None:
    decision = OrchestratorDecisionRecord(
        decision_id="dec_live_blocked",
        prediction_id="pred_live_blocked",
        feature_snapshot_id="snap_live_blocked",
        symbol="BTCUSDT",
        decision_ts_ms=10,
        decision_action="open_long",
        decision_reason_code="proceed_long",
        input_prediction_direction="long",
        input_prediction_confidence_calibrated=0.85,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )
    record = assemble_risk_decision_record(decision=decision, now_ms_clock=lambda: 1000)

    assert record.live_blocked is True
    assert record.live_blocked == True
    assert type(record.live_blocked) is bool
