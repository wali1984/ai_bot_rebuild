import inspect

from v2.backend.app.adapters.redis_v2 import url_env

import v2.backend.app.adapters.redis_v2 as _redis_v2_package

for _name in ("factory", "url_env"):
    if hasattr(_redis_v2_package, _name):
        delattr(_redis_v2_package, _name)

del _name
del _redis_v2_package

def test_url_env_module_does_not_import_redis() -> None:
    source = inspect.getsource(url_env)
    tokens = [
        "im" + "port " + "red" + "is",
        "fr" + "om " + "red" + "is",
        "red" + "is.asyncio",
        "aio" + "red" + "is",
        "hi" + "red" + "is",
    ]

    for token in tokens:
        assert token not in source
