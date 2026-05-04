import inspect

from v2.backend.app.adapters.redis_v2 import factory


def test_factory_module_imports_redis_at_top() -> None:
    source = inspect.getsource(factory)
    lines = source.splitlines()
    token = "im" + "port " + "red" + "is"

    assert token in lines[:20]
    assert lines.index(token) < next(
        index for index, line in enumerate(lines) if line.startswith("def ")
    )
