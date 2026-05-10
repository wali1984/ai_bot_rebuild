import sys


def test_degraded_state_record_module_does_not_load_redis_when_imported() -> None:
    sys.modules.pop("redis", None)
    __import__(
        "v2.backend.app.domain.degraded_state_fail_closed_gates.degraded_state_record"
    )
    assert "redis" not in sys.modules
