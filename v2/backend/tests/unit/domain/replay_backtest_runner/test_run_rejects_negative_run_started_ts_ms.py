import pytest

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun, ReplayBacktestRunnerDomainError


def test_run_rejects_negative_run_started_ts_ms():
    with pytest.raises(ReplayBacktestRunnerDomainError) as error:
        ReplayBacktestRun(
        replay_run_id="run-1",
        run_mode="replay",
        symbol="BTCUSDT",
        run_started_ts_ms=-1,
        run_ended_ts_ms=200,
        live_blocked=True,
        )
    assert error.value.field == "run_started_ts_ms"
