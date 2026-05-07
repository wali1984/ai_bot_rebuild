import pytest

from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step
from v2.backend.app.services.replay_backtest_runner.errors import ReplayBacktestRunnerServiceError


def test_assemble_step_exhaustive_over_paper_ledger_reasons():
    rows = (
        ("mirror_allow_proceed_long", "step_record_allow", "step_mirror_allow_proceed_long", "allow", "allow_proceed_long"),
        ("mirror_allow_proceed_short", "step_record_allow", "step_mirror_allow_proceed_short", "allow", "allow_proceed_short"),
        ("mirror_deny_orchestrator_held", "step_record_deny", "step_mirror_deny_orchestrator_held", "deny", "deny_orchestrator_held"),
        ("mirror_deny_orchestrator_abstained", "step_record_deny", "step_mirror_deny_orchestrator_abstained", "deny", "deny_orchestrator_abstained"),
        ("mirror_deny_default", "step_record_deny", "step_mirror_deny_default", "deny", "deny_default"),
    )
    run = ReplayBacktestRun(replay_run_id="run_exhaustive", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)

    assert len(rows) == 5
    for index, (reason, action, step_reason, risk_action, risk_reason) in enumerate(rows):
        entry = PaperExecutionLedgerEntry(paper_trade_id=f"pt_ex_{index}", risk_decision_id=f"rd_ex_{index}", decision_id=f"dec_ex_{index}", prediction_id=f"pred_ex_{index}", feature_snapshot_id=f"snap_ex_{index}", symbol="BTCUSDT", ledger_entry_ts_ms=1, ledger_action="record_allow" if risk_action == "allow" else "record_deny", ledger_reason_code=reason, input_risk_action=risk_action, input_risk_reason_code=risk_reason, live_blocked=True)
        step = assemble_replay_backtest_step(paper_ledger_entry=entry, replay_run=run, now_ms_clock=lambda: 1)
        assert step.step_action == action
        assert step.step_reason_code == step_reason

    mutated = PaperExecutionLedgerEntry(paper_trade_id="pt_ex_bad", risk_decision_id="rd_ex_bad", decision_id="dec_ex_bad", prediction_id="pred_ex_bad", feature_snapshot_id="snap_ex_bad", symbol="BTCUSDT", ledger_entry_ts_ms=1, ledger_action="record_allow", ledger_reason_code="mirror_allow_proceed_long", input_risk_action="allow", input_risk_reason_code="allow_proceed_long", live_blocked=True)
    object.__setattr__(mutated, "ledger_reason_code", "mirror_unrecognized_synthetic")
    with pytest.raises(ReplayBacktestRunnerServiceError) as exc:
        assemble_replay_backtest_step(paper_ledger_entry=mutated, replay_run=run, now_ms_clock=lambda: 1)
    assert exc.value.code == "unrecognized_paper_ledger_reason_code"
    assert exc.value.field == "paper_ledger_entry.ledger_reason_code"
