from v2.backend.app.domain.shadow_mode_readiness import ShadowModeReadinessFlag
from v2.backend.app.services.shadow_mode_readiness import (
    assemble_shadow_mode_readiness_flag,
)


def test_assemble_returns_flag_for_ready_requested_state() -> None:
    flag = assemble_shadow_mode_readiness_flag(
        requested_state="ready",
        now_ms_clock=lambda: 2000,
    )

    assert flag.state == "ready"
    assert flag.flag_emitted_ts_ms == 2000
    assert flag.live_blocked is True
    assert isinstance(flag, ShadowModeReadinessFlag)
