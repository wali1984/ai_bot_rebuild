from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_summary


def test_assemble_summary_replay_summary_id_derived_from_replay_run_id():
    run = ReplayBacktestRun(replay_run_id="run_xyz", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)

    assert assemble_replay_backtest_summary(replay_run=run, steps=(), now_ms_clock=lambda: 1).replay_summary_id == "rsum_run_xyz"
