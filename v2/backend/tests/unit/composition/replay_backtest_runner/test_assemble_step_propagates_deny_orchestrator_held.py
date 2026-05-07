def test_assemble_step_propagates_deny_orchestrator_held():
    from v2.backend.app.composition.replay_backtest_runner import build_replay_backtest_runner
    from v2.backend.app.domain.paper_execution_ledger import PAPER_LEDGER_ACTION_RECORD_DENY, PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD, PaperExecutionLedgerEntry
    from v2.backend.app.domain.replay_backtest_runner import RUN_MODE_REPLAY, STEP_ACTION_RECORD_DENY, STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD, ReplayBacktestRun

    runner = build_replay_backtest_runner(now_ms_clock=lambda: 2)
    result = runner.assemble_step(
        paper_ledger_entry=PaperExecutionLedgerEntry("paper_3", "risk_3", "decision_3", "prediction_3", "feature_3", "BTCUSD", 1, PAPER_LEDGER_ACTION_RECORD_DENY, PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD, "deny", "deny_orchestrator_held", True),
        replay_run=ReplayBacktestRun("run_1", RUN_MODE_REPLAY, "BTCUSD", 1, 10, True),
    )

    assert result.step_action == STEP_ACTION_RECORD_DENY
    assert result.step_reason_code == STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD
    assert result.input_paper_reason_code == PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD
    assert result.live_blocked is True
