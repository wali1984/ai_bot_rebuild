import dataclasses

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestStep


def test_step_constructs_with_valid_inputs_record_allow_long():
    step = ReplayBacktestStep(
        replay_step_id="step-1",
        replay_run_id="run-1",
        paper_trade_id="paper-1",
        risk_decision_id="risk-1",
        decision_id="decision-1",
        prediction_id="prediction-1",
        feature_snapshot_id="feature-1",
        symbol="BTCUSDT",
        step_ts_ms=123,
        step_action='step_record_allow',
        step_reason_code='step_mirror_allow_proceed_long',
        input_paper_action='record_allow',
        input_paper_reason_code='mirror_allow_proceed_long',
        live_blocked=True,
    )
    assert step.step_reason_code == 'step_mirror_allow_proceed_long'
    assert isinstance(step.__class__.__dict__.get("__slots__"), tuple)
    try:
        step.replay_step_id = "x"
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("expected frozen step")
    try:
        setattr(step, "unknown", "x")
    except (AttributeError, TypeError):
        pass
    else:
        raise AssertionError("expected slotted step")
