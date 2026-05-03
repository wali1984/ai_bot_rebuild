from __future__ import annotations

from dataclasses import dataclass

from .errors import LivenessStreamGrowthDomainError


@dataclass(frozen=True, slots=True)
class GrowthWindowConfig:
    window_ms: int
    boundary_inclusive: bool = False

    def __post_init__(self) -> None:
        if type(self.window_ms) is not int:
            raise LivenessStreamGrowthDomainError("must_be_int", field="window_ms")
        if self.window_ms < 1:
            raise LivenessStreamGrowthDomainError("must_be_at_least_one", field="window_ms")
        if type(self.boundary_inclusive) is not bool:
            raise LivenessStreamGrowthDomainError("must_be_bool", field="boundary_inclusive")
