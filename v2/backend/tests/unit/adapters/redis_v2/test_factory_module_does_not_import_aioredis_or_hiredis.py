import inspect

from v2.backend.app.adapters.redis_v2 import factory

import v2.backend.app.adapters.redis_v2 as _redis_v2_package

for _name in ("factory", "url_env"):
    if hasattr(_redis_v2_package, _name):
        delattr(_redis_v2_package, _name)

del _name
del _redis_v2_package

def test_factory_module_does_not_import_aioredis_or_hiredis() -> None:
    source = inspect.getsource(factory)
    tokens = [
        "aio" + "red" + "is",
        "red" + "is.asyncio",
        "hi" + "red" + "is",
    ]

    for token in tokens:
        assert token not in source
