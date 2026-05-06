from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.services.risk_gateway import assemble_risk_decision_record


def test_assemble_deny_orchestrator_held_for_hold() -> None:
    decision = OrchestratorDecisionRecord(
        decision_id="dec_hold",
        prediction_id="pred_hold",
        feature_snapshot_id="snap_hold",
        symbol="BTCUSDT",
        decision_ts_ms=10,
        decision_action="hold",
        decision_reason_code="hold_flat_direction",
        input_prediction_direction="flat",
        input_prediction_confidence_calibrated=0.85,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )
    record = assemble_risk_decision_record(decision=decision, now_ms_clock=lambda: 1000)

    assert record.risk_action == "deny"
    assert record.risk_reason_code == "deny_orchestrator_held"
    assert record.input_decision_action == "hold"
    assert record.input_decision_reason_code == "hold_flat_direction"
    assert record.live_blocked is True
