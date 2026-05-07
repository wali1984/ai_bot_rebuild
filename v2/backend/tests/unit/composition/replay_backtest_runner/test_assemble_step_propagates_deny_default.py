def test_assemble_step_propagates_deny_default():
    from v2.backend.app.composition.replay_backtest_runner import build_replay_backtest_runner
    from v2.backend.app.domain.paper_execution_ledger import PAPER_LEDGER_ACTION_RECORD_DENY, PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT, PaperExecutionLedgerEntry
    from v2.backend.app.domain.replay_backtest_runner import RUN_MODE_REPLAY, STEP_ACTION_RECORD_DENY, STEP_REASON_MIRROR_DENY_DEFAULT, ReplayBacktestRun

    input_reason = "deny" + "_default"
    runner = build_replay_backtest_runner(now_ms_clock=lambda: 2)
    result = runner.assemble_step(
        paper_ledger_entry=PaperExecutionLedgerEntry("paper_5", "risk_5", "decision_5", "prediction_5", "feature_5", "BTCUSD", 1, PAPER_LEDGER_ACTION_RECORD_DENY, PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT, "deny", input_reason, True),
        replay_run=ReplayBacktestRun("run_1", RUN_MODE_REPLAY, "BTCUSD", 1, 10, True),
    )

    assert result.step_action == STEP_ACTION_RECORD_DENY
    assert result.step_reason_code == STEP_REASON_MIRROR_DENY_DEFAULT
    assert result.input_paper_reason_code == PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT
    assert result.live_blocked is True
