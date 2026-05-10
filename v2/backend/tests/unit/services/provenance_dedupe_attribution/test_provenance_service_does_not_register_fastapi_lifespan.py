import v2.backend.app.services.provenance_dedupe_attribution.provenance_service as module


def test_provenance_service_does_not_register_fastapi_lifespan() -> None:
    assert not hasattr(module, "lifespan")
