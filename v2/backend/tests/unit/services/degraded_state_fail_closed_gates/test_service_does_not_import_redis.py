import sys


def test_service_does_not_import_redis() -> None:
    sys.modules.pop("redis", None)
    __import__("v2.backend.app.services.degraded_state_fail_closed_gates.service")
    assert "redis" not in sys.modules
