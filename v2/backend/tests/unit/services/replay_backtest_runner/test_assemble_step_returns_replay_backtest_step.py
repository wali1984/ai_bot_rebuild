from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun, ReplayBacktestStep
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step


def test_assemble_step_returns_replay_backtest_step():
    entry = PaperExecutionLedgerEntry(paper_trade_id="pt_type", risk_decision_id="rd_type", decision_id="dec_type", prediction_id="pred_type", feature_snapshot_id="snap_type", symbol="BTCUSDT", ledger_entry_ts_ms=1, ledger_action="record_allow", ledger_reason_code="mirror_allow_proceed_long", input_risk_action="allow", input_risk_reason_code="allow_proceed_long", live_blocked=True)
    run = ReplayBacktestRun(replay_run_id="run_type", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)

    assert isinstance(assemble_replay_backtest_step(paper_ledger_entry=entry, replay_run=run, now_ms_clock=lambda: 1), ReplayBacktestStep)
