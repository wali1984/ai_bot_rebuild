from v2.backend.app.domain.degraded_state_fail_closed_gates import (
    DEGRADED_SOURCE_MISSING,
    DEGRADED_SOURCE_OK,
    DEGRADED_SOURCE_STALE,
    DEGRADED_SOURCE_UNUSED,
)
from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_DENY_DEFAULT,
    RiskDecisionRecord,
)
from v2.backend.app.services.degraded_state_fail_closed_gates import (
    assemble_degraded_state_record,
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


def _assemble(
    *,
    smc_state: str,
    liq_state: str,
    oi_state: str,
    orderbook_state: str,
) -> bool:
    record = assemble_degraded_state_record(
        upstream_record=_risk_record(),
        smc_state=smc_state,
        smc_age_ms=50,
        liq_state=liq_state,
        liq_age_ms=60,
        oi_state=oi_state,
        oi_age_ms=70,
        orderbook_state=orderbook_state,
        orderbook_age_ms=80,
        trainer_model_version="hybrid_trainer_v2026_05",
        trainer_checkpoint_id="ckpt_duplicate_signal_blocked_2026_05",
        trainer_confidence_raw=0.71,
        trainer_confidence_calibrated=0.68,
        trainer_worker_liveness="alive",
    )
    return record.fail_closed


def test_service_all_sources_ok_yields_fail_closed_false() -> None:
    assert (
        _assemble(
            smc_state=DEGRADED_SOURCE_OK,
            liq_state=DEGRADED_SOURCE_OK,
            oi_state=DEGRADED_SOURCE_OK,
            orderbook_state=DEGRADED_SOURCE_OK,
        )
        is False
    )


def test_service_smc_stale_yields_fail_closed_true() -> None:
    assert (
        _assemble(
            smc_state=DEGRADED_SOURCE_STALE,
            liq_state=DEGRADED_SOURCE_OK,
            oi_state=DEGRADED_SOURCE_OK,
            orderbook_state=DEGRADED_SOURCE_OK,
        )
        is True
    )


def test_service_liq_missing_yields_fail_closed_true() -> None:
    assert (
        _assemble(
            smc_state=DEGRADED_SOURCE_OK,
            liq_state=DEGRADED_SOURCE_MISSING,
            oi_state=DEGRADED_SOURCE_OK,
            orderbook_state=DEGRADED_SOURCE_OK,
        )
        is True
    )


def test_service_oi_unused_yields_fail_closed_false() -> None:
    assert (
        _assemble(
            smc_state=DEGRADED_SOURCE_OK,
            liq_state=DEGRADED_SOURCE_OK,
            oi_state=DEGRADED_SOURCE_UNUSED,
            orderbook_state=DEGRADED_SOURCE_OK,
        )
        is False
    )


def test_service_orderbook_missing_yields_fail_closed_true() -> None:
    assert (
        _assemble(
            smc_state=DEGRADED_SOURCE_OK,
            liq_state=DEGRADED_SOURCE_OK,
            oi_state=DEGRADED_SOURCE_OK,
            orderbook_state=DEGRADED_SOURCE_MISSING,
        )
        is True
    )


def test_service_all_sources_stale_yields_fail_closed_true() -> None:
    assert (
        _assemble(
            smc_state=DEGRADED_SOURCE_STALE,
            liq_state=DEGRADED_SOURCE_STALE,
            oi_state=DEGRADED_SOURCE_STALE,
            orderbook_state=DEGRADED_SOURCE_STALE,
        )
        is True
    )
