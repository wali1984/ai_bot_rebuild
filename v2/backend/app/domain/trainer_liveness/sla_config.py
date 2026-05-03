from __future__ import annotations

from dataclasses import dataclass

from .errors import LivenessDomainError


@dataclass(frozen=True, slots=True)
class LivenessSLAConfig:
    prediction_age_max_ms: int
    gpu_batch_age_max_ms: int
    proposal_age_max_ms: int
    prediction_stream_zero_growth_window_ms: int

    def __post_init__(self) -> None:
        for field in (
            "prediction_age_max_ms",
            "gpu_batch_age_max_ms",
            "proposal_age_max_ms",
            "prediction_stream_zero_growth_window_ms",
        ):
            if getattr(self, field) < 1:
                raise LivenessDomainError("must_be_at_least_one", field=field)
