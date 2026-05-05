import pytest

from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RiskDecisionRecord,
    RiskGatewayDomainError,
)


def test_deny_action_requires_deny_prefixed_reason() -> None:
    with pytest.raises(RiskGatewayDomainError) as exc_info:
        RiskDecisionRecord(
            risk_decision_id="risk-1",
            decision_id="decision-1",
            prediction_id="prediction-1",
            feature_snapshot_id="feature-1",
            symbol="BTCUSDT",
            risk_decision_ts_ms=1,
            risk_action=RISK_DECISION_ACTION_DENY,
            risk_reason_code=RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
            input_decision_action="open_long",
            input_decision_reason_code="proceed_long",
            live_blocked=True,
        )
    assert exc_info.value.field == "risk_reason_code"
    assert exc_info.value.reason == "deny_requires_deny_prefix_reason"
