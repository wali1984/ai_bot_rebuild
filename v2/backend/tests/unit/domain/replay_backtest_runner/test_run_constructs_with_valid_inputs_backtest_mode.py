from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun


def test_run_constructs_with_valid_inputs_backtest_mode():
    run = ReplayBacktestRun(
        replay_run_id="run-1",
        run_mode="backtest",
        symbol="BTCUSDT",
        run_started_ts_ms=100,
        run_ended_ts_ms=200,
        live_blocked=True,
    )
    assert run.run_mode == "backtest"
    assert run.symbol == "BTCUSDT"
