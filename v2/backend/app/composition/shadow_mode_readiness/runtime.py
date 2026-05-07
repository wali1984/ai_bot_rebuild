from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.shadow_mode_readiness import ShadowModeReadinessFlag
from v2.backend.app.services.shadow_mode_readiness import assemble_shadow_mode_readiness_flag
from .errors import ShadowModeReadinessRuntimeCompositionError


class ShadowModeReadinessRuntime:
    __slots__ = ("shadow_mode_readiness_now",)

    def __init__(
        self,
        *,
        shadow_mode_readiness_now: Callable[..., ShadowModeReadinessFlag],
    ) -> None:
        self.shadow_mode_readiness_now = shadow_mode_readiness_now


def build_shadow_mode_readiness_runtime(
    *,
    now_ms_clock: Callable[[], int],
) -> ShadowModeReadinessRuntime:
    if not callable(now_ms_clock):
        raise ShadowModeReadinessRuntimeCompositionError(
            "must_be_callable",
            field="now_ms_clock",
        )

    _now_ms_clock = now_ms_clock

    def _shadow_mode_readiness_now(
        *,
        requested_state: str,
    ) -> ShadowModeReadinessFlag:
        return assemble_shadow_mode_readiness_flag(requested_state=requested_state, now_ms_clock=_now_ms_clock)

    return ShadowModeReadinessRuntime(
        shadow_mode_readiness_now=_shadow_mode_readiness_now,
    )
