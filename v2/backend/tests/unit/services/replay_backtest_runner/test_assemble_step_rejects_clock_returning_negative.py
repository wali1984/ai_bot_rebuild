import pytest

from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step
from v2.backend.app.services.replay_backtest_runner.errors import ReplayBacktestRunnerServiceError


def test_assemble_step_rejects_clock_returning_negative():
    entry = PaperExecutionLedgerEntry(paper_trade_id="pt_neg", risk_decision_id="rd_neg", decision_id="dec_neg", prediction_id="pred_neg", feature_snapshot_id="snap_neg", symbol="BTCUSDT", ledger_entry_ts_ms=1, ledger_action="record_allow", ledger_reason_code="mirror_allow_proceed_long", input_risk_action="allow", input_risk_reason_code="allow_proceed_long", live_blocked=True)
    run = ReplayBacktestRun(replay_run_id="run_neg", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)

    with pytest.raises(ReplayBacktestRunnerServiceError) as exc:
        assemble_replay_backtest_step(paper_ledger_entry=entry, replay_run=run, now_ms_clock=lambda: -1)

    assert exc.value.code == "must_be_nonnegative"
    assert exc.value.field == "now_ms_clock"
