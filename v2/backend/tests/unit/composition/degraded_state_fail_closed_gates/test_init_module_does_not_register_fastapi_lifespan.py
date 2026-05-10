import v2.backend.app.composition.degraded_state_fail_closed_gates as module


def test_init_module_does_not_register_fastapi_lifespan() -> None:
    assert not hasattr(module, "lifespan")
