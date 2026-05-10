import sys


def test_dedupe_decision_record_module_does_not_load_redis_when_imported() -> None:
    sys.modules.pop("redis", None)
    __import__("v2.backend.app.domain.provenance_dedupe_attribution.dedupe_decision_record")
    assert "redis" not in sys.modules
