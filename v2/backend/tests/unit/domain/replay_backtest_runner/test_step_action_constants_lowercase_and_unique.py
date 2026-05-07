def test_step_action_constants_lowercase_and_unique():
    from v2.backend.app.domain.replay_backtest_runner import STEP_ACTION_RECORD_ALLOW, STEP_ACTION_RECORD_DENY

    values = (STEP_ACTION_RECORD_ALLOW, STEP_ACTION_RECORD_DENY)
    assert all(isinstance(value, str) and value and value == value.lower() for value in values)
    assert len(set(values)) == 2
