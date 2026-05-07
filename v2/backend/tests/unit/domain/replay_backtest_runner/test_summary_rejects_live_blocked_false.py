import pytest

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestSummary, ReplayBacktestRunnerDomainError


def test_summary_rejects_live_blocked_false():
    with pytest.raises(ReplayBacktestRunnerDomainError) as error:
        ReplayBacktestSummary(
        replay_summary_id="summary-1",
        replay_run_id="run-1",
        summary_emitted_ts_ms=123,
        total_steps_count=0,
        record_allow_steps_count=0,
        record_deny_steps_count=0,
        mirror_allow_proceed_long_steps_count=0,
        mirror_allow_proceed_short_steps_count=0,
        mirror_deny_orchestrator_held_steps_count=0,
        mirror_deny_orchestrator_abstained_steps_count=0,
        mirror_deny_default_steps_count=0,
        live_blocked=False,
        )
    assert error.value.field == "live_blocked"
    assert error.value.reason == "replay_backtest_summary_requires_live_blocked_true"
