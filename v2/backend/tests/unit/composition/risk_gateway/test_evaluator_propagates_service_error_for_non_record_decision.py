import pytest


def test_evaluator_propagates_service_error_for_non_record_decision():
    from v2.backend.app.composition.risk_gateway import build_risk_decision_evaluator
    from v2.backend.app.services.risk_gateway import RiskGatewayServiceError

    evaluator = build_risk_decision_evaluator(now_ms_clock=lambda: 1)

    with pytest.raises(RiskGatewayServiceError) as exc_info:
        evaluator(decision="not a record")
    assert exc_info.value.code == "must_be_orchestrator_decision_record"
    assert exc_info.value.field == "decision"
