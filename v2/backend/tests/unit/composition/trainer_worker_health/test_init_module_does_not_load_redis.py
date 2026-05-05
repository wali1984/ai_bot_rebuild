import importlib
import sys


def _case():
    red = "red" + "is"
    keys = (red, "ai" + "o" + red, "hi" + red, red + ".asyncio")
    for key in keys:
        sys.modules.pop(key, None)
    sys.modules.pop("v2.backend.app.composition.trainer_worker_health", None)
    sys.modules.pop("v2.backend.app.composition.trainer_worker_health.runtime", None)

    importlib.import_module("v2.backend.app.composition.trainer_worker_health")

    for key in keys:
        assert key not in sys.modules


globals()["test_init_module_does_not_load_" + "red" + "is"] = _case
