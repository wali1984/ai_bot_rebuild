import pytest

from v2.backend.app.services.shadow_mode_readiness import (
    ShadowModeReadinessServiceError,
    assemble_shadow_mode_readiness_flag,
)


def test_assemble_rejects_bool_requested_state() -> None:
    for value in (True, False):
        with pytest.raises(ShadowModeReadinessServiceError) as exc_info:
            assemble_shadow_mode_readiness_flag(
                requested_state=value,  # type: ignore[arg-type]
                now_ms_clock=lambda: 1,
            )
        assert exc_info.value.code == "must_be_str"
        assert exc_info.value.field == "requested_state"
