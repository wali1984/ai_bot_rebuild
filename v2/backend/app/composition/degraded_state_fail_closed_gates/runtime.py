from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.degraded_state_fail_closed_gates import (
    DegradedStateRecord,
)
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.degraded_state_fail_closed_gates import (
    assemble_degraded_state_record,
)

from .errors import DegradedStateFailClosedGatesRuntimeCompositionError


class DegradedStateFailClosedGatesRuntime:
    __slots__ = ("degraded_state_now",)

    def __init__(
        self,
        *,
        degraded_state_now: Callable[..., DegradedStateRecord],
    ) -> None:
        self.degraded_state_now = degraded_state_now


def build_degraded_state_fail_closed_gates_runtime(
    *,
    now_ms_clock: Callable[[], int],
) -> DegradedStateFailClosedGatesRuntime:
    if not callable(now_ms_clock):
        raise DegradedStateFailClosedGatesRuntimeCompositionError(
            "must_be_callable",
            field="now_ms_clock",
        )

    _now_ms_clock = now_ms_clock
    # Reserved for a future Phase 2Z-follow-up where the runtime emits its own
    # typed timestamp. The current record carries per-source *_age_ms and a
    # decision-id-derived degraded_state_id, so the closure invokes the
    # captured clock zero times per call.

    def _degraded_state_now(
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
        return assemble_degraded_state_record(
            upstream_record=upstream_record,
            smc_state=smc_state,
            smc_age_ms=smc_age_ms,
            liq_state=liq_state,
            liq_age_ms=liq_age_ms,
            oi_state=oi_state,
            oi_age_ms=oi_age_ms,
            orderbook_state=orderbook_state,
            orderbook_age_ms=orderbook_age_ms,
            trainer_model_version=trainer_model_version,
            trainer_checkpoint_id=trainer_checkpoint_id,
            trainer_confidence_raw=trainer_confidence_raw,
            trainer_confidence_calibrated=trainer_confidence_calibrated,
            trainer_worker_liveness=trainer_worker_liveness,
        )

    return DegradedStateFailClosedGatesRuntime(
        degraded_state_now=_degraded_state_now,
    )
