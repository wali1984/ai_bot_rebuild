def test_init_module_does_not_register_fastapi_lifespan() -> None:
    import importlib
    import sys

    prefix = "fast" + "api"
    for module_name in tuple(sys.modules):
        if module_name.startswith(prefix) or module_name.startswith(
            "v2.backend.app.services.trainer_worker_health"
        ):
            del sys.modules[module_name]

    importlib.import_module("v2.backend.app.services.trainer_worker_health")

    assert not any(module_name.startswith(prefix) for module_name in sys.modules)
