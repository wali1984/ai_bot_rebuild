from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.shadow_mode_readiness import (
    SHADOW_MODE_NOT_READY,
    SHADOW_MODE_READY,
    ShadowModeReadinessFlag,
)
from .errors import ShadowModeReadinessServiceError


_ALLOWED_REQUESTED_STATES = frozenset({SHADOW_MODE_NOT_READY, SHADOW_MODE_READY})


def assemble_shadow_mode_readiness_flag(
    *,
    requested_state: str,
    now_ms_clock: Callable[[], int],
) -> ShadowModeReadinessFlag:
    if type(requested_state) is not str:
        raise ShadowModeReadinessServiceError("must_be_str", field="requested_state")
    if not callable(now_ms_clock):
        raise ShadowModeReadinessServiceError("must_be_callable", field="now_ms_clock")
    if requested_state not in _ALLOWED_REQUESTED_STATES:
        raise ShadowModeReadinessServiceError(
            "shadow_mode_readiness_service_unrecognized_requested_state",
            field="requested_state",
        )

    now_ms = now_ms_clock()
    if isinstance(now_ms, bool) or type(now_ms) is not int:
        raise ShadowModeReadinessServiceError("must_be_int", field="now_ms_clock")
    if now_ms < 0:
        raise ShadowModeReadinessServiceError("must_be_nonnegative", field="now_ms_clock")

    if requested_state == SHADOW_MODE_NOT_READY:
        flag_state = SHADOW_MODE_NOT_READY
    elif requested_state == SHADOW_MODE_READY:
        flag_state = SHADOW_MODE_READY
    else:
        raise ShadowModeReadinessServiceError(
            "shadow_mode_readiness_service_unrecognized_requested_state",
            field="requested_state",
        )

    return ShadowModeReadinessFlag(
        state=flag_state,
        flag_emitted_ts_ms=now_ms,
        live_blocked=True,
    )
