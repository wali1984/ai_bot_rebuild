def test_init_module_does_not_load_redis() -> None:
    import importlib
    import sys

    prefix = "red" + "is"
    for module_name in tuple(sys.modules):
        if module_name.startswith(prefix) or module_name.startswith(
            "v2.backend.app.services.trainer_worker_health"
        ):
            del sys.modules[module_name]

    importlib.import_module("v2.backend.app.services.trainer_worker_health")

    assert not any(module_name.startswith(prefix) for module_name in sys.modules)
