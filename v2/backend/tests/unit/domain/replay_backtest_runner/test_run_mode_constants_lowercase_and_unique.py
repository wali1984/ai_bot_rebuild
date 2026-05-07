def test_run_mode_constants_lowercase_and_unique():
    from v2.backend.app.domain.replay_backtest_runner import RUN_MODE_BACKTEST, RUN_MODE_REPLAY

    values = (RUN_MODE_REPLAY, RUN_MODE_BACKTEST)
    assert all(isinstance(value, str) and value and value == value.lower() for value in values)
    assert len(set(values)) == 2
