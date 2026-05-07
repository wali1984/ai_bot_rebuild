from v2.backend.app.composition.shadow_mode_readiness import (
    build_shadow_mode_readiness_runtime,
)


def test_shadow_mode_readiness_now_propagates_not_ready_state():
    runtime = build_shadow_mode_readiness_runtime(now_ms_clock=lambda: 7)

    result = runtime.shadow_mode_readiness_now(requested_state="not_ready")

    assert result.state == "not_ready"
    assert result.live_blocked is True
    assert result.flag_emitted_ts_ms == 7
