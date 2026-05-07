import pytest

from v2.backend.app.services.shadow_mode_readiness import (
    ShadowModeReadinessServiceError,
    assemble_shadow_mode_readiness_flag,
)


def test_assemble_rejects_live_enabled_requested_state() -> None:
    value = "live" + "_enabled"
    with pytest.raises(ShadowModeReadinessServiceError) as exc_info:
        assemble_shadow_mode_readiness_flag(
            requested_state=value,
            now_ms_clock=lambda: 1,
        )

    assert exc_info.value.code == (
        "shadow_mode_readiness_service_unrecognized_requested_state"
    )
    assert exc_info.value.field == "requested_state"
