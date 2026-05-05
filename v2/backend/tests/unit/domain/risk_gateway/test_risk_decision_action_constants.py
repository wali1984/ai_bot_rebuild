from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_ALLOW,
    RISK_DECISION_ACTION_DENY,
)


def test_risk_decision_action_constants_are_exact_and_distinct() -> None:
    assert RISK_DECISION_ACTION_ALLOW == "allow"
    assert RISK_DECISION_ACTION_DENY == "deny"
    assert len({RISK_DECISION_ACTION_ALLOW, RISK_DECISION_ACTION_DENY}) == 2
