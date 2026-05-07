import pytest

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_summary


def test_assemble_summary_keyword_only_params():
    run = ReplayBacktestRun(replay_run_id="run_sum_kw", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)

    with pytest.raises(TypeError):
        assemble_replay_backtest_summary(run, (), lambda: 1)

    assert assemble_replay_backtest_summary(replay_run=run, steps=(), now_ms_clock=lambda: 1).summary_emitted_ts_ms == 1
