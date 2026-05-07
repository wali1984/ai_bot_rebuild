from v2.backend.app.composition.shadow_mode_readiness import (
    build_shadow_mode_readiness_runtime,
)


def test_shadow_mode_readiness_now_does_not_mutate_supplied_input():
    requested_state = "not_ready"
    snapshot = requested_state
    original_id = id(requested_state)
    runtime = build_shadow_mode_readiness_runtime(now_ms_clock=lambda: 1)

    runtime.shadow_mode_readiness_now(requested_state=requested_state)

    assert requested_state == snapshot
    assert id(requested_state) == original_id
