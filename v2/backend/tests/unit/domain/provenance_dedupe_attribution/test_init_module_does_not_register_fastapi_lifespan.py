import v2.backend.app.domain.provenance_dedupe_attribution as module


def test_init_module_does_not_register_fastapi_lifespan() -> None:
    assert not hasattr(module, "lifespan")
