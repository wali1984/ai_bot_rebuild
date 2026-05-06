import pytest


def test_evaluator_propagates_service_error_for_long_decision_id():
    from v2.backend.app.composition.risk_gateway import build_risk_decision_evaluator
    from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
    from v2.backend.app.services.risk_gateway import RiskGatewayServiceError

    evaluator = build_risk_decision_evaluator(now_ms_clock=lambda: 1)
    decision = OrchestratorDecisionRecord(
        decision_id="d" * 126,
        prediction_id="prediction_1",
        feature_snapshot_id="feature_1",
        symbol="BTCUSD",
        decision_ts_ms=1,
        decision_action="hold",
        decision_reason_code="hold_flat_direction",
        input_prediction_direction="flat",
        input_prediction_confidence_calibrated=0.5,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )

    with pytest.raises(RiskGatewayServiceError) as exc_info:
        evaluator(decision=decision)
    assert exc_info.value.code == "decision_id_too_long_for_risk_decision_id_derivation"
    assert exc_info.value.field == "decision.decision_id"
