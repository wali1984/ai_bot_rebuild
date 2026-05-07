import pytest

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step
from v2.backend.app.services.replay_backtest_runner.errors import ReplayBacktestRunnerServiceError


def test_assemble_step_rejects_paper_ledger_entry_not_record():
    run = ReplayBacktestRun(replay_run_id="run_bad_entry", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)

    for value in (object(), None):
        with pytest.raises(ReplayBacktestRunnerServiceError) as exc:
            assemble_replay_backtest_step(paper_ledger_entry=value, replay_run=run, now_ms_clock=lambda: 1)
        assert exc.value.code == "must_be_paper_execution_ledger_entry"
        assert exc.value.field == "paper_ledger_entry"
