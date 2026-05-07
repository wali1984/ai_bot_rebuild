from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step


def test_assemble_step_propagates_input_lineage_fields():
    entry = PaperExecutionLedgerEntry(paper_trade_id="pt_rd_dec_lineage_xyz", risk_decision_id="rd_dec_lineage_xyz", decision_id="dec_lineage_xyz", prediction_id="pred_lineage_xyz", feature_snapshot_id="snap_lineage_xyz", symbol="ETHUSDT", ledger_entry_ts_ms=1, ledger_action="record_allow", ledger_reason_code="mirror_allow_proceed_long", input_risk_action="allow", input_risk_reason_code="allow_proceed_long", live_blocked=True)
    run = ReplayBacktestRun(replay_run_id="run_lineage", run_mode="backtest", symbol="ETHUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)
    step = assemble_replay_backtest_step(paper_ledger_entry=entry, replay_run=run, now_ms_clock=lambda: 1)

    assert step.paper_trade_id == "pt_rd_dec_lineage_xyz"
    assert step.risk_decision_id == "rd_dec_lineage_xyz"
    assert step.decision_id == "dec_lineage_xyz"
    assert step.prediction_id == "pred_lineage_xyz"
    assert step.feature_snapshot_id == "snap_lineage_xyz"
    assert step.symbol == "ETHUSDT"
    assert step.replay_step_id == "rstep_pt_rd_dec_lineage_xyz"
    assert step.replay_run_id == run.replay_run_id
    assert step.input_paper_action == "record_allow"
    assert step.input_paper_reason_code == "mirror_allow_proceed_long"
    assert step.live_blocked is True
