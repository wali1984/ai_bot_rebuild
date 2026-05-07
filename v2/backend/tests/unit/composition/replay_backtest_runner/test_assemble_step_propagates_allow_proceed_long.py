def test_assemble_step_propagates_allow_proceed_long():
    from v2.backend.app.composition.replay_backtest_runner import build_replay_backtest_runner
    from v2.backend.app.domain.paper_execution_ledger import PAPER_LEDGER_ACTION_RECORD_ALLOW, PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG, PaperExecutionLedgerEntry
    from v2.backend.app.domain.replay_backtest_runner import RUN_MODE_REPLAY, STEP_ACTION_RECORD_ALLOW, STEP_REASON_MIRROR_ALLOW_PROCEED_LONG, ReplayBacktestRun

    runner = build_replay_backtest_runner(now_ms_clock=lambda: 2)
    result = runner.assemble_step(
        paper_ledger_entry=PaperExecutionLedgerEntry("paper_1", "risk_1", "decision_1", "prediction_1", "feature_1", "BTCUSD", 1, PAPER_LEDGER_ACTION_RECORD_ALLOW, PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG, "allow", "allow_proceed_long", True),
        replay_run=ReplayBacktestRun("run_1", RUN_MODE_REPLAY, "BTCUSD", 1, 10, True),
    )

    assert result.step_action == STEP_ACTION_RECORD_ALLOW
    assert result.step_reason_code == STEP_REASON_MIRROR_ALLOW_PROCEED_LONG
    assert result.input_paper_action == PAPER_LEDGER_ACTION_RECORD_ALLOW
    assert result.input_paper_reason_code == PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG
    assert result.live_blocked is True
