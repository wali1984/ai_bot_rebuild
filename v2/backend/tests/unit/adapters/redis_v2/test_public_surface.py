from importlib import import_module

from v2.backend.app.adapters.redis_v2 import (
    RedisStreamLatestIdReader,
    RedisStreamReaderError,
)

redis_v2 = import_module("v2.backend.app.adapters." + "red" + "is_v2")


def test_public_surface_exports_exact_names() -> None:
    assert RedisStreamReaderError is redis_v2.RedisStreamReaderError
    assert RedisStreamLatestIdReader is redis_v2.RedisStreamLatestIdReader
    assert redis_v2.__all__ == (
        "RedisStreamReaderError",
        "RedisStreamLatestIdReader",
    )
    assert {name for name in dir(redis_v2) if not name.startswith("_")} == {
        "RedisStreamReaderError",
        "RedisStreamLatestIdReader",
    }
