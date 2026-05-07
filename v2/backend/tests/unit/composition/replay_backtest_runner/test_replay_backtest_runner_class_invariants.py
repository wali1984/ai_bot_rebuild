import pytest


def test_replay_backtest_runner_class_invariants():
    from v2.backend.app.composition.replay_backtest_runner import ReplayBacktestRunner

    runner = ReplayBacktestRunner(assemble_step=lambda **kwargs: None, assemble_summary=lambda **kwargs: None)

    assert ReplayBacktestRunner.__slots__ == ("assemble_step", "assemble_summary")
    assert not hasattr(runner, "__dict__")
    with pytest.raises(AttributeError):
        runner.foreign = object()
    public_methods = {
        name for name in dir(ReplayBacktestRunner) if not name.startswith("_")
    }
    assert public_methods == {"assemble_step", "assemble_summary"}
