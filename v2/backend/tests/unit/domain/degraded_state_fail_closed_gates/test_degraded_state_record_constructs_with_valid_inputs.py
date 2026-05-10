from v2.backend.app.domain.degraded_state_fail_closed_gates import (
    DEGRADED_SOURCE_OK,
    DegradedStateRecord,
)


def _record(**overrides: object) -> DegradedStateRecord:
    values: dict[str, object] = {
        "degraded_state_id": "degraded_state:decision-1",
        "smc_state": DEGRADED_SOURCE_OK,
        "smc_age_ms": 50,
        "liq_state": DEGRADED_SOURCE_OK,
        "liq_age_ms": 60,
        "oi_state": DEGRADED_SOURCE_OK,
        "oi_age_ms": 70,
        "orderbook_state": DEGRADED_SOURCE_OK,
        "orderbook_age_ms": 80,
        "fail_closed": False,
        "decision_id": "decision-1",
        "prediction_id": "prediction-1",
        "feature_snapshot_id": "feature-1",
        "risk_decision_id": "risk-1",
        "model_version": "hybrid_trainer_v2026_05",
        "checkpoint_id": "ckpt_duplicate_signal_blocked_2026_05",
        "confidence_raw": 0.71,
        "confidence_calibrated": 0.68,
        "trainer_worker_liveness": "alive",
        "live_blocked": True,
    }
    values.update(overrides)
    return DegradedStateRecord(**values)  # type: ignore[arg-type]


def test_degraded_state_record_constructs_with_valid_inputs() -> None:
    record = _record()
    assert record.degraded_state_id == "degraded_state:decision-1"
    assert record.fail_closed is False
    assert record.live_blocked is True
