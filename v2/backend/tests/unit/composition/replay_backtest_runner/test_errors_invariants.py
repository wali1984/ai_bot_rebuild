import pytest


def test_errors_invariants():
    from v2.backend.app.composition.replay_backtest_runner import (
        ReplayBacktestRunnerCompositionError,
    )

    error = ReplayBacktestRunnerCompositionError("some_code", field="some_field")

    assert error.code == "some_code"
    assert error.field == "some_field"
    assert str(error) == "some_code (some_field)"
    assert repr(error) == (
        "ReplayBacktestRunnerCompositionError("
        "code='some_code', field='some_field')"
    )
    with pytest.raises(TypeError):
        ReplayBacktestRunnerCompositionError("some_code")
