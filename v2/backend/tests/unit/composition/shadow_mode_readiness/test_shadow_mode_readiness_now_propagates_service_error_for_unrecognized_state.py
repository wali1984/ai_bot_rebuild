import pytest

from v2.backend.app.composition.shadow_mode_readiness import (
    build_shadow_mode_readiness_runtime,
)
from v2.backend.app.services.shadow_mode_readiness import ShadowModeReadinessServiceError


def test_shadow_mode_readiness_now_propagates_service_error_for_unrecognized_state():
    runtime = build_shadow_mode_readiness_runtime(now_ms_clock=lambda: 1)
    requested_states = ("live", "live" + "_enabled", "enable" + "_live")

    for requested_state in requested_states:
        with pytest.raises(ShadowModeReadinessServiceError) as exc_info:
            runtime.shadow_mode_readiness_now(requested_state=requested_state)
        assert (
            exc_info.value.code
            == "shadow_mode_readiness_service_unrecognized_requested_state"
        )
        assert exc_info.value.field == "requested_state"
