import pytest

from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_ALLOW,
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RiskDecisionRecord,
    RiskGatewayDomainError,
)


def test_allow_proceed_long_requires_open_long_and_proceed_long_input() -> None:
    with pytest.raises(RiskGatewayDomainError) as exc_info:
        RiskDecisionRecord(
            risk_decision_id="risk-1",
            decision_id="decision-1",
            prediction_id="prediction-1",
            feature_snapshot_id="feature-1",
            symbol="BTCUSDT",
            risk_decision_ts_ms=1,
            risk_action=RISK_DECISION_ACTION_ALLOW,
            risk_reason_code=RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
            input_decision_action="open_short",
            input_decision_reason_code="proceed_long",
            live_blocked=True,
        )
    assert exc_info.value.field == "input_decision_action"
    assert exc_info.value.reason == "allow_proceed_long_requires_open_long_input"

    with pytest.raises(RiskGatewayDomainError) as exc_info:
        RiskDecisionRecord(
            risk_decision_id="risk-2",
            decision_id="decision-2",
            prediction_id="prediction-2",
            feature_snapshot_id="feature-2",
            symbol="BTCUSDT",
            risk_decision_ts_ms=1,
            risk_action=RISK_DECISION_ACTION_ALLOW,
            risk_reason_code=RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
            input_decision_action="open_long",
            input_decision_reason_code="proceed_short",
            live_blocked=True,
        )
    assert exc_info.value.field == "input_decision_reason_code"
    assert exc_info.value.reason == "allow_proceed_long_requires_proceed_long_input_reason"
