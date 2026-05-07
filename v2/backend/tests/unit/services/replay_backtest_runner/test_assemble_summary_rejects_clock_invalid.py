import pytest

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_summary
from v2.backend.app.services.replay_backtest_runner.errors import ReplayBacktestRunnerServiceError


def test_assemble_summary_rejects_clock_invalid():
    run = ReplayBacktestRun(replay_run_id="run_sum_clock_bad", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)
    late_run = ReplayBacktestRun(replay_run_id="run_sum_clock_late", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=1000, run_ended_ts_ms=1000, live_blocked=True)

    cases = (
        (run, 42, "must_be_callable"),
        (run, lambda: 1.0, "must_be_int"),
        (run, lambda: -1, "must_be_nonnegative"),
        (late_run, lambda: 999, "must_be_at_or_after_run_started_ts_ms"),
    )
    for case_run, clock, code in cases:
        with pytest.raises(ReplayBacktestRunnerServiceError) as exc:
            assemble_replay_backtest_summary(replay_run=case_run, steps=(), now_ms_clock=clock)
        assert exc.value.code == code
        assert exc.value.field == "now_ms_clock"
