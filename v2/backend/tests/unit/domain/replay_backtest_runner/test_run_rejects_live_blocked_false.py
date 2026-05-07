import pytest

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun, ReplayBacktestRunnerDomainError


def test_run_rejects_live_blocked_false():
    with pytest.raises(ReplayBacktestRunnerDomainError) as error:
        ReplayBacktestRun(
        replay_run_id="run-1",
        run_mode="replay",
        symbol="BTCUSDT",
        run_started_ts_ms=100,
        run_ended_ts_ms=200,
        live_blocked=False,
        )
    assert error.value.field == "live_blocked"
    assert error.value.reason == "replay_backtest_run_requires_live_blocked_true"
