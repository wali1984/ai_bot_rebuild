from v2.backend.app.adapters.redis_v2 import factory
from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (


    RedisStreamLatestIdReader,
)

import v2.backend.app.adapters.redis_v2 as _redis_v2_package

for _name in ("factory", "url_env"):
    if hasattr(_redis_v2_package, _name):
        delattr(_redis_v2_package, _name)

del _name
del _redis_v2_package

class FakeClient:
    calls = []

    def xrevrange(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return [(b"123-0", {})]


class FakeRedisClass:
    calls = []
    client = FakeClient()

    @classmethod
    def from_url(cls, url):
        cls.calls.append(url)
        return cls.client


class FakeModule:
    Redis = FakeRedisClass


def test_factory_constructs_reader_via_redis_from_url(monkeypatch) -> None:
    FakeRedisClass.calls = []
    FakeRedisClass.client.calls = []
    monkeypatch.setattr(factory, "redis", FakeModule)
    url = "redis://localhost:6379/0"

    reader = factory.make_real_redis_stream_latest_id_reader(url=url)

    assert FakeRedisClass.calls == [url]
    assert isinstance(reader, RedisStreamLatestIdReader)
    assert reader._client is FakeRedisClass.client
    assert reader.latest_stream_id("some_stream") == "123-0"
    assert FakeRedisClass.client.calls == [
        (("some_stream",), {"max": "+", "min": "-", "count": 1})
    ]
