import pytest

from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_summary
from v2.backend.app.services.replay_backtest_runner.errors import ReplayBacktestRunnerServiceError


def test_assemble_summary_rejects_replay_run_not_record():
    for value in (object(), None):
        with pytest.raises(ReplayBacktestRunnerServiceError) as exc:
            assemble_replay_backtest_summary(replay_run=value, steps=(), now_ms_clock=lambda: 1)
        assert exc.value.code == "must_be_replay_backtest_run"
        assert exc.value.field == "replay_run"
