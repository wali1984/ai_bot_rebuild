def test_assemble_summary_invokes_clock_exactly_once_per_call():
    from v2.backend.app.composition.replay_backtest_runner import build_replay_backtest_runner
    from v2.backend.app.domain.replay_backtest_runner import RUN_MODE_REPLAY, ReplayBacktestRun

    n = [0]

    def clock():
        n[0] += 1
        return 2

    runner = build_replay_backtest_runner(now_ms_clock=clock)
    runner.assemble_summary(
        replay_run=ReplayBacktestRun("run_1", RUN_MODE_REPLAY, "BTCUSD", 1, 10, True),
        steps=(),
    )

    assert n == [1]
