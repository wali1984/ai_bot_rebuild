import pytest

from v2.backend.app.composition.degraded_state_fail_closed_gates import (
    build_degraded_state_fail_closed_gates_runtime,
)


def test_runtime_degraded_state_now_keyword_only_params() -> None:
    runtime = build_degraded_state_fail_closed_gates_runtime(now_ms_clock=lambda: 1)
    with pytest.raises(TypeError):
        runtime.degraded_state_now(object())  # type: ignore[misc]
