def test_step_reason_constants_carry_correct_prefix():
    from v2.backend.app.domain.replay_backtest_runner import (
        STEP_REASON_MIRROR_ALLOW_PROCEED_LONG,
        STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT,
        STEP_REASON_MIRROR_DENY_DEFAULT,
        STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
        STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
    )

    assert STEP_REASON_MIRROR_ALLOW_PROCEED_LONG.startswith("step_mirror_allow_")
    assert STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT.startswith("step_mirror_allow_")
    assert STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD.startswith("step_mirror_deny_")
    assert STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED.startswith("step_mirror_deny_")
    assert STEP_REASON_MIRROR_DENY_DEFAULT.startswith("step_mirror_deny_")
