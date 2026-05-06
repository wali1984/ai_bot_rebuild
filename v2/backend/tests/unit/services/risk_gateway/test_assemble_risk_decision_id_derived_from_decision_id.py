from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.services.risk_gateway import assemble_risk_decision_record


def test_assemble_risk_decision_id_derived_from_decision_id() -> None:
    decision = OrchestratorDecisionRecord(
        decision_id="dec_pred_abc",
        prediction_id="pred_id",
        feature_snapshot_id="snap_id",
        symbol="BTCUSDT",
        decision_ts_ms=1,
        decision_action="open_long",
        decision_reason_code="proceed_long",
        input_prediction_direction="long",
        input_prediction_confidence_calibrated=0.85,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )

    assert assemble_risk_decision_record(
        decision=decision,
        now_ms_clock=lambda: 1,
    ).risk_decision_id == "rd_dec_pred_abc"
