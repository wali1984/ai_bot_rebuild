import pytest

from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step
from v2.backend.app.services.replay_backtest_runner.errors import ReplayBacktestRunnerServiceError


def test_assemble_step_rejects_clock_returning_non_int():
    entry = PaperExecutionLedgerEntry(paper_trade_id="pt_nonint", risk_decision_id="rd_nonint", decision_id="dec_nonint", prediction_id="pred_nonint", feature_snapshot_id="snap_nonint", symbol="BTCUSDT", ledger_entry_ts_ms=1, ledger_action="record_allow", ledger_reason_code="mirror_allow_proceed_long", input_risk_action="allow", input_risk_reason_code="allow_proceed_long", live_blocked=True)
    run = ReplayBacktestRun(replay_run_id="run_nonint", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)

    for clock in (lambda: 1.0, lambda: True, lambda: "100"):
        with pytest.raises(ReplayBacktestRunnerServiceError) as exc:
            assemble_replay_backtest_step(paper_ledger_entry=entry, replay_run=run, now_ms_clock=clock)
        assert exc.value.code == "must_be_int"
        assert exc.value.field == "now_ms_clock"
