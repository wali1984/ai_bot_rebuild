from v2.backend.app.composition.shadow_mode_readiness import (
    ShadowModeReadinessRuntime,
    build_shadow_mode_readiness_runtime,
)


def test_returns_shadow_mode_readiness_runtime_instance():
    clock = lambda: 123

    runtime = build_shadow_mode_readiness_runtime(now_ms_clock=clock)

    assert isinstance(runtime, ShadowModeReadinessRuntime)
    assert callable(runtime.shadow_mode_readiness_now)
    assert runtime.shadow_mode_readiness_now is not clock
