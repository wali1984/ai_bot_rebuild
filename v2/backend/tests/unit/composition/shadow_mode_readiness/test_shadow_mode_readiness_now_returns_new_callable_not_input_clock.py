from v2.backend.app.composition.shadow_mode_readiness import (
    build_shadow_mode_readiness_runtime,
)


def test_shadow_mode_readiness_now_returns_new_callable_not_input_clock():
    now_ms_clock_lambda = lambda: 999

    runtime = build_shadow_mode_readiness_runtime(now_ms_clock=now_ms_clock_lambda)

    assert runtime.shadow_mode_readiness_now is not now_ms_clock_lambda
