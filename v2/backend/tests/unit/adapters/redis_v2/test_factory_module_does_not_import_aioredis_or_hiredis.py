import inspect

from v2.backend.app.adapters.redis_v2 import factory


def test_factory_module_does_not_import_aioredis_or_hiredis() -> None:
    source = inspect.getsource(factory)
    tokens = [
        "aio" + "red" + "is",
        "red" + "is.asyncio",
        "hi" + "red" + "is",
    ]

    for token in tokens:
        assert token not in source
