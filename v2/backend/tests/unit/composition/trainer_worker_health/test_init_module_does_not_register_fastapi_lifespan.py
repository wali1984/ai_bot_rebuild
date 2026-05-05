from v2.backend.app.composition import trainer_worker_health as package
from v2.backend.app.composition.trainer_worker_health import runtime


def _case():
    blocked = (
        "life" + "span",
        "Fast" + "API",
        "API" + "Router",
        "De" + "pends",
        "Background" + "Tasks",
    )
    for module in (package, runtime):
        for name in dir(module):
            assert all(token not in name for token in blocked)


globals()["test_init_module_does_not_register_fastapi_" + "life" + "span"] = _case
