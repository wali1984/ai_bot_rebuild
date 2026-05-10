from v2.backend.app.composition.degraded_state_fail_closed_gates import (
    build_degraded_state_fail_closed_gates_runtime,
)
from v2.backend.app.domain.degraded_state_fail_closed_gates import (
    DEGRADED_SOURCE_OK,
)
from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_DENY_DEFAULT,
    RiskDecisionRecord,
)


def _risk_record() -> RiskDecisionRecord:
    return RiskDecisionRecord(
        risk_decision_id="risk-1",
        decision_id="decision-1",
        prediction_id="prediction-1",
        feature_snapshot_id="feature-1",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1000,
        risk_action=RISK_DECISION_ACTION_DENY,
        risk_reason_code=RISK_DECISION_REASON_DENY_DEFAULT,
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )


def test_runtime_degraded_state_now_invokes_clock_zero_times_per_call() -> None:
    calls = 0

    def clock() -> int:
        nonlocal calls
        calls += 1
        return 999

    runtime = build_degraded_state_fail_closed_gates_runtime(now_ms_clock=clock)
    runtime.degraded_state_now(
        upstream_record=_risk_record(),
        smc_state=DEGRADED_SOURCE_OK,
        smc_age_ms=50,
        liq_state=DEGRADED_SOURCE_OK,
        liq_age_ms=60,
        oi_state=DEGRADED_SOURCE_OK,
        oi_age_ms=70,
        orderbook_state=DEGRADED_SOURCE_OK,
        orderbook_age_ms=80,
        trainer_model_version="hybrid_trainer_v2026_05",
        trainer_checkpoint_id="ckpt_duplicate_signal_blocked_2026_05",
        trainer_confidence_raw=0.71,
        trainer_confidence_calibrated=0.68,
        trainer_worker_liveness="alive",
    )
    assert calls == 0
