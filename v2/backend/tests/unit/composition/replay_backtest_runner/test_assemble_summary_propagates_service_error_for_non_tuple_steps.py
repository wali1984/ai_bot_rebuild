import pytest


def test_assemble_summary_propagates_service_error_for_non_tuple_steps():
    from v2.backend.app.composition.replay_backtest_runner import build_replay_backtest_runner
    from v2.backend.app.domain.replay_backtest_runner import RUN_MODE_REPLAY, ReplayBacktestRun
    from v2.backend.app.services.replay_backtest_runner import ReplayBacktestRunnerServiceError

    runner = build_replay_backtest_runner(now_ms_clock=lambda: 2)
    with pytest.raises(ReplayBacktestRunnerServiceError) as exc_info:
        runner.assemble_summary(
            replay_run=ReplayBacktestRun("run_1", RUN_MODE_REPLAY, "BTCUSD", 1, 10, True),
            steps=[],
        )
    assert exc_info.value.code == "must_be_tuple"
    assert exc_info.value.field == "steps"
