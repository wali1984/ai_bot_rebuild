from __future__ import annotations

from v2.backend.app.domain.provenance_dedupe_attribution import DedupeDecisionRecord
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord

from .errors import DedupeServiceError


def assemble_dedupe_decision_record(
    *,
    upstream_record: RiskDecisionRecord,
    dedupe_state: str,
    duplicate_of_decision_id: str | None,
    dedupe_reason: str,
    trainer_model_version: str,
    trainer_checkpoint_id: str,
    trainer_confidence_raw: float,
    trainer_confidence_calibrated: float,
    trainer_worker_liveness: str,
) -> DedupeDecisionRecord:
    if not isinstance(upstream_record, RiskDecisionRecord):
        raise DedupeServiceError(
            "must_be_risk_decision_record",
            field="upstream_record",
        )

    try:
        return DedupeDecisionRecord(
            dedupe_decision_id=_derive_dedupe_decision_id(
                decision_id=upstream_record.decision_id,
                dedupe_state=dedupe_state,
            ),
            dedupe_state=dedupe_state,
            duplicate_of_decision_id=duplicate_of_decision_id,
            dedupe_reason=dedupe_reason,
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
        raise DedupeServiceError(
            "invalid_dedupe_decision_record",
            field="upstream_record",
        ) from exc


def _derive_dedupe_decision_id(*, decision_id: str, dedupe_state: str) -> str:
    return f"dedupe:{decision_id}:{dedupe_state}"[:128]
