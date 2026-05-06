def test_public_surface() -> None:
    from v2.backend.app.services import risk_gateway

    assert risk_gateway.__all__ == (
        "assemble_risk_decision_record",
        "RiskGatewayServiceError",
    )
    assert callable(risk_gateway.assemble_risk_decision_record)
    assert issubclass(risk_gateway.RiskGatewayServiceError, ValueError)
