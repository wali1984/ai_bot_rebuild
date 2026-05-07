def test_public_surface():
    import v2.backend.app.domain.replay_backtest_runner as domain

    assert domain.__all__ == (
        "ReplayBacktestRunnerDomainError",
        "ReplayBacktestRun",
        "ReplayBacktestStep",
        "ReplayBacktestSummary",
        "RUN_MODE_REPLAY",
        "RUN_MODE_BACKTEST",
        "STEP_ACTION_RECORD_ALLOW",
        "STEP_ACTION_RECORD_DENY",
        "STEP_REASON_MIRROR_ALLOW_PROCEED_LONG",
        "STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT",
        "STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD",
        "STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED",
        "STEP_REASON_MIRROR_DENY_DEFAULT",
    )
