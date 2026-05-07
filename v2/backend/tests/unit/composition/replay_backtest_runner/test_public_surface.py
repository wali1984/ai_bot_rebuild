def test_public_surface():
    from v2.backend.app.composition import replay_backtest_runner

    assert replay_backtest_runner.__all__ == (
        "build_replay_backtest_runner",
        "ReplayBacktestRunner",
        "ReplayBacktestRunnerCompositionError",
    )
    assert callable(replay_backtest_runner.build_replay_backtest_runner)
    assert isinstance(replay_backtest_runner.ReplayBacktestRunnerCompositionError, type)
    assert issubclass(replay_backtest_runner.ReplayBacktestRunnerCompositionError, Exception)
    assert not issubclass(replay_backtest_runner.ReplayBacktestRunnerCompositionError, ValueError)
    assert replay_backtest_runner.ReplayBacktestRunner is not None
