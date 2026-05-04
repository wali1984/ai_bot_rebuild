from __future__ import annotations

from dataclasses import dataclass

from .errors import TrainerWorkerHealthDomainError


@dataclass(frozen=True, slots=True)
class TrainerWorkerHealthThresholds:
    prediction_age_degraded_ms: int
    prediction_age_critical_ms: int
    gpu_batch_age_degraded_ms: int
    gpu_batch_age_critical_ms: int
    proposal_age_degraded_ms: int
    proposal_age_critical_ms: int

    def __post_init__(self) -> None:
        for field in (
            "prediction_age_degraded_ms",
            "prediction_age_critical_ms",
            "gpu_batch_age_degraded_ms",
            "gpu_batch_age_critical_ms",
            "proposal_age_degraded_ms",
            "proposal_age_critical_ms",
        ):
            value = getattr(self, field)
            if type(value) is not int:
                raise TrainerWorkerHealthDomainError("must_be_int", field=field)
            if value < 1:
                raise TrainerWorkerHealthDomainError("must_be_at_least_one", field=field)

        for degraded_field, critical_field in (
            ("prediction_age_degraded_ms", "prediction_age_critical_ms"),
            ("gpu_batch_age_degraded_ms", "gpu_batch_age_critical_ms"),
            ("proposal_age_degraded_ms", "proposal_age_critical_ms"),
        ):
            if getattr(self, degraded_field) >= getattr(self, critical_field):
                raise TrainerWorkerHealthDomainError(
                    "critical_must_be_greater_than_degraded",
                    field=critical_field,
                )
