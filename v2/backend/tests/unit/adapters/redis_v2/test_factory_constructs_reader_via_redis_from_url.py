from v2.backend.app.adapters.redis_v2 import factory
from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (
    RedisStreamLatestIdReader,
)


class FakeClient:
    def xrevrange(self, *args, **kwargs):
        raise AssertionError("must not be called")


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
    monkeypatch.setattr(factory, "redis", FakeModule)
    url = "redis://localhost:6379/0"

    reader = factory.make_real_redis_stream_latest_id_reader(url=url)

    assert FakeRedisClass.calls == [url]
    assert isinstance(reader, RedisStreamLatestIdReader)
    assert reader._client is FakeRedisClass.client
