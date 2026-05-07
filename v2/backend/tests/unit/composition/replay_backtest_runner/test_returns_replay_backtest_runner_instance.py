def test_returns_replay_backtest_runner_instance():
    from v2.backend.app.composition.replay_backtest_runner import (
        ReplayBacktestRunner,
        build_replay_backtest_runner,
    )

    clock = lambda: 123
    runner = build_replay_backtest_runner(now_ms_clock=clock)

    assert isinstance(runner, ReplayBacktestRunner)
    assert callable(runner.assemble_step)
    assert callable(runner.assemble_summary)
    assert runner.assemble_step is not clock
    assert runner.assemble_summary is not clock
