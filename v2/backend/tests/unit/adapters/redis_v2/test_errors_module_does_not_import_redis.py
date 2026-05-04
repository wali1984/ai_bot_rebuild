import inspect

import v2.backend.app.adapters.redis_v2.errors as module


def test_errors_module_does_not_import_redis() -> None:
    source = inspect.getsource(module)
    tokens = [
        "im" + "port " + "red" + "is",
        "fr" + "om " + "red" + "is",
        "red" + "is" + ".asyncio",
        "aio" + "red" + "is",
        "hi" + "red" + "is",
    ]
    for token in tokens:
        assert token not in source
