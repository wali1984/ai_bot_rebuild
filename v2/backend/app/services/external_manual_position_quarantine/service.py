from __future__ import annotations

from v2.backend.app.domain.external_manual_position_quarantine import (
    ExternalPositionQuarantineRecord,
    ManualPositionFlag,
)
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord

from .errors import ExternalManualPositionQuarantineServiceError


def assemble_external_position_quarantine_record(
    *,
    risk_decision_record: RiskDecisionRecord,
    manual_position_flag: ManualPositionFlag,
    trainer_model_version: str,
    trainer_checkpoint_id: str,
    trainer_confidence_raw: float,
    trainer_confidence_calibrated: float,
    trainer_worker_liveness: str,
) -> ExternalPositionQuarantineRecord:
    if not isinstance(risk_decision_record, RiskDecisionRecord):
        raise ExternalManualPositionQuarantineServiceError(
            "must_be_risk_decision_record",
            field="risk_decision_record",
        )
    if not isinstance(manual_position_flag, ManualPositionFlag):
        raise ExternalManualPositionQuarantineServiceError(
            "must_be_manual_position_flag",
            field="manual_position_flag",
        )

    try:
        return ExternalPositionQuarantineRecord(
            risk_decision_id=risk_decision_record.risk_decision_id,
            decision_id=risk_decision_record.decision_id,
            prediction_id=risk_decision_record.prediction_id,
            feature_snapshot_id=risk_decision_record.feature_snapshot_id,
            symbol=risk_decision_record.symbol,
            risk_decision_ts_ms=risk_decision_record.risk_decision_ts_ms,
            manual_position_flag=manual_position_flag,
            model_version=trainer_model_version,
            checkpoint_id=trainer_checkpoint_id,
            confidence_raw=trainer_confidence_raw,
            confidence_calibrated=trainer_confidence_calibrated,
            trainer_worker_liveness=trainer_worker_liveness,
            live_blocked=True,
        )
    except ValueError as exc:
        raise ExternalManualPositionQuarantineServiceError(
            "invalid_external_position_quarantine_record",
            field="risk_decision_record",
        ) from exc
