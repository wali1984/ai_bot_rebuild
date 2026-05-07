from v2.backend.app.composition.shadow_mode_readiness import (
    build_shadow_mode_readiness_runtime,
)


def test_shadow_mode_readiness_now_propagates_ready_state():
    runtime = build_shadow_mode_readiness_runtime(now_ms_clock=lambda: 11)

    result = runtime.shadow_mode_readiness_now(requested_state="ready")

    assert result.state == "ready"
    assert result.live_blocked is True
    assert result.flag_emitted_ts_ms == 11
