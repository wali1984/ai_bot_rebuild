import pytest


def test_validates_now_ms_clock_callable():
    from v2.backend.app.composition.risk_gateway import (
        RiskGatewayCompositionError,
        build_risk_decision_evaluator,
    )

    for value in (42, None, "not_callable"):
        with pytest.raises(RiskGatewayCompositionError) as exc_info:
            build_risk_decision_evaluator(now_ms_clock=value)
        assert exc_info.value.code == "must_be_callable"
        assert exc_info.value.field == "now_ms_clock"
