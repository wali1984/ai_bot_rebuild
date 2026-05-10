import v2.backend.app.services.provenance_dedupe_attribution.dedupe_service as module


def test_dedupe_service_does_not_register_fastapi_lifespan() -> None:
    assert not hasattr(module, "lifespan")
