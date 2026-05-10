import pytest

from v2.backend.app.composition.degraded_state_fail_closed_gates import (
    DegradedStateFailClosedGatesRuntimeCompositionError,
    build_degraded_state_fail_closed_gates_runtime,
)


def test_runtime_validates_now_ms_clock() -> None:
    with pytest.raises(DegradedStateFailClosedGatesRuntimeCompositionError):
        build_degraded_state_fail_closed_gates_runtime(now_ms_clock=1)  # type: ignore[arg-type]
