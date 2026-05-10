import v2.backend.app.services.degraded_state_fail_closed_gates as module


def test_public_surface() -> None:
    assert set(module.__all__) == {
        "DegradedStateFailClosedGatesServiceError",
        "assemble_degraded_state_record",
    }
