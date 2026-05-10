from __future__ import annotations

from dataclasses import dataclass

from .errors import ProvenanceDedupeAttributionDomainError
from .provenance_record import (
    _validate_confidence,
    _validate_id,
    _validate_live_blocked,
    _validate_text,
    _validate_trainer_worker_liveness,
)


DEDUPE_NEW = "DEDUPE_NEW"
DEDUPE_DUPLICATE_OF_PRIOR = "DEDUPE_DUPLICATE_OF_PRIOR"
DEDUPE_STALE_OUT_OF_ORDER = "DEDUPE_STALE_OUT_OF_ORDER"

_ALLOWED_DEDUPE_STATES = frozenset(
    {DEDUPE_NEW, DEDUPE_DUPLICATE_OF_PRIOR, DEDUPE_STALE_OUT_OF_ORDER}
)


@dataclass(frozen=True, slots=True)
class DedupeDecisionRecord:
    dedupe_decision_id: str
    dedupe_state: str
    duplicate_of_decision_id: str | None
    dedupe_reason: str
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    risk_decision_id: str
    model_version: str
    checkpoint_id: str
    confidence_raw: float
    confidence_calibrated: float
    trainer_worker_liveness: str
    live_blocked: bool

    def __post_init__(self) -> None:
        _validate_id(self.dedupe_decision_id, field="dedupe_decision_id")
        _validate_dedupe_state(self.dedupe_state)
        if self.dedupe_state == DEDUPE_DUPLICATE_OF_PRIOR:
            if self.duplicate_of_decision_id is None:
                raise ProvenanceDedupeAttributionDomainError(
                    "duplicate_of_decision_id_required",
                    field="duplicate_of_decision_id",
                )
            _validate_id(
                self.duplicate_of_decision_id,
                field="duplicate_of_decision_id",
            )
        elif self.duplicate_of_decision_id is not None:
            raise ProvenanceDedupeAttributionDomainError(
                "duplicate_of_decision_id_forbidden",
                field="duplicate_of_decision_id",
            )
        _validate_text(self.dedupe_reason, field="dedupe_reason")
        if len(self.dedupe_reason) > 64:
            raise ProvenanceDedupeAttributionDomainError(
                "must_be_at_most_64_chars",
                field="dedupe_reason",
            )
        _validate_id(self.decision_id, field="decision_id")
        _validate_id(self.prediction_id, field="prediction_id")
        _validate_id(self.feature_snapshot_id, field="feature_snapshot_id")
        _validate_id(self.risk_decision_id, field="risk_decision_id")
        _validate_text(self.model_version, field="model_version")
        _validate_text(self.checkpoint_id, field="checkpoint_id")
        _validate_confidence(self.confidence_raw, field="confidence_raw")
        _validate_confidence(
            self.confidence_calibrated,
            field="confidence_calibrated",
        )
        _validate_trainer_worker_liveness(self.trainer_worker_liveness)
        _validate_live_blocked(self.live_blocked)


def _validate_dedupe_state(value: str) -> None:
    if not isinstance(value, str):
        raise ProvenanceDedupeAttributionDomainError(
            "must_be_str",
            field="dedupe_state",
        )
    if value not in _ALLOWED_DEDUPE_STATES:
        raise ProvenanceDedupeAttributionDomainError(
            "invalid_dedupe_state",
            field="dedupe_state",
        )
