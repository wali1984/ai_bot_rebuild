import dataclasses

import pytest

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun, ReplayBacktestSummary
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_summary


def test_assemble_summary_zero_steps_zero_counts():
    run = ReplayBacktestRun(replay_run_id="run_sum_zero", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)
    summary = assemble_replay_backtest_summary(replay_run=run, steps=(), now_ms_clock=lambda: 1)

    assert isinstance(summary, ReplayBacktestSummary)
    assert summary.total_steps_count == 0
    assert summary.record_allow_steps_count == 0
    assert summary.record_deny_steps_count == 0
    assert summary.mirror_allow_proceed_long_steps_count == 0
    assert summary.mirror_allow_proceed_short_steps_count == 0
    assert summary.mirror_deny_orchestrator_held_steps_count == 0
    assert summary.mirror_deny_orchestrator_abstained_steps_count == 0
    assert summary.mirror_deny_default_steps_count == 0
    assert summary.live_blocked is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        summary.replay_summary_id = "x"
