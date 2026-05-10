import pytest

from v2.backend.app.domain.degraded_state_fail_closed_gates import (
    DEGRADED_SOURCE_OK,
    DegradedStateFailClosedGatesDomainError,
    DegradedStateRecord,
)


def _kwargs(**overrides: object) -> dict[str, object]:
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
    return values


def test_smc_state_unknown_rejected() -> None:
    with pytest.raises(DegradedStateFailClosedGatesDomainError):
        DegradedStateRecord(**_kwargs(smc_state="UNKNOWN"))  # type: ignore[arg-type]


def test_liq_state_unknown_rejected() -> None:
    with pytest.raises(DegradedStateFailClosedGatesDomainError):
        DegradedStateRecord(**_kwargs(liq_state="UNKNOWN"))  # type: ignore[arg-type]


def test_oi_state_unknown_rejected() -> None:
    with pytest.raises(DegradedStateFailClosedGatesDomainError):
        DegradedStateRecord(**_kwargs(oi_state="UNKNOWN"))  # type: ignore[arg-type]


def test_orderbook_state_unknown_rejected() -> None:
    with pytest.raises(DegradedStateFailClosedGatesDomainError):
        DegradedStateRecord(**_kwargs(orderbook_state="UNKNOWN"))  # type: ignore[arg-type]
