import sys


def test_runtime_module_does_not_load_redis_when_imported() -> None:
    sys.modules.pop("redis", None)
    __import__("v2.backend.app.composition.provenance_dedupe_attribution.runtime")
    assert "redis" not in sys.modules
