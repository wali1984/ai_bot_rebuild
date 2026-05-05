import pytest

from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
    RiskDecisionRecord,
    RiskGatewayDomainError,
)


def test_deny_orchestrator_held_requires_hold_input() -> None:
    with pytest.raises(RiskGatewayDomainError) as exc_info:
        RiskDecisionRecord(
            risk_decision_id="risk-1",
            decision_id="decision-1",
            prediction_id="prediction-1",
            feature_snapshot_id="feature-1",
            symbol="BTCUSDT",
            risk_decision_ts_ms=1,
            risk_action=RISK_DECISION_ACTION_DENY,
            risk_reason_code=RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
            input_decision_action="abstain",
            input_decision_reason_code="abstain_low_confidence",
            live_blocked=True,
        )
    assert exc_info.value.field == "input_decision_action"
    assert exc_info.value.reason == "deny_orchestrator_held_requires_hold_input"
