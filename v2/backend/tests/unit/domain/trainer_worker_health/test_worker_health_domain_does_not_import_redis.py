def test_worker_health_domain_does_not_import_redis() -> None:
    import importlib
    import inspect
    import sys

    module_names = (
        "v2.backend.app.domain.trainer_worker_health",
        "v2.backend.app.domain.trainer_worker_health.errors",
        "v2.backend.app.domain.trainer_worker_health.health_status",
        "v2.backend.app.domain.trainer_worker_health.health_thresholds",
        "v2.backend.app.domain.trainer_worker_health.health_snapshot",
        "v2.backend.app.domain.trainer_worker_health.health_evaluator",
    )
    forbidden = (
        "import " + "redis",
        "from " + "redis",
        "redis" + "." + "asyncio",
        "hire" + "dis",
        "aio" + "redis",
        "xrev" + "range",
        "x" + "add",
        "x" + "read",
        "x" + "len",
        "pipe" + "line",
        "ht" + "tpx",
        "re" + "quests",
    )
    for module_name in module_names:
        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
        for token in forbidden:
            assert token not in source

    sys.modules.pop("v2.backend.app.domain.trainer_worker_health", None)
    importlib.import_module("v2.backend.app.domain.trainer_worker_health")
    assert "redis" not in sys.modules
