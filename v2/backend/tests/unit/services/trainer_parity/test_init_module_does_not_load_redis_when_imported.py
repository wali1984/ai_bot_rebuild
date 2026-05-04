def test_init_module_does_not_load_redis_when_imported():
    import importlib
    import sys

    sys.modules.pop("redis", None)
    sys.modules.pop("v2.backend.app.services.trainer_parity", None)

    importlib.import_module("v2.backend.app.services.trainer_parity")

    assert "redis" not in sys.modules
