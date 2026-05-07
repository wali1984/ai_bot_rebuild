from __future__ import annotations

from dataclasses import dataclass

from .errors import ShadowModeReadinessDomainError


SHADOW_MODE_NOT_READY = "not_ready"
SHADOW_MODE_READY = "ready"

_ALLOWED_STATES = frozenset({SHADOW_MODE_NOT_READY, SHADOW_MODE_READY})


@dataclass(frozen=True, slots=True)
class ShadowModeReadinessFlag:
    state: str
    flag_emitted_ts_ms: int
    live_blocked: bool

    def __post_init__(self) -> None:
        if not isinstance(self.state, str):
            raise ShadowModeReadinessDomainError(
                "shadow_mode_readiness_flag_unknown_state",
                field="state",
            )
        if self.state not in _ALLOWED_STATES:
            raise ShadowModeReadinessDomainError(
                "shadow_mode_readiness_flag_unknown_state",
                field="state",
            )

        if isinstance(self.flag_emitted_ts_ms, bool) or not isinstance(
            self.flag_emitted_ts_ms,
            int,
        ):
            raise ShadowModeReadinessDomainError(
                "shadow_mode_readiness_flag_emitted_ts_ms_must_be_non_negative_int",
                field="flag_emitted_ts_ms",
            )
        if self.flag_emitted_ts_ms < 0:
            raise ShadowModeReadinessDomainError(
                "shadow_mode_readiness_flag_emitted_ts_ms_must_be_non_negative_int",
                field="flag_emitted_ts_ms",
            )

        if not isinstance(self.live_blocked, bool):
            raise ShadowModeReadinessDomainError(
                "shadow_mode_readiness_flag_requires_live_blocked_true",
                field="live_blocked",
            )
        if self.live_blocked is not True:
            raise ShadowModeReadinessDomainError(
                "shadow_mode_readiness_flag_requires_live_blocked_true",
                field="live_blocked",
            )


def _shadow_mode_readiness_flag_setattr(
    self: ShadowModeReadinessFlag,
    name: str,
    value: object,
    _frozen_setattr: object = ShadowModeReadinessFlag.__setattr__,
) -> None:
    if name not in ShadowModeReadinessFlag.__slots__:
        raise AttributeError(name)
    _frozen_setattr(self, name, value)


ShadowModeReadinessFlag.__setattr__ = _shadow_mode_readiness_flag_setattr
