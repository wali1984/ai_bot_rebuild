from __future__ import annotations

from v2.backend.app.domain.degraded_state_fail_closed_gates import (
    DegradedStateRecord,
)
from v2.backend.app.domain.degraded_state_fail_closed_gates.degraded_source_state import (
    _FAIL_CLOSED_TRIGGER_STATES,
)
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord

from .errors import DegradedStateFailClosedGatesServiceError


def assemble_degraded_state_record(
    *,
    upstream_record: RiskDecisionRecord,
    smc_state: str,
    smc_age_ms: int,
    liq_state: str,
    liq_age_ms: int,
    oi_state: str,
    oi_age_ms: int,
    orderbook_state: str,
    orderbook_age_ms: int,
    trainer_model_version: str,
    trainer_checkpoint_id: str,
    trainer_confidence_raw: float,
    trainer_confidence_calibrated: float,
    trainer_worker_liveness: str,
) -> DegradedStateRecord:
    if not isinstance(upstream_record, RiskDecisionRecord):
        raise DegradedStateFailClosedGatesServiceError(
            "must_be_risk_decision_record",
            field="upstream_record",
        )

    fail_closed = (
        smc_state in _FAIL_CLOSED_TRIGGER_STATES
        or liq_state in _FAIL_CLOSED_TRIGGER_STATES
        or oi_state in _FAIL_CLOSED_TRIGGER_STATES
        or orderbook_state in _FAIL_CLOSED_TRIGGER_STATES
    )

    try:
        return DegradedStateRecord(
            degraded_state_id=_derive_degraded_state_id(
                decision_id=upstream_record.decision_id,
            ),
            smc_state=smc_state,
            smc_age_ms=smc_age_ms,
            liq_state=liq_state,
            liq_age_ms=liq_age_ms,
            oi_state=oi_state,
            oi_age_ms=oi_age_ms,
            orderbook_state=orderbook_state,
            orderbook_age_ms=orderbook_age_ms,
            fail_closed=fail_closed,
            decision_id=upstream_record.decision_id,
            prediction_id=upstream_record.prediction_id,
            feature_snapshot_id=upstream_record.feature_snapshot_id,
            risk_decision_id=upstream_record.risk_decision_id,
            model_version=trainer_model_version,
            checkpoint_id=trainer_checkpoint_id,
            confidence_raw=trainer_confidence_raw,
            confidence_calibrated=trainer_confidence_calibrated,
            trainer_worker_liveness=trainer_worker_liveness,
            live_blocked=True,
        )
    except ValueError as exc:
        raise DegradedStateFailClosedGatesServiceError(
            "invalid_degraded_state_record",
            field="upstream_record",
        ) from exc


def _derive_degraded_state_id(*, decision_id: str) -> str:
    return f"degraded_state:{decision_id}"[:128]
