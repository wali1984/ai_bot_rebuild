import sys


def test_runtime_module_does_not_load_redis_when_imported() -> None:
    sys.modules.pop("redis", None)

    import v2.backend.app.composition.external_manual_position_quarantine.runtime  # noqa: F401

    assert "redis" not in sys.modules
