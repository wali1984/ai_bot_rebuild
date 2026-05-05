import pytest

from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_ALLOW,
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RiskDecisionRecord,
    RiskGatewayDomainError,
)


def test_input_decision_reason_code_must_be_string_member_of_allowed_set() -> None:
    def build(value: object) -> None:
        RiskDecisionRecord(
            risk_decision_id="risk-1",
            decision_id="decision-1",
            prediction_id="prediction-1",
            feature_snapshot_id="feature-1",
            symbol="BTCUSDT",
            risk_decision_ts_ms=1,
            risk_action=RISK_DECISION_ACTION_ALLOW,
            risk_reason_code=RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
            input_decision_action="open_long",
            input_decision_reason_code=value,
            live_blocked=True,
        )

    with pytest.raises(RiskGatewayDomainError) as exc_info:
        build("proceed_neutral")
    assert exc_info.value.field == "input_decision_reason_code"
    assert exc_info.value.reason == "invalid_input_decision_reason_code"
    with pytest.raises(RiskGatewayDomainError) as exc_info:
        build(42)
    assert exc_info.value.field == "input_decision_reason_code"
    assert exc_info.value.reason == "must_be_str"
