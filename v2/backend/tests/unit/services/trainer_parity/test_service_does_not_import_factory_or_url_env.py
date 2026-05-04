def test_service_does_not_import_factory_or_url_env():
    import importlib
    import sys

    mod_a = "v2.backend.app.adapters." + "redis_v2." + "factory"
    mod_b = "v2.backend.app.adapters." + "redis_v2." + "url_env"
    root = "v2.backend.app.services.trainer_parity"
    sys.modules.pop("redis", None)
    sys.modules.pop(mod_a, None)
    sys.modules.pop(mod_b, None)
    sys.modules.pop(root, None)

    importlib.import_module(root)

    assert "redis" not in sys.modules
    assert mod_a not in sys.modules
    assert mod_b not in sys.modules
