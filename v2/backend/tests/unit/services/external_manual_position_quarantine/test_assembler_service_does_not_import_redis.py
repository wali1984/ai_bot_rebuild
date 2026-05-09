import sys


def test_assembler_service_does_not_import_redis() -> None:
    sys.modules.pop("redis", None)

    import v2.backend.app.services.external_manual_position_quarantine.service  # noqa: F401

    assert "redis" not in sys.modules
