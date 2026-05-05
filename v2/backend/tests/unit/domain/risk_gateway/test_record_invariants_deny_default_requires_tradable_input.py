import pytest

from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_DENY_DEFAULT,
    RiskDecisionRecord,
    RiskGatewayDomainError,
)


def test_deny_default_requires_tradable_input() -> None:
    def build(action: str, reason: str) -> RiskDecisionRecord:
        return RiskDecisionRecord(
            risk_decision_id="risk-" + action,
            decision_id="decision-" + action,
            prediction_id="prediction-" + action,
            feature_snapshot_id="feature-" + action,
            symbol="BTCUSDT",
            risk_decision_ts_ms=1,
            risk_action=RISK_DECISION_ACTION_DENY,
            risk_reason_code=RISK_DECISION_REASON_DENY_DEFAULT,
            input_decision_action=action,
            input_decision_reason_code=reason,
            live_blocked=True,
        )

    for action, reason in (
        ("hold", "hold_flat_direction"),
        ("abstain", "abstain_low_confidence"),
    ):
        with pytest.raises(RiskGatewayDomainError) as exc_info:
            build(action, reason)
        assert exc_info.value.field == "input_decision_action"
        assert exc_info.value.reason == "deny_default_requires_tradable_input"
    assert build("open_long", "proceed_long").input_decision_action == "open_long"
    assert build("open_short", "proceed_short").input_decision_action == "open_short"
