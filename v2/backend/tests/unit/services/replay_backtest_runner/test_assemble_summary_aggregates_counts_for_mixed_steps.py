from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun, ReplayBacktestStep
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_summary


def test_assemble_summary_aggregates_counts_for_mixed_steps():
    run = ReplayBacktestRun(replay_run_id="run_sum_mixed", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)
    reasons = (
        ("step_record_allow", "step_mirror_allow_proceed_long", "record_allow", "mirror_allow_proceed_long"),
        ("step_record_allow", "step_mirror_allow_proceed_short", "record_allow", "mirror_allow_proceed_short"),
        ("step_record_deny", "step_mirror_deny_orchestrator_held", "record_deny", "mirror_deny_orchestrator_held"),
        ("step_record_deny", "step_mirror_deny_orchestrator_abstained", "record_deny", "mirror_deny_orchestrator_abstained"),
        ("step_record_deny", "step_mirror_deny_default", "record_deny", "mirror_deny_default"),
    )
    steps = tuple(ReplayBacktestStep(replay_step_id=f"rstep_mix_{index}", replay_run_id=run.replay_run_id, paper_trade_id=f"pt_mix_{index}", risk_decision_id=f"rd_mix_{index}", decision_id=f"dec_mix_{index}", prediction_id=f"pred_mix_{index}", feature_snapshot_id=f"snap_mix_{index}", symbol="BTCUSDT", step_ts_ms=1, step_action=action, step_reason_code=reason, input_paper_action=input_action, input_paper_reason_code=input_reason, live_blocked=True) for index, (action, reason, input_action, input_reason) in enumerate(reasons))
    summary = assemble_replay_backtest_summary(replay_run=run, steps=steps, now_ms_clock=lambda: 1)

    assert summary.total_steps_count == 5
    assert summary.record_allow_steps_count == 2
    assert summary.record_deny_steps_count == 3
    assert summary.mirror_allow_proceed_long_steps_count == 1
    assert summary.mirror_allow_proceed_short_steps_count == 1
    assert summary.mirror_deny_orchestrator_held_steps_count == 1
    assert summary.mirror_deny_orchestrator_abstained_steps_count == 1
    assert summary.mirror_deny_default_steps_count == 1
    assert summary.live_blocked is True

    more = steps[:1] + steps[:1] + steps[2:]
    second = assemble_replay_backtest_summary(replay_run=run, steps=more, now_ms_clock=lambda: 2)
    assert second.total_steps_count == 5
    assert second.record_allow_steps_count == 2
    assert second.record_deny_steps_count == 3
    assert second.mirror_allow_proceed_long_steps_count == 2
    assert second.mirror_allow_proceed_short_steps_count == 0
    assert second.mirror_deny_orchestrator_held_steps_count == 1
    assert second.mirror_deny_orchestrator_abstained_steps_count == 1
    assert second.mirror_deny_default_steps_count == 1
