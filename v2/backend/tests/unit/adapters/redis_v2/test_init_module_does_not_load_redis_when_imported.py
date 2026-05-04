import importlib
import sys


def test_init_module_does_not_load_redis_when_imported() -> None:
    sys.modules.pop("red" + "is", None)
    importlib.import_module("v2.backend.app.adapters.redis_v2")

    assert ("red" + "is") not in sys.modules
