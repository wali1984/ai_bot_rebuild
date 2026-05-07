from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_summary


def test_assemble_summary_calls_clock_exactly_once():
    calls = []
    run = ReplayBacktestRun(replay_run_id="run_sum_once", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)

    def clock():
        calls.append(1)
        return 1000 if len(calls) == 1 else 999999999

    summary = assemble_replay_backtest_summary(replay_run=run, steps=(), now_ms_clock=clock)

    assert len(calls) == 1
    assert summary.summary_emitted_ts_ms == 1000
