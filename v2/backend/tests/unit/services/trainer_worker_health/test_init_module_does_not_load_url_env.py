def test_init_module_does_not_load_url_env() -> None:
    import importlib
    import sys
    from pathlib import Path

    marker = "url" + "_env"
    source_root = Path("v2/backend/app/services/trainer_worker_health")
    for source_filename in ("__init__.py", "errors.py", "service.py"):
        source_text = (source_root / source_filename).read_text(encoding="utf-8")
        assert marker not in source_text

    blocked_prefix = "v2.backend.app.adapters." + "red" + "is_v2." + marker
    for module_name in tuple(sys.modules):
        if module_name.startswith(blocked_prefix) or module_name.startswith(
            "v2.backend.app.services.trainer_worker_health"
        ):
            sys.modules.pop(module_name, None)

    importlib.import_module("v2.backend.app.services.trainer_worker_health")

    assert not any(marker in module_name for module_name in sys.modules if module_name != __name__)
