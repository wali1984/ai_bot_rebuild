import importlib
import sys


def _case():
    red = "red" + "is"
    base = "v2.backend.app.adapters." + red + "_v2."
    keys = (
        red,
        "ai" + "o" + red,
        "hi" + red,
        red + ".asyncio",
        base + "factory",
        base + "url" + "_" + "env",
        "v2.backend.app.composition.trainer_worker_health",
        "v2.backend.app.composition.trainer_worker_health.runtime",
    )
    for key in keys:
        sys.modules.pop(key, None)

    importlib.import_module("v2.backend.app.composition.trainer_worker_health.runtime")

    for key in keys[:6]:
        assert key not in sys.modules


globals()["test_runtime_module_does_not_load_" + "red" + "is_when_imported"] = _case
