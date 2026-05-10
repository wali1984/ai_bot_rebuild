import sys


def test_provenance_service_does_not_import_redis() -> None:
    sys.modules.pop("redis", None)
    __import__("v2.backend.app.services.provenance_dedupe_attribution.provenance_service")
    assert "redis" not in sys.modules
