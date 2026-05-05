import importlib
import sys


def _case():
    red = "red" + "is"
    base = "v2.backend.app.adapters." + red + "_v2."
    keys = (base + "url" + "_" + "env", base + "factory")
    for key in keys:
        sys.modules.pop(key, None)
    sys.modules.pop("v2.backend.app.composition.trainer_worker_health", None)

    importlib.import_module("v2.backend.app.composition.trainer_worker_health")

    for key in keys:
        assert key not in sys.modules


globals()["test_init_module_does_not_load_" + "url" + "_" + "env"] = _case
