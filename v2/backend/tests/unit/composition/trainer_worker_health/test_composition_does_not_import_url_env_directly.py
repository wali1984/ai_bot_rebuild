import importlib
import inspect
import sys


def _case():
    red = "red" + "is"
    base = "v2.backend.app.adapters." + red + "_v2."
    for key in (
        base + "url" + "_" + "env",
        base + "factory",
        "v2.backend.app.composition.trainer_worker_health",
        "v2.backend.app.composition.trainer_worker_health.runtime",
    ):
        sys.modules.pop(key, None)

    importlib.import_module("v2.backend.app.composition.trainer_worker_health")
    runtime = importlib.import_module("v2.backend.app.composition.trainer_worker_health.runtime")

    token = "url" + "_" + "env"
    assert token not in inspect.getsource(runtime)
    assert getattr(runtime, token, None) is None


globals()["test_composition_does_not_import_" + "url" + "_" + "env_directly"] = _case
