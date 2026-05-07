def test_assemble_step_not_invoked_at_build_time():
    from v2.backend.app.composition.replay_backtest_runner import (
        build_replay_backtest_runner,
    )

    n = [0]

    def clock():
        n[0] += 1
        return 1

    build_replay_backtest_runner(now_ms_clock=clock)

    assert n == [0]
