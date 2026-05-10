import sys


def test_dedupe_service_does_not_import_redis() -> None:
    sys.modules.pop("redis", None)
    __import__("v2.backend.app.services.provenance_dedupe_attribution.dedupe_service")
    assert "redis" not in sys.modules
