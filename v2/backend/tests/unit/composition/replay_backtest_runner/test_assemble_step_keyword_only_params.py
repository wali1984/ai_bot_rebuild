import pytest


def test_assemble_step_keyword_only_params():
    from v2.backend.app.composition.replay_backtest_runner import build_replay_backtest_runner

    runner = build_replay_backtest_runner(now_ms_clock=lambda: 2)

    with pytest.raises(TypeError):
        runner.assemble_step("not_keyword")
