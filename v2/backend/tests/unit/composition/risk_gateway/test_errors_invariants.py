import pytest


def test_errors_invariants():
    from v2.backend.app.composition.risk_gateway import RiskGatewayCompositionError

    error = RiskGatewayCompositionError("some_code", field="some_field")

    assert error.code == "some_code"
    assert error.field == "some_field"
    assert str(error) == "some_code (some_field)"
    with pytest.raises(TypeError):
        RiskGatewayCompositionError("some_code")
