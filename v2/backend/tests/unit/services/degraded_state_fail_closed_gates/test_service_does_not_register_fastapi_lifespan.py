import v2.backend.app.services.degraded_state_fail_closed_gates.service as module


def test_service_does_not_register_fastapi_lifespan() -> None:
    assert not hasattr(module, "lifespan")
