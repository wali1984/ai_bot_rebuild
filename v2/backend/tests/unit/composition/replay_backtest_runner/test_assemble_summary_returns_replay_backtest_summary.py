def test_assemble_summary_returns_replay_backtest_summary():
    from v2.backend.app.composition.replay_backtest_runner import build_replay_backtest_runner
    from v2.backend.app.domain.replay_backtest_runner import RUN_MODE_REPLAY, ReplayBacktestRun, ReplayBacktestSummary

    runner = build_replay_backtest_runner(now_ms_clock=lambda: 2)
    result = runner.assemble_summary(
        replay_run=ReplayBacktestRun("run_1", RUN_MODE_REPLAY, "BTCUSD", 1, 10, True),
        steps=(),
    )

    assert isinstance(result, ReplayBacktestSummary)
