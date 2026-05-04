from v2.backend.app.adapters.redis_v2 import factory
from v2.backend.app.domain.trainer_liveness_observation_collector import (
    StreamLatestIdReader,
)


class FakeClient:
    def xrevrange(self, *args, **kwargs):
        return []


class FakeRedisClass:
    @classmethod
    def from_url(cls, url):
        return FakeClient()


class FakeModule:
    Redis = FakeRedisClass


def test_factory_returned_reader_satisfies_protocol(monkeypatch) -> None:
    monkeypatch.setattr(factory, "redis", FakeModule)

    reader = factory.make_real_redis_stream_latest_id_reader(
        url="redis://cache:6379/0",
    )

    assert isinstance(reader, StreamLatestIdReader)
