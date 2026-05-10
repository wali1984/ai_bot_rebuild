import v2.backend.app.composition.degraded_state_fail_closed_gates as module


def test_public_surface() -> None:
    assert set(module.__all__) == {
        "DegradedStateFailClosedGatesRuntime",
        "DegradedStateFailClosedGatesRuntimeCompositionError",
        "build_degraded_state_fail_closed_gates_runtime",
    }
