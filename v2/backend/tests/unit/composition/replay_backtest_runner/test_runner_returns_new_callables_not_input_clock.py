def test_runner_returns_new_callables_not_input_clock():
    from v2.backend.app.composition.replay_backtest_runner import build_replay_backtest_runner

    clock = lambda x=[0]: x[0]
    runner = build_replay_backtest_runner(now_ms_clock=clock)

    assert runner.assemble_step is not clock
    assert runner.assemble_summary is not clock
    assert runner.assemble_step is not runner.assemble_summary
