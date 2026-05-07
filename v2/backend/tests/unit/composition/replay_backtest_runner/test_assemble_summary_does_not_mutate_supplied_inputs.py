def test_assemble_summary_does_not_mutate_supplied_inputs():
    from v2.backend.app.composition.replay_backtest_runner import build_replay_backtest_runner
    from v2.backend.app.domain.paper_execution_ledger import PAPER_LEDGER_ACTION_RECORD_ALLOW, PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG, PaperExecutionLedgerEntry
    from v2.backend.app.domain.replay_backtest_runner import RUN_MODE_REPLAY, ReplayBacktestRun

    runner = build_replay_backtest_runner(now_ms_clock=lambda: 2)
    run = ReplayBacktestRun("run_1", RUN_MODE_REPLAY, "BTCUSD", 1, 10, True)
    step = runner.assemble_step(
        paper_ledger_entry=PaperExecutionLedgerEntry("paper_1", "risk_1", "decision_1", "prediction_1", "feature_1", "BTCUSD", 1, PAPER_LEDGER_ACTION_RECORD_ALLOW, PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG, "allow", "allow_proceed_long", True),
        replay_run=run,
    )
    steps = (step,)
    before = (run.replay_run_id, run.symbol, step.replay_step_id, step.step_action, id(steps))

    runner.assemble_summary(replay_run=run, steps=steps)

    assert (run.replay_run_id, run.symbol, step.replay_step_id, step.step_action, id(steps)) == before
