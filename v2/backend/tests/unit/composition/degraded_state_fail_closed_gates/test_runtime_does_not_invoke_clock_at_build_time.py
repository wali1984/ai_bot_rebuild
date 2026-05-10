from v2.backend.app.composition.degraded_state_fail_closed_gates import (
    build_degraded_state_fail_closed_gates_runtime,
)


def test_runtime_does_not_invoke_clock_at_build_time() -> None:
    calls = 0

    def clock() -> int:
        nonlocal calls
        calls += 1
        return 1

    build_degraded_state_fail_closed_gates_runtime(now_ms_clock=clock)
    assert calls == 0
