from __future__ import annotations

from dataclasses import dataclass

from .errors import ProvenanceDedupeAttributionDomainError


_ALLOWED_TRAINER_WORKER_LIVENESS = frozenset({"alive", "degraded", "worker_dead"})


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    provenance_id: str
    source_id: str
    ingestor_id: str
    source_ts_ms: int
    ingest_ts_ms: int
    freshness_ms: int
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
        _validate_id(self.provenance_id, field="provenance_id")
        _validate_short_id(self.source_id, field="source_id")
        _validate_short_id(self.ingestor_id, field="ingestor_id")
        _validate_ts(self.source_ts_ms, field="source_ts_ms")
        _validate_ts(self.ingest_ts_ms, field="ingest_ts_ms")
        _validate_ts(self.freshness_ms, field="freshness_ms")
        if self.ingest_ts_ms < self.source_ts_ms:
            raise ProvenanceDedupeAttributionDomainError(
                "ingest_ts_before_source_ts",
                field="ingest_ts_ms",
            )
        if self.freshness_ms != self.ingest_ts_ms - self.source_ts_ms:
            raise ProvenanceDedupeAttributionDomainError(
                "freshness_mismatch",
                field="freshness_ms",
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


def _validate_id(value: str, *, field: str) -> None:
    _validate_text(value, field=field)
    if value != value.strip() or any(char.isspace() for char in value):
        raise ProvenanceDedupeAttributionDomainError(
            "must_not_have_whitespace",
            field=field,
        )
    if len(value) > 128:
        raise ProvenanceDedupeAttributionDomainError(
            "must_be_at_most_128_chars",
            field=field,
        )


def _validate_short_id(value: str, *, field: str) -> None:
    _validate_id(value, field=field)
    if len(value) > 64:
        raise ProvenanceDedupeAttributionDomainError(
            "must_be_at_most_64_chars",
            field=field,
        )


def _validate_text(value: str, *, field: str) -> None:
    if not isinstance(value, str):
        raise ProvenanceDedupeAttributionDomainError("must_be_str", field=field)
    if value == "":
        raise ProvenanceDedupeAttributionDomainError(
            "must_be_non_empty",
            field=field,
        )


def _validate_ts(value: int, *, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProvenanceDedupeAttributionDomainError("must_be_int", field=field)
    if value < 0:
        raise ProvenanceDedupeAttributionDomainError(
            "must_be_nonnegative",
            field=field,
        )


def _validate_confidence(value: float, *, field: str) -> None:
    if not isinstance(value, float) or isinstance(value, bool):
        raise ProvenanceDedupeAttributionDomainError("must_be_float", field=field)
    if value < 0.0 or value > 1.0:
        raise ProvenanceDedupeAttributionDomainError(
            "must_be_between_zero_and_one",
            field=field,
        )


def _validate_trainer_worker_liveness(value: str) -> None:
    if not isinstance(value, str):
        raise ProvenanceDedupeAttributionDomainError(
            "must_be_str",
            field="trainer_worker_liveness",
        )
    if value not in _ALLOWED_TRAINER_WORKER_LIVENESS:
        raise ProvenanceDedupeAttributionDomainError(
            "invalid_trainer_worker_liveness",
            field="trainer_worker_liveness",
        )


def _validate_live_blocked(value: bool) -> None:
    if not isinstance(value, bool):
        raise ProvenanceDedupeAttributionDomainError(
            "must_be_bool",
            field="live_blocked",
        )
    if value is not True:
        raise ProvenanceDedupeAttributionDomainError(
            "must_be_true",
            field="live_blocked",
        )
