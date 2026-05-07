def test_public_surface():
    import v2.backend.app.services.replay_backtest_runner as package

    assert package.__all__ == (
        "assemble_replay_backtest_step",
        "assemble_replay_backtest_summary",
        "ReplayBacktestRunnerServiceError",
    )
    assert callable(package.assemble_replay_backtest_step)
    assert callable(package.assemble_replay_backtest_summary)
    assert issubclass(package.ReplayBacktestRunnerServiceError, ValueError)
