from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.services.risk_gateway import assemble_risk_decision_record


def test_assemble_allow_open_long() -> None:
    decision = OrchestratorDecisionRecord(
        decision_id="dec_allow_long",
        prediction_id="pred_allow_long",
        feature_snapshot_id="snap_allow_long",
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

    assert record.risk_action == "allow"
    assert record.risk_reason_code == "allow_proceed_long"
    assert record.risk_decision_ts_ms == 1000
    assert record.risk_decision_id == "rd_dec_allow_long"
    assert record.live_blocked is True
    assert record.input_decision_action == "open_long"
    assert record.input_decision_reason_code == "proceed_long"
    assert record.prediction_id == "pred_allow_long"
    assert record.feature_snapshot_id == "snap_allow_long"
    assert record.symbol == "BTCUSDT"
