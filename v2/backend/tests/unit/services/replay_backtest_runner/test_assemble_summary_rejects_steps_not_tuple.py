import pytest

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_summary
from v2.backend.app.services.replay_backtest_runner.errors import ReplayBacktestRunnerServiceError


def test_assemble_summary_rejects_steps_not_tuple():
    run = ReplayBacktestRun(replay_run_id="run_sum_steps_type", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)

    for value in ([], None):
        with pytest.raises(ReplayBacktestRunnerServiceError) as exc:
            assemble_replay_backtest_summary(replay_run=run, steps=value, now_ms_clock=lambda: 1)
        assert exc.value.code == "must_be_tuple"
        assert exc.value.field == "steps"
