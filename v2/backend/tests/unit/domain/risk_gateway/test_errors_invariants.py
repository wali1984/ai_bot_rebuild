from v2.backend.app.domain.risk_gateway import RiskGatewayDomainError


def test_error_preserves_reason_field_and_value_error_formatting() -> None:
    without_field = RiskGatewayDomainError("must_be_int")
    assert without_field.reason == "must_be_int"
    assert without_field.field is None
    assert str(without_field) == "must_be_int"
    assert isinstance(without_field, ValueError)

    with_field = RiskGatewayDomainError("must_be_int", field="risk_decision_ts_ms")
    assert with_field.reason == "must_be_int"
    assert with_field.field == "risk_decision_ts_ms"
    assert str(with_field) == "risk_decision_ts_ms: must_be_int"
