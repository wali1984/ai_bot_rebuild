def test_worker_health_domain_does_not_import_url_env() -> None:
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
        "from v2.backend.app." + "adapters",
        "url" + "_env",
        "os" + "." + "environ",
        "sub" + "process",
        "socket" + "." + "socket",
        "time" + "." + "time(",
        "time" + "." + "monotonic(",
        "datetime" + "." + "now(",
        "datetime" + "." + "utcnow(",
        "pri" + "nt(",
        "logging" + ".",
        "from v2.backend.app." + "services",
        "from v2.backend.app." + "composition",
        "from v2.backend.app." + "adapters" + "." + "redis_v2",
    )
    for module_name in module_names:
        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
        for token in forbidden:
            assert token not in source

    sys.modules.pop("v2.backend.app.domain.trainer_worker_health", None)
    importlib.import_module("v2.backend.app.domain.trainer_worker_health")
    assert "v2.backend.app.adapters.redis_v2.url_env" not in sys.modules
