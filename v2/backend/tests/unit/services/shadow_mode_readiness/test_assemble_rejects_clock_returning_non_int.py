import pytest

from v2.backend.app.services.shadow_mode_readiness import (
    ShadowModeReadinessServiceError,
    assemble_shadow_mode_readiness_flag,
)


def test_assemble_rejects_clock_returning_non_int() -> None:
    for clock in (lambda: 1.0, lambda: "100"):
        with pytest.raises(ShadowModeReadinessServiceError) as exc_info:
            assemble_shadow_mode_readiness_flag(
                requested_state="not_ready",
                now_ms_clock=clock,  # type: ignore[arg-type]
            )
        assert exc_info.value.code == "must_be_int"
        assert exc_info.value.field == "now_ms_clock"
