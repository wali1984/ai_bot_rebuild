from __future__ import annotations

from dataclasses import dataclass

from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot

from .errors import TrainerWorkerHealthDomainError
from .health_status import (
    HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
    HEALTH_REASON_GPU_BATCH_AGE_CRITICAL,
    HEALTH_REASON_GPU_BATCH_AGE_DEGRADED,
    HEALTH_REASON_NO_SIGNALS_OBSERVED,
    HEALTH_REASON_PREDICTION_AGE_CRITICAL,
    HEALTH_REASON_PREDICTION_AGE_DEGRADED,
    HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH,
    HEALTH_REASON_PREDICTION_WORKER_DEAD,
    HEALTH_REASON_PROPOSAL_AGE_CRITICAL,
    HEALTH_REASON_PROPOSAL_AGE_DEGRADED,
    HEALTH_STATUS_CRITICAL,
    HEALTH_STATUS_DEGRADED,
    HEALTH_STATUS_HEALTHY,
    HEALTH_STATUS_UNKNOWN,
    _ALLOWED_HEALTH_REASONS,
    _ALLOWED_HEALTH_STATUSES,
)

_DEGRADED_BAND_REASONS = frozenset(
    {
        HEALTH_REASON_PREDICTION_AGE_DEGRADED,
        HEALTH_REASON_GPU_BATCH_AGE_DEGRADED,
        HEALTH_REASON_PROPOSAL_AGE_DEGRADED,
    }
)
_CRITICAL_BAND_REASONS = frozenset(
    {
        HEALTH_REASON_PREDICTION_AGE_CRITICAL,
        HEALTH_REASON_GPU_BATCH_AGE_CRITICAL,
        HEALTH_REASON_PROPOSAL_AGE_CRITICAL,
        HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH,
        HEALTH_REASON_PREDICTION_WORKER_DEAD,
        HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
    }
)


@dataclass(frozen=True, slots=True)
class TrainerWorkerHealthSnapshot:
    status: str
    reasons: tuple[str, ...]
    signal_snapshot: LivenessSignalSnapshot
    observation_ts_ms: int

    def __post_init__(self) -> None:
        if self.status not in _ALLOWED_HEALTH_STATUSES:
            raise TrainerWorkerHealthDomainError("invalid_status", field="status")
        if type(self.reasons) is not tuple:
            raise TrainerWorkerHealthDomainError("must_be_tuple", field="reasons")
        if any(type(reason) is not str or reason not in _ALLOWED_HEALTH_REASONS for reason in self.reasons):
            raise TrainerWorkerHealthDomainError("unknown_reason", field="reasons")
        if len(self.reasons) != len(frozenset(self.reasons)):
            raise TrainerWorkerHealthDomainError("duplicate_reasons", field="reasons")
        if not isinstance(self.signal_snapshot, LivenessSignalSnapshot):
            raise TrainerWorkerHealthDomainError(
                "must_be_liveness_signal_snapshot",
                field="signal_snapshot",
            )
        if self.observation_ts_ms != self.signal_snapshot.observation_ts_ms:
            raise TrainerWorkerHealthDomainError("must_match_snapshot", field="observation_ts_ms")
        if self.status == HEALTH_STATUS_HEALTHY and self.reasons != ():
            raise TrainerWorkerHealthDomainError("healthy_requires_empty_reasons", field="reasons")
        if self.status == HEALTH_STATUS_UNKNOWN and self.reasons != (HEALTH_REASON_NO_SIGNALS_OBSERVED,):
            raise TrainerWorkerHealthDomainError(
                "unknown_requires_no_signals_reason",
                field="reasons",
            )
        if self.status == HEALTH_STATUS_DEGRADED:
            if len(self.reasons) == 0:
                raise TrainerWorkerHealthDomainError(
                    "degraded_requires_at_least_one_reason",
                    field="reasons",
                )
            if any(reason not in _DEGRADED_BAND_REASONS for reason in self.reasons):
                raise TrainerWorkerHealthDomainError(
                    "degraded_reasons_must_be_degraded_band",
                    field="reasons",
                )
        if self.status == HEALTH_STATUS_CRITICAL and not any(
            reason in _CRITICAL_BAND_REASONS for reason in self.reasons
        ):
            raise TrainerWorkerHealthDomainError(
                "critical_requires_at_least_one_critical_reason",
                field="reasons",
            )
