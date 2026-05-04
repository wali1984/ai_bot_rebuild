import inspect

from v2.backend.app.adapters.redis_v2 import url_env


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
