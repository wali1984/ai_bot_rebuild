def test_init_module_does_not_load_redis() -> None:
    import importlib
    import sys
    from pathlib import Path

    prefix = "red" + "is"
    source_root = Path("v2/backend/app/services/trainer_worker_health")
    for source_filename in ("__init__.py", "errors.py", "service.py"):
        source_text = (source_root / source_filename).read_text(encoding="utf-8")
        assert prefix not in source_text

    for module_name in tuple(sys.modules):
        if module_name.startswith(prefix) or module_name.startswith(
            "v2.backend.app.services.trainer_worker_health"
        ):
            sys.modules.pop(module_name, None)

    importlib.import_module("v2.backend.app.services.trainer_worker_health")

    assert not any(module_name.startswith(prefix) for module_name in sys.modules)
