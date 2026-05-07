import pytest

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun, ReplayBacktestRunnerDomainError


def test_run_rejects_too_long_replay_run_id():
    with pytest.raises(ReplayBacktestRunnerDomainError) as error:
        ReplayBacktestRun(
        replay_run_id="r" * 129,
        run_mode="replay",
        symbol="BTCUSDT",
        run_started_ts_ms=100,
        run_ended_ts_ms=200,
        live_blocked=True,
        )
    assert error.value.field == "replay_run_id"
