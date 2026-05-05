import pytest

from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RiskDecisionRecord,
    RiskGatewayDomainError,
)


def test_risk_action_must_be_string_member_of_allowed_set() -> None:
    def build(value: object) -> None:
        RiskDecisionRecord(
            risk_decision_id="risk-1",
            decision_id="decision-1",
            prediction_id="prediction-1",
            feature_snapshot_id="feature-1",
            symbol="BTCUSDT",
            risk_decision_ts_ms=1,
            risk_action=value,
            risk_reason_code=RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
            input_decision_action="open_long",
            input_decision_reason_code="proceed_long",
            live_blocked=True,
        )

    for value in ("ALLOW", "abstain", ""):
        with pytest.raises(RiskGatewayDomainError) as exc_info:
            build(value)
        assert exc_info.value.field == "risk_action"
        assert exc_info.value.reason == "invalid_risk_action"
    with pytest.raises(RiskGatewayDomainError) as exc_info:
        build(42)
    assert exc_info.value.field == "risk_action"
    assert exc_info.value.reason == "must_be_str"
