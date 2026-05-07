import pytest

from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step
from v2.backend.app.services.replay_backtest_runner.errors import ReplayBacktestRunnerServiceError


def test_assemble_step_rejects_clock_returning_before_run_started_ts_ms():
    entry = PaperExecutionLedgerEntry(paper_trade_id="pt_before", risk_decision_id="rd_before", decision_id="dec_before", prediction_id="pred_before", feature_snapshot_id="snap_before", symbol="BTCUSDT", ledger_entry_ts_ms=1, ledger_action="record_allow", ledger_reason_code="mirror_allow_proceed_long", input_risk_action="allow", input_risk_reason_code="allow_proceed_long", live_blocked=True)
    run = ReplayBacktestRun(replay_run_id="run_before", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=1000, run_ended_ts_ms=1000, live_blocked=True)

    with pytest.raises(ReplayBacktestRunnerServiceError) as exc:
        assemble_replay_backtest_step(paper_ledger_entry=entry, replay_run=run, now_ms_clock=lambda: 999)

    assert exc.value.code == "must_be_at_or_after_run_started_ts_ms"
    assert exc.value.field == "now_ms_clock"
