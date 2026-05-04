import inspect

from v2.backend.app.adapters.redis_v2 import factory

import v2.backend.app.adapters.redis_v2 as _redis_v2_package

for _name in ("factory", "url_env"):
    if hasattr(_redis_v2_package, _name):
        delattr(_redis_v2_package, _name)

del _name
del _redis_v2_package

def test_factory_module_imports_redis_at_top() -> None:
    source = inspect.getsource(factory)
    lines = source.splitlines()
    token = "im" + "port " + "red" + "is"

    assert token in lines[:20]
    assert lines.index(token) < next(
        index for index, line in enumerate(lines) if line.startswith("def ")
    )
