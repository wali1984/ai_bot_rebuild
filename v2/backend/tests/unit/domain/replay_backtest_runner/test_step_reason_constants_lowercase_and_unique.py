def test_step_reason_constants_lowercase_and_unique():
    from v2.backend.app.domain.replay_backtest_runner import (
        STEP_REASON_MIRROR_ALLOW_PROCEED_LONG,
        STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT,
        STEP_REASON_MIRROR_DENY_DEFAULT,
        STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
        STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
    )

    values = (
        STEP_REASON_MIRROR_ALLOW_PROCEED_LONG,
        STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT,
        STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
        STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
        STEP_REASON_MIRROR_DENY_DEFAULT,
    )
    assert all(isinstance(value, str) and value and value == value.lower() for value in values)
    assert len(set(values)) == 5
