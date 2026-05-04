from v2.backend.app.adapters.redis_v2 import factory
from v2.backend.app.domain.trainer_liveness_observation_collector import (


    StreamLatestIdReader,
)

import v2.backend.app.adapters.redis_v2 as _redis_v2_package

for _name in ("factory", "url_env"):
    if hasattr(_redis_v2_package, _name):
        delattr(_redis_v2_package, _name)

del _name
del _redis_v2_package

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
