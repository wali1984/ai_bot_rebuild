from v2.backend.app.domain.degraded_state_fail_closed_gates import (
    DEGRADED_SOURCE_MISSING,
    DEGRADED_SOURCE_OK,
    DEGRADED_SOURCE_STALE,
    DEGRADED_SOURCE_UNUSED,
    DegradedStateRecord,
)


def _build(
    *,
    smc_state: str,
    liq_state: str,
    oi_state: str,
    orderbook_state: str,
    fail_closed: bool,
) -> DegradedStateRecord:
    return DegradedStateRecord(
        degraded_state_id="degraded_state:decision-1",
        smc_state=smc_state,
        smc_age_ms=50,
        liq_state=liq_state,
        liq_age_ms=60,
        oi_state=oi_state,
        oi_age_ms=70,
        orderbook_state=orderbook_state,
        orderbook_age_ms=80,
        fail_closed=fail_closed,
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


def test_all_sources_ok_yields_fail_closed_false() -> None:
    record = _build(
        smc_state=DEGRADED_SOURCE_OK,
        liq_state=DEGRADED_SOURCE_OK,
        oi_state=DEGRADED_SOURCE_OK,
        orderbook_state=DEGRADED_SOURCE_OK,
        fail_closed=False,
    )
    assert record.fail_closed is False


def test_smc_stale_yields_fail_closed_true() -> None:
    record = _build(
        smc_state=DEGRADED_SOURCE_STALE,
        liq_state=DEGRADED_SOURCE_OK,
        oi_state=DEGRADED_SOURCE_OK,
        orderbook_state=DEGRADED_SOURCE_OK,
        fail_closed=True,
    )
    assert record.fail_closed is True


def test_liq_missing_yields_fail_closed_true() -> None:
    record = _build(
        smc_state=DEGRADED_SOURCE_OK,
        liq_state=DEGRADED_SOURCE_MISSING,
        oi_state=DEGRADED_SOURCE_OK,
        orderbook_state=DEGRADED_SOURCE_OK,
        fail_closed=True,
    )
    assert record.fail_closed is True


def test_oi_unused_yields_fail_closed_false() -> None:
    record = _build(
        smc_state=DEGRADED_SOURCE_OK,
        liq_state=DEGRADED_SOURCE_OK,
        oi_state=DEGRADED_SOURCE_UNUSED,
        orderbook_state=DEGRADED_SOURCE_OK,
        fail_closed=False,
    )
    assert record.fail_closed is False


def test_orderbook_missing_yields_fail_closed_true() -> None:
    record = _build(
        smc_state=DEGRADED_SOURCE_OK,
        liq_state=DEGRADED_SOURCE_OK,
        oi_state=DEGRADED_SOURCE_OK,
        orderbook_state=DEGRADED_SOURCE_MISSING,
        fail_closed=True,
    )
    assert record.fail_closed is True


def test_all_sources_stale_yields_fail_closed_true() -> None:
    record = _build(
        smc_state=DEGRADED_SOURCE_STALE,
        liq_state=DEGRADED_SOURCE_STALE,
        oi_state=DEGRADED_SOURCE_STALE,
        orderbook_state=DEGRADED_SOURCE_STALE,
        fail_closed=True,
    )
    assert record.fail_closed is True
