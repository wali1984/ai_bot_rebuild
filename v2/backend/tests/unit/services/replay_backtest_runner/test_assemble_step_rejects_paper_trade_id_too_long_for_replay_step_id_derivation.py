import pytest

from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step
from v2.backend.app.services.replay_backtest_runner.errors import ReplayBacktestRunnerServiceError


def test_assemble_step_rejects_paper_trade_id_too_long_for_replay_step_id_derivation():
    run = ReplayBacktestRun(replay_run_id="run_length", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)
    ok_entry = PaperExecutionLedgerEntry(paper_trade_id="a" * 122, risk_decision_id="rd_length", decision_id="dec_length", prediction_id="pred_length", feature_snapshot_id="snap_length", symbol="BTCUSDT", ledger_entry_ts_ms=1, ledger_action="record_allow", ledger_reason_code="mirror_allow_proceed_long", input_risk_action="allow", input_risk_reason_code="allow_proceed_long", live_blocked=True)
    bad_entry = PaperExecutionLedgerEntry(paper_trade_id="a" * 123, risk_decision_id="rd_length_b", decision_id="dec_length_b", prediction_id="pred_length_b", feature_snapshot_id="snap_length_b", symbol="BTCUSDT", ledger_entry_ts_ms=1, ledger_action="record_allow", ledger_reason_code="mirror_allow_proceed_long", input_risk_action="allow", input_risk_reason_code="allow_proceed_long", live_blocked=True)

    assert assemble_replay_backtest_step(paper_ledger_entry=ok_entry, replay_run=run, now_ms_clock=lambda: 1).replay_step_id == "rstep_" + ("a" * 122)
    with pytest.raises(ReplayBacktestRunnerServiceError) as exc:
        assemble_replay_backtest_step(paper_ledger_entry=bad_entry, replay_run=run, now_ms_clock=lambda: 1)
    assert exc.value.code == "paper_trade_id_too_long_for_replay_step_id_derivation"
    assert exc.value.field == "paper_ledger_entry.paper_trade_id"
