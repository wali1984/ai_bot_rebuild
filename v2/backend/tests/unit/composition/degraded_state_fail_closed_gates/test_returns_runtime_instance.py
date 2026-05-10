from v2.backend.app.composition.degraded_state_fail_closed_gates import (
    DegradedStateFailClosedGatesRuntime,
    build_degraded_state_fail_closed_gates_runtime,
)


def test_returns_runtime_instance() -> None:
    runtime = build_degraded_state_fail_closed_gates_runtime(now_ms_clock=lambda: 1)
    assert isinstance(runtime, DegradedStateFailClosedGatesRuntime)
