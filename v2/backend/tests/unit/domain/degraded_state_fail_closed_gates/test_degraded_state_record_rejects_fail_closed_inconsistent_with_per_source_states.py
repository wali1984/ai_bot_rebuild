import pytest

from v2.backend.app.domain.degraded_state_fail_closed_gates import (
    DEGRADED_SOURCE_OK,
    DEGRADED_SOURCE_STALE,
    DegradedStateFailClosedGatesDomainError,
    DegradedStateRecord,
)


def test_fail_closed_false_with_stale_smc_rejected() -> None:
    with pytest.raises(DegradedStateFailClosedGatesDomainError):
        DegradedStateRecord(
            degraded_state_id="degraded_state:decision-1",
            smc_state=DEGRADED_SOURCE_STALE,
            smc_age_ms=50,
            liq_state=DEGRADED_SOURCE_OK,
            liq_age_ms=60,
            oi_state=DEGRADED_SOURCE_OK,
            oi_age_ms=70,
            orderbook_state=DEGRADED_SOURCE_OK,
            orderbook_age_ms=80,
            fail_closed=False,
            decision_id="decision-1",
            prediction_id="prediction-1",
            feature_snapshot_id="feature-1",
            risk_decision_id="risk-1",
            model_version="hybrid_trainer_v2026_05",
            checkpoint_id="ckpt_duplicate_signal_blocked_2026_05",
            confidence_raw=0.71,
            confidence_calibrated=0.68,
            trainer_worker_liveness="alive",
            live_blocked=True,
        )


def test_fail_closed_true_with_all_ok_rejected() -> None:
    with pytest.raises(DegradedStateFailClosedGatesDomainError):
        DegradedStateRecord(
            degraded_state_id="degraded_state:decision-1",
            smc_state=DEGRADED_SOURCE_OK,
            smc_age_ms=50,
            liq_state=DEGRADED_SOURCE_OK,
            liq_age_ms=60,
            oi_state=DEGRADED_SOURCE_OK,
            oi_age_ms=70,
            orderbook_state=DEGRADED_SOURCE_OK,
            orderbook_age_ms=80,
            fail_closed=True,
            decision_id="decision-1",
            prediction_id="prediction-1",
            feature_snapshot_id="feature-1",
            risk_decision_id="risk-1",
            model_version="hybrid_trainer_v2026_05",
            checkpoint_id="ckpt_duplicate_signal_blocked_2026_05",
            confidence_raw=0.71,
            confidence_calibrated=0.68,
            trainer_worker_liveness="alive",
            live_blocked=True,
        )
