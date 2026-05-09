import sys


def test_record_module_does_not_load_redis_when_imported() -> None:
    sys.modules.pop("redis", None)

    import v2.backend.app.domain.external_manual_position_quarantine.record  # noqa: F401

    assert "redis" not in sys.modules
