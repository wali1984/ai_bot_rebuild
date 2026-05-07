from v2.backend.app.services.replay_backtest_runner.errors import (
    ReplayBacktestRunnerServiceError,
)


def test_errors_invariants():
    error = ReplayBacktestRunnerServiceError("must_be_int", field="now_ms_clock")

    assert error.code == "must_be_int"
    assert error.field == "now_ms_clock"
    assert str(error) == "must_be_int (now_ms_clock)"
    assert repr(error) == (
        "ReplayBacktestRunnerServiceError(code='must_be_int', field='now_ms_clock')"
    )
    assert isinstance(error, ValueError) is True
