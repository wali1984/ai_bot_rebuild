import pytest

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_summary
from v2.backend.app.services.replay_backtest_runner.errors import ReplayBacktestRunnerServiceError


def test_assemble_summary_rejects_step_element_not_record():
    run = ReplayBacktestRun(replay_run_id="run_sum_elem", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)

    with pytest.raises(ReplayBacktestRunnerServiceError) as exc:
        assemble_replay_backtest_summary(replay_run=run, steps=(object(),), now_ms_clock=lambda: 1)

    assert exc.value.code == "must_be_replay_backtest_step"
    assert exc.value.field == "steps[0]"
