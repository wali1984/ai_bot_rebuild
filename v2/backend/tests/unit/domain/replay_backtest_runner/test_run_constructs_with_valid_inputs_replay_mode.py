import dataclasses

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun


def test_run_constructs_with_valid_inputs_replay_mode():
    run = ReplayBacktestRun(
        replay_run_id="run-1",
        run_mode="replay",
        symbol="BTCUSDT",
        run_started_ts_ms=100,
        run_ended_ts_ms=200,
        live_blocked=True,
    )
    assert run.replay_run_id == "run-1"
    assert run.run_mode == "replay"
    assert run.__class__.__dict__.get("__slots__")
    try:
        run.replay_run_id = "x"
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("expected frozen run")
