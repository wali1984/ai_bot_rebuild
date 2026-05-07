from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step


def test_assemble_step_record_allow_for_mirror_allow_proceed_long():
    entry = PaperExecutionLedgerEntry(paper_trade_id="pt_long", risk_decision_id="rd_long", decision_id="dec_long", prediction_id="pred_long", feature_snapshot_id="snap_long", symbol="BTCUSDT", ledger_entry_ts_ms=1, ledger_action="record_allow", ledger_reason_code="mirror_allow_proceed_long", input_risk_action="allow", input_risk_reason_code="allow_proceed_long", live_blocked=True)
    run = ReplayBacktestRun(replay_run_id="run_long", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)
    step = assemble_replay_backtest_step(paper_ledger_entry=entry, replay_run=run, now_ms_clock=lambda: 1000)

    assert step.step_action == "step_record_allow"
    assert step.step_reason_code == "step_mirror_allow_proceed_long"
    assert step.step_ts_ms == 1000
    assert step.replay_step_id == "rstep_pt_long"
    assert step.live_blocked is True
    assert step.input_paper_action == "record_allow"
    assert step.input_paper_reason_code == "mirror_allow_proceed_long"
