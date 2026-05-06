import pytest

from v2.backend.app.services.risk_gateway import (
    RiskGatewayServiceError,
    assemble_risk_decision_record,
)


def test_assemble_rejects_decision_not_record() -> None:
    for decision in (object(), None):
        with pytest.raises(RiskGatewayServiceError) as exc_info:
            assemble_risk_decision_record(
                decision=decision,  # type: ignore[arg-type]
                now_ms_clock=lambda: 1,
            )
        assert exc_info.value.code == "must_be_orchestrator_decision_record"
        assert exc_info.value.field == "decision"
