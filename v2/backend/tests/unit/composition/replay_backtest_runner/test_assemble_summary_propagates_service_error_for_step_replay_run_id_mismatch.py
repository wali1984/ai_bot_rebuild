import pytest


def test_assemble_summary_propagates_service_error_for_step_replay_run_id_mismatch():
    from v2.backend.app.composition.replay_backtest_runner import build_replay_backtest_runner
    from v2.backend.app.domain.paper_execution_ledger import PAPER_LEDGER_ACTION_RECORD_ALLOW, PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG, PaperExecutionLedgerEntry
    from v2.backend.app.domain.replay_backtest_runner import RUN_MODE_REPLAY, ReplayBacktestRun
    from v2.backend.app.services.replay_backtest_runner import ReplayBacktestRunnerServiceError

    runner = build_replay_backtest_runner(now_ms_clock=lambda: 2)
    run_1 = ReplayBacktestRun("run_1", RUN_MODE_REPLAY, "BTCUSD", 1, 10, True)
    step = runner.assemble_step(
        paper_ledger_entry=PaperExecutionLedgerEntry("paper_1", "risk_1", "decision_1", "prediction_1", "feature_1", "BTCUSD", 1, PAPER_LEDGER_ACTION_RECORD_ALLOW, PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG, "allow", "allow_proceed_long", True),
        replay_run=run_1,
    )
    with pytest.raises(ReplayBacktestRunnerServiceError) as exc_info:
        runner.assemble_summary(
            replay_run=ReplayBacktestRun("run_2", RUN_MODE_REPLAY, "BTCUSD", 1, 10, True),
            steps=(step,),
        )
    assert exc_info.value.code == "step_replay_run_id_must_match_replay_run_id"
    assert exc_info.value.field == "steps[0].replay_run_id"
