import pytest

from v2.backend.app.services.shadow_mode_readiness import (
    ShadowModeReadinessServiceError,
    assemble_shadow_mode_readiness_flag,
)
from v2.backend.app.services.shadow_mode_readiness import service


def test_assemble_rejects_unrecognized_requested_state() -> None:
    assert service._ALLOWED_REQUESTED_STATES == frozenset({"not_ready", "ready"})
    with pytest.raises(ShadowModeReadinessServiceError) as exc_info:
        assemble_shadow_mode_readiness_flag(
            requested_state="foo_bar_synthetic",
            now_ms_clock=lambda: 1,
        )

    assert exc_info.value.code == (
        "shadow_mode_readiness_service_unrecognized_requested_state"
    )
    assert exc_info.value.field == "requested_state"
