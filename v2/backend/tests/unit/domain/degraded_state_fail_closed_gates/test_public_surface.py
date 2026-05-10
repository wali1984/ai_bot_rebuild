import v2.backend.app.domain.degraded_state_fail_closed_gates as module


def test_public_surface() -> None:
    assert set(module.__all__) == {
        "DEGRADED_SOURCE_MISSING",
        "DEGRADED_SOURCE_OK",
        "DEGRADED_SOURCE_STALE",
        "DEGRADED_SOURCE_UNUSED",
        "DegradedStateFailClosedGatesDomainError",
        "DegradedStateRecord",
    }
