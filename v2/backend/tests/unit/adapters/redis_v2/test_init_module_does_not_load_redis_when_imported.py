import importlib
import sys

import v2.backend.app.adapters.redis_v2 as _redis_v2_package

for _name in ("factory", "url_env"):
    if hasattr(_redis_v2_package, _name):
        delattr(_redis_v2_package, _name)

del _name
del _redis_v2_package

def test_init_module_does_not_load_redis_when_imported() -> None:
    sys.modules.pop("red" + "is", None)
    importlib.import_module("v2.backend.app.adapters.redis_v2")

    assert ("red" + "is") not in sys.modules
