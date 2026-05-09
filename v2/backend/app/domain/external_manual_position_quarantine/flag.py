from __future__ import annotations

from dataclasses import dataclass

from .errors import ExternalManualPositionQuarantineDomainError


MANUAL_POSITION_QUARANTINED = "manual_position_quarantined"
MANUAL_POSITION_NOT_PRESENT = "manual_position_not_present"

_ALLOWED_STATES = frozenset(
    {
        MANUAL_POSITION_QUARANTINED,
        MANUAL_POSITION_NOT_PRESENT,
    }
)


@dataclass(frozen=True, slots=True)
class ManualPositionFlag:
    state: str
    live_blocked: bool

    def __post_init__(self) -> None:
        if not isinstance(self.state, str):
            raise ExternalManualPositionQuarantineDomainError(
                "manual_position_flag_unknown_state",
                field="state",
            )
        if self.state not in _ALLOWED_STATES:
            raise ExternalManualPositionQuarantineDomainError(
                "manual_position_flag_unknown_state",
                field="state",
            )
        if not isinstance(self.live_blocked, bool):
            raise ExternalManualPositionQuarantineDomainError(
                "manual_position_flag_requires_live_blocked_true",
                field="live_blocked",
            )
        if self.live_blocked is not True:
            raise ExternalManualPositionQuarantineDomainError(
                "manual_position_flag_requires_live_blocked_true",
                field="live_blocked",
            )
