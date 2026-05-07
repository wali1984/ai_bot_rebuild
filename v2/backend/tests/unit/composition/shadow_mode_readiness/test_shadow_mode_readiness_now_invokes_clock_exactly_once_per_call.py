from v2.backend.app.composition.shadow_mode_readiness import (
    build_shadow_mode_readiness_runtime,
)


def test_shadow_mode_readiness_now_invokes_clock_exactly_once_per_call():
    calls = [0]

    def clock():
        calls[0] += 1
        return calls[0]

    runtime = build_shadow_mode_readiness_runtime(now_ms_clock=clock)

    runtime.shadow_mode_readiness_now(requested_state="not_ready")
    assert calls == [1]
    runtime.shadow_mode_readiness_now(requested_state="ready")
    assert calls == [2]
