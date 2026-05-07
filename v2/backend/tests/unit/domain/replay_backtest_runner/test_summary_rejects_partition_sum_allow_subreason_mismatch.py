import pytest

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestSummary, ReplayBacktestRunnerDomainError


def test_summary_rejects_partition_sum_allow_subreason_mismatch():
    with pytest.raises(ReplayBacktestRunnerDomainError) as error:
        ReplayBacktestSummary(
        replay_summary_id="summary-1",
        replay_run_id="run-1",
        summary_emitted_ts_ms=123,
        total_steps_count=1,
        record_allow_steps_count=1,
        record_deny_steps_count=0,
        mirror_allow_proceed_long_steps_count=0,
        mirror_allow_proceed_short_steps_count=0,
        mirror_deny_orchestrator_held_steps_count=0,
        mirror_deny_orchestrator_abstained_steps_count=0,
        mirror_deny_default_steps_count=0,
        live_blocked=True,
        )
    assert error.value.field == "record_allow_steps_count"
    assert error.value.reason == "allow_subreason_partition_sum_must_equal_record_allow_steps_count"
