from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_ABSTAIN,
    DECISION_ACTION_HOLD,
    DECISION_ACTION_OPEN_LONG,
    DECISION_ACTION_OPEN_SHORT,
)


def test_decision_action_constants_are_exact_and_distinct():
    values = (
        DECISION_ACTION_OPEN_LONG,
        DECISION_ACTION_OPEN_SHORT,
        DECISION_ACTION_HOLD,
        DECISION_ACTION_ABSTAIN,
    )
    assert values == ("open_long", "open_short", "hold", "abstain")
    assert len(set(values)) == 4
