from __future__ import annotations

from dataclasses import dataclass

from .errors import LivenessDomainError
from .signal_snapshot import LivenessSignalSnapshot


LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA = "prediction_age_exceeds_sla"
LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA = "gpu_batch_age_exceeds_sla"
LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA = "proposal_age_exceeds_sla"
LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH = "prediction_stream_zero_growth"
LIVENESS_REASON_PREDICTION_WORKER_DEAD = "prediction_worker_dead"
LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED = "fatal_log_signature_observed"

_ALLOWED_LIVENESS_REASONS = frozenset(
    {
        LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA,
        LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA,
        LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA,
        LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH,
        LIVENESS_REASON_PREDICTION_WORKER_DEAD,
        LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
    }
)

LIVENESS_ALERT_CODE = "TRAINER_INTERNAL_LIVENESS_CRITICAL"


@dataclass(frozen=True, slots=True)
class LivenessAlert:
    alert_code: str
    reasons: tuple[str, ...]
    observation_ts_ms: int
    snapshot: LivenessSignalSnapshot

    def __post_init__(self) -> None:
        if self.alert_code != LIVENESS_ALERT_CODE:
            raise LivenessDomainError("invalid_alert_code", field="alert_code")
        if not self.reasons:
            raise LivenessDomainError("must_have_reasons", field="reasons")
        if len(set(self.reasons)) != len(self.reasons):
            raise LivenessDomainError("duplicate_reasons", field="reasons")
        unknown = [reason for reason in self.reasons if reason not in _ALLOWED_LIVENESS_REASONS]
        if unknown:
            raise LivenessDomainError("unknown_reason", field="reasons")
        if self.observation_ts_ms != self.snapshot.observation_ts_ms:
            raise LivenessDomainError("must_match_snapshot", field="observation_ts_ms")
