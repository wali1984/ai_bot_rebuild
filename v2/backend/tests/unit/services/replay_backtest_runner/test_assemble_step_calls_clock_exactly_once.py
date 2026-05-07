from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step


def test_assemble_step_calls_clock_exactly_once():
    calls = []
    entry = PaperExecutionLedgerEntry(paper_trade_id="pt_once", risk_decision_id="rd_once", decision_id="dec_once", prediction_id="pred_once", feature_snapshot_id="snap_once", symbol="BTCUSDT", ledger_entry_ts_ms=1, ledger_action="record_allow", ledger_reason_code="mirror_allow_proceed_long", input_risk_action="allow", input_risk_reason_code="allow_proceed_long", live_blocked=True)
    run = ReplayBacktestRun(replay_run_id="run_once", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)

    def clock():
        calls.append(1)
        return 1000 if len(calls) == 1 else 999999999

    step = assemble_replay_backtest_step(paper_ledger_entry=entry, replay_run=run, now_ms_clock=clock)

    assert len(calls) == 1
    assert step.step_ts_ms == 1000
