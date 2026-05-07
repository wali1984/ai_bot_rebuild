from v2.backend.app.composition.shadow_mode_readiness import (
    build_shadow_mode_readiness_runtime,
)
from v2.backend.app.domain.shadow_mode_readiness import ShadowModeReadinessFlag


def test_shadow_mode_readiness_now_returns_shadow_mode_readiness_flag():
    state = "not" + "_ready"
    runtime = build_shadow_mode_readiness_runtime(now_ms_clock=lambda: 555)

    result = runtime.shadow_mode_readiness_now(requested_state=state)

    assert isinstance(result, ShadowModeReadinessFlag)
    assert result.state == state
    assert result.live_blocked is True
    assert result.flag_emitted_ts_ms == 555
