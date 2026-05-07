import pytest

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_summary
from v2.backend.app.services.replay_backtest_runner.errors import ReplayBacktestRunnerServiceError


def test_assemble_summary_rejects_replay_run_id_too_long_for_replay_summary_id_derivation():
    ok_run = ReplayBacktestRun(replay_run_id="a" * 123, run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)
    bad_run = ReplayBacktestRun(replay_run_id="a" * 124, run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)

    assert assemble_replay_backtest_summary(replay_run=ok_run, steps=(), now_ms_clock=lambda: 1).replay_summary_id == "rsum_" + ("a" * 123)
    with pytest.raises(ReplayBacktestRunnerServiceError) as exc:
        assemble_replay_backtest_summary(replay_run=bad_run, steps=(), now_ms_clock=lambda: 1)
    assert exc.value.code == "replay_run_id_too_long_for_replay_summary_id_derivation"
    assert exc.value.field == "replay_run.replay_run_id"
