def test_public_surface():
    from v2.backend.app.composition import risk_gateway

    assert risk_gateway.__all__ == (
        "build_risk_decision_evaluator",
        "RiskDecisionEvaluator",
        "RiskGatewayCompositionError",
    )
    assert callable(risk_gateway.build_risk_decision_evaluator)
    assert isinstance(risk_gateway.RiskGatewayCompositionError, type)
    assert issubclass(risk_gateway.RiskGatewayCompositionError, Exception)
    assert not issubclass(risk_gateway.RiskGatewayCompositionError, ValueError)
    assert risk_gateway.RiskDecisionEvaluator is not None
