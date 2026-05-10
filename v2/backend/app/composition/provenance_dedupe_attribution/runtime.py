from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.provenance_dedupe_attribution import (
    DedupeDecisionRecord,
    ProvenanceRecord,
)
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.provenance_dedupe_attribution import (
    assemble_dedupe_decision_record,
    assemble_provenance_record,
)

from .errors import ProvenanceDedupeAttributionRuntimeCompositionError


class ProvenanceDedupeAttributionRuntime:
    __slots__ = ("provenance_now", "dedupe_decision_now")

    def __init__(
        self,
        *,
        provenance_now: Callable[..., ProvenanceRecord],
        dedupe_decision_now: Callable[..., DedupeDecisionRecord],
    ) -> None:
        self.provenance_now = provenance_now
        self.dedupe_decision_now = dedupe_decision_now


def build_provenance_dedupe_attribution_runtime(
    *,
    now_ms_clock: Callable[[], int],
) -> ProvenanceDedupeAttributionRuntime:
    if not callable(now_ms_clock):
        raise ProvenanceDedupeAttributionRuntimeCompositionError(
            "must_be_callable",
            field="now_ms_clock",
        )

    _now_ms_clock = now_ms_clock
    # Reserved for future timestamping; current records carry source/ingest times.

    def _provenance_now(
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
        return assemble_provenance_record(
            upstream_record=upstream_record,
            source_id=source_id,
            ingestor_id=ingestor_id,
            source_ts_ms=source_ts_ms,
            ingest_ts_ms=ingest_ts_ms,
            trainer_model_version=trainer_model_version,
            trainer_checkpoint_id=trainer_checkpoint_id,
            trainer_confidence_raw=trainer_confidence_raw,
            trainer_confidence_calibrated=trainer_confidence_calibrated,
            trainer_worker_liveness=trainer_worker_liveness,
        )

    def _dedupe_decision_now(
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
        return assemble_dedupe_decision_record(
            upstream_record=upstream_record,
            dedupe_state=dedupe_state,
            duplicate_of_decision_id=duplicate_of_decision_id,
            dedupe_reason=dedupe_reason,
            trainer_model_version=trainer_model_version,
            trainer_checkpoint_id=trainer_checkpoint_id,
            trainer_confidence_raw=trainer_confidence_raw,
            trainer_confidence_calibrated=trainer_confidence_calibrated,
            trainer_worker_liveness=trainer_worker_liveness,
        )

    return ProvenanceDedupeAttributionRuntime(
        provenance_now=_provenance_now,
        dedupe_decision_now=_dedupe_decision_now,
    )
