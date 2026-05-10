from __future__ import annotations

from v2.backend.app.domain.provenance_dedupe_attribution import ProvenanceRecord
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord

from .errors import ProvenanceServiceError


def assemble_provenance_record(
    *,
    upstream_record: RiskDecisionRecord,
    source_id: str,
    ingestor_id: str,
    source_ts_ms: int,
    ingest_ts_ms: int,
    trainer_model_version: str,
    trainer_checkpoint_id: str,
    trainer_confidence_raw: float,
    trainer_confidence_calibrated: float,
    trainer_worker_liveness: str,
) -> ProvenanceRecord:
    if not isinstance(upstream_record, RiskDecisionRecord):
        raise ProvenanceServiceError(
            "must_be_risk_decision_record",
            field="upstream_record",
        )

    try:
        return ProvenanceRecord(
            provenance_id=_derive_provenance_id(
                decision_id=upstream_record.decision_id,
                source_id=source_id,
                ingestor_id=ingestor_id,
            ),
            source_id=source_id,
            ingestor_id=ingestor_id,
            source_ts_ms=source_ts_ms,
            ingest_ts_ms=ingest_ts_ms,
            freshness_ms=ingest_ts_ms - source_ts_ms,
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
        raise ProvenanceServiceError(
            "invalid_provenance_record",
            field="upstream_record",
        ) from exc


def _derive_provenance_id(
    *,
    decision_id: str,
    source_id: str,
    ingestor_id: str,
) -> str:
    return f"prov:{decision_id}:{source_id}:{ingestor_id}"[:128]
