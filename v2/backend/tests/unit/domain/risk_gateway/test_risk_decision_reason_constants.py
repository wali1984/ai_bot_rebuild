from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
    RISK_DECISION_REASON_DENY_DEFAULT,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
)


def test_risk_decision_reason_constants_are_exact_distinct_and_prefixed() -> None:
    allow_reasons = (
        RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
        RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
    )
    deny_reasons = (
        RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
        RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
        RISK_DECISION_REASON_DENY_DEFAULT,
    )
    assert allow_reasons == ("allow_proceed_long", "allow_proceed_short")
    assert deny_reasons == (
        "deny_orchestrator_abstained",
        "deny_orchestrator_held",
        "deny_default",
    )
    assert len(set(allow_reasons + deny_reasons)) == 5
    assert all(reason.startswith("allow_") for reason in allow_reasons)
    assert all(reason.startswith("deny_") for reason in deny_reasons)
