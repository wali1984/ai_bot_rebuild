import dataclasses

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestSummary


def test_summary_constructs_with_valid_inputs_zero_steps():
    summary = ReplayBacktestSummary(
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
        live_blocked=True,
    )
    assert summary.total_steps_count == 0
    assert isinstance(summary.__class__.__dict__.get("__slots__"), tuple)
    try:
        summary.replay_summary_id = "x"
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("expected frozen summary")
    try:
        setattr(summary, "unknown", "x")
    except (AttributeError, TypeError):
        pass
    else:
        raise AssertionError("expected slotted summary")
