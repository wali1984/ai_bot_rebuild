import pytest

from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_ALLOW,
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RiskDecisionRecord,
    RiskGatewayDomainError,
)


def test_live_blocked_must_be_bool_true() -> None:
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
            input_decision_reason_code="proceed_long",
            live_blocked=value,
        )

    with pytest.raises(RiskGatewayDomainError) as exc_info:
        build(False)
    assert exc_info.value.field == "live_blocked"
    assert exc_info.value.reason == "must_be_true"
    with pytest.raises(RiskGatewayDomainError) as exc_info:
        build(1)
    assert exc_info.value.field == "live_blocked"
    assert exc_info.value.reason == "must_be_bool"
