def test_assemble_step_propagates_deny_orchestrator_abstained():
    from v2.backend.app.composition.replay_backtest_runner import build_replay_backtest_runner
    from v2.backend.app.domain.paper_execution_ledger import PAPER_LEDGER_ACTION_RECORD_DENY, PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED, PaperExecutionLedgerEntry
    from v2.backend.app.domain.replay_backtest_runner import RUN_MODE_REPLAY, STEP_ACTION_RECORD_DENY, STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED, ReplayBacktestRun

    runner = build_replay_backtest_runner(now_ms_clock=lambda: 2)
    result = runner.assemble_step(
        paper_ledger_entry=PaperExecutionLedgerEntry("paper_4", "risk_4", "decision_4", "prediction_4", "feature_4", "BTCUSD", 1, PAPER_LEDGER_ACTION_RECORD_DENY, PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED, "deny", "deny_orchestrator_abstained", True),
        replay_run=ReplayBacktestRun("run_1", RUN_MODE_REPLAY, "BTCUSD", 1, 10, True),
    )

    assert result.step_action == STEP_ACTION_RECORD_DENY
    assert result.step_reason_code == STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED
    assert result.input_paper_reason_code == PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED
    assert result.live_blocked is True
