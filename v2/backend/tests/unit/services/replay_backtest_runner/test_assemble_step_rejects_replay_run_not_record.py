import pytest

from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step
from v2.backend.app.services.replay_backtest_runner.errors import ReplayBacktestRunnerServiceError


def test_assemble_step_rejects_replay_run_not_record():
    entry = PaperExecutionLedgerEntry(paper_trade_id="pt_bad_run", risk_decision_id="rd_bad_run", decision_id="dec_bad_run", prediction_id="pred_bad_run", feature_snapshot_id="snap_bad_run", symbol="BTCUSDT", ledger_entry_ts_ms=1, ledger_action="record_allow", ledger_reason_code="mirror_allow_proceed_long", input_risk_action="allow", input_risk_reason_code="allow_proceed_long", live_blocked=True)

    for value in (object(), None):
        with pytest.raises(ReplayBacktestRunnerServiceError) as exc:
            assemble_replay_backtest_step(paper_ledger_entry=entry, replay_run=value, now_ms_clock=lambda: 1)
        assert exc.value.code == "must_be_replay_backtest_run"
        assert exc.value.field == "replay_run"
