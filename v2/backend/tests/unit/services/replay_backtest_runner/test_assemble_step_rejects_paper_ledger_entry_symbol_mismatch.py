import pytest

from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step
from v2.backend.app.services.replay_backtest_runner.errors import ReplayBacktestRunnerServiceError


def test_assemble_step_rejects_paper_ledger_entry_symbol_mismatch():
    entry = PaperExecutionLedgerEntry(paper_trade_id="pt_symbol", risk_decision_id="rd_symbol", decision_id="dec_symbol", prediction_id="pred_symbol", feature_snapshot_id="snap_symbol", symbol="BTCUSDT", ledger_entry_ts_ms=1, ledger_action="record_allow", ledger_reason_code="mirror_allow_proceed_long", input_risk_action="allow", input_risk_reason_code="allow_proceed_long", live_blocked=True)
    run = ReplayBacktestRun(replay_run_id="run_symbol", run_mode="backtest", symbol="ETHUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)

    with pytest.raises(ReplayBacktestRunnerServiceError) as exc:
        assemble_replay_backtest_step(paper_ledger_entry=entry, replay_run=run, now_ms_clock=lambda: 1)

    assert exc.value.code == "paper_ledger_entry_symbol_must_match_replay_run_symbol"
    assert exc.value.field == "paper_ledger_entry.symbol"
