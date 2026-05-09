from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.external_manual_position_quarantine import (
    ExternalPositionQuarantineRecord,
    ManualPositionFlag,
)
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.external_manual_position_quarantine import (
    assemble_external_position_quarantine_record,
)

from .errors import ExternalManualPositionQuarantineRuntimeCompositionError


class ExternalManualPositionQuarantineRuntime:
    __slots__ = ("external_manual_position_quarantine_now",)

    def __init__(
        self,
        *,
        external_manual_position_quarantine_now: Callable[
            ...,
            ExternalPositionQuarantineRecord,
        ],
    ) -> None:
        self.external_manual_position_quarantine_now = (
            external_manual_position_quarantine_now
        )


def build_external_position_quarantine_runtime(
    *,
    now_ms_clock: Callable[[], int],
) -> ExternalManualPositionQuarantineRuntime:
    if not callable(now_ms_clock):
        raise ExternalManualPositionQuarantineRuntimeCompositionError(
            "must_be_callable",
            field="now_ms_clock",
        )

    _now_ms_clock = now_ms_clock
    _ = _now_ms_clock

    def _external_manual_position_quarantine_now(
        *,
        risk_decision_record: RiskDecisionRecord,
        manual_position_flag: ManualPositionFlag,
        trainer_model_version: str,
        trainer_checkpoint_id: str,
        trainer_confidence_raw: float,
        trainer_confidence_calibrated: float,
        trainer_worker_liveness: str,
    ) -> ExternalPositionQuarantineRecord:
        return assemble_external_position_quarantine_record(
            risk_decision_record=risk_decision_record,
            manual_position_flag=manual_position_flag,
            trainer_model_version=trainer_model_version,
            trainer_checkpoint_id=trainer_checkpoint_id,
            trainer_confidence_raw=trainer_confidence_raw,
            trainer_confidence_calibrated=trainer_confidence_calibrated,
            trainer_worker_liveness=trainer_worker_liveness,
        )

    return ExternalManualPositionQuarantineRuntime(
        external_manual_position_quarantine_now=(
            _external_manual_position_quarantine_now
        ),
    )
