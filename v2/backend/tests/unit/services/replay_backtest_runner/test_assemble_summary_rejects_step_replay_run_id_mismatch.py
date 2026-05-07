import pytest

from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun, ReplayBacktestStep
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_summary
from v2.backend.app.services.replay_backtest_runner.errors import ReplayBacktestRunnerServiceError


def test_assemble_summary_rejects_step_replay_run_id_mismatch():
    run = ReplayBacktestRun(replay_run_id="run_b", run_mode="backtest", symbol="BTCUSDT", run_started_ts_ms=0, run_ended_ts_ms=0, live_blocked=True)
    step = ReplayBacktestStep(replay_step_id="rstep_mismatch", replay_run_id="run_a", paper_trade_id="pt_mismatch", risk_decision_id="rd_mismatch", decision_id="dec_mismatch", prediction_id="pred_mismatch", feature_snapshot_id="snap_mismatch", symbol="BTCUSDT", step_ts_ms=1, step_action="step_record_allow", step_reason_code="step_mirror_allow_proceed_long", input_paper_action="record_allow", input_paper_reason_code="mirror_allow_proceed_long", live_blocked=True)

    with pytest.raises(ReplayBacktestRunnerServiceError) as exc:
        assemble_replay_backtest_summary(replay_run=run, steps=(step,), now_ms_clock=lambda: 1)

    assert exc.value.code == "step_replay_run_id_must_match_replay_run_id"
    assert exc.value.field == "steps[0].replay_run_id"
