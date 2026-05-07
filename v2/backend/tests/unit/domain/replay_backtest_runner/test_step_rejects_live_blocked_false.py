import pytest

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestStep, ReplayBacktestRunnerDomainError


def test_step_rejects_live_blocked_false():
    with pytest.raises(ReplayBacktestRunnerDomainError) as error:
        ReplayBacktestStep(
        replay_step_id="step-1",
        replay_run_id="run-1",
        paper_trade_id="paper-1",
        risk_decision_id="risk-1",
        decision_id="decision-1",
        prediction_id="prediction-1",
        feature_snapshot_id="feature-1",
        symbol="BTCUSDT",
        step_ts_ms=123,
        step_action="step_record_allow",
        step_reason_code="step_mirror_allow_proceed_long",
        input_paper_action="record_allow",
        input_paper_reason_code="mirror_allow_proceed_long",
        live_blocked=False,
        )
    assert error.value.field == "live_blocked"
    assert error.value.reason == "replay_backtest_step_requires_live_blocked_true"
