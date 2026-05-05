def test_init_module_does_not_load_url_env() -> None:
    import importlib
    import sys

    marker = "url" + "_env"
    blocked_prefix = "v2.backend.app.adapters." + "red" + "is_v2." + marker
    for module_name in tuple(sys.modules):
        if module_name.startswith(blocked_prefix) or module_name.startswith(
            "v2.backend.app.services.trainer_worker_health"
        ):
            del sys.modules[module_name]

    importlib.import_module("v2.backend.app.services.trainer_worker_health")

    assert not any(marker in module_name for module_name in sys.modules if module_name != __name__)
