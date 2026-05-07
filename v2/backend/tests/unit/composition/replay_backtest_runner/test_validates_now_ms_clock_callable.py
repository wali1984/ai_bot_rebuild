import pytest


def test_validates_now_ms_clock_callable():
    from v2.backend.app.composition.replay_backtest_runner import (
        ReplayBacktestRunnerCompositionError,
        build_replay_backtest_runner,
    )

    for value in (42, None, "not_callable"):
        with pytest.raises(ReplayBacktestRunnerCompositionError) as exc_info:
            build_replay_backtest_runner(now_ms_clock=value)
        assert exc_info.value.code == "must_be_callable"
        assert exc_info.value.field == "now_ms_clock"
