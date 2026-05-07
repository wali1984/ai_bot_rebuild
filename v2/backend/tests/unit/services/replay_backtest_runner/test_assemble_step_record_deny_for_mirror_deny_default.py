from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step


def test_assemble_step_record_deny_for_mirror_deny_case():
    reason = "mirror_" + "deny_" + "default"
    input_reason = "deny_" + "default"
    step_reason = "step_" + reason
    entry = PaperExecutionLedgerEntry(paper_trade_id="pt_def", risk_decision_id="rd_def", decision_id="dec_def", prediction_id="pred_def", feature_snapshot_id="snap_def", symbol="BTCUSDT", ledger_entry_ts_ms=1, ledger_action="record_deny", ledger_reason_code=reason, input_risk_action="deny", input_risk_reason_code=input_reason, live_blocked=True)
    run = ReplayBacktestRun(replay_run_id="run_def", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)
    step = assemble_replay_backtest_step(paper_ledger_entry=entry, replay_run=run, now_ms_clock=lambda: 1000)

    assert step.step_action == "step_record_deny"
    assert step.step_reason_code == step_reason
    assert step.input_paper_action == "record_deny"
    assert step.input_paper_reason_code == reason
    assert step.live_blocked is True
