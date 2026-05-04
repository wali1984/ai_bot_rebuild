from v2.backend.app.adapters.redis_v2 import factory

import v2.backend.app.adapters.redis_v2 as _redis_v2_package

for _name in ("factory", "url_env"):
    if hasattr(_redis_v2_package, _name):
        delattr(_redis_v2_package, _name)

del _name
del _redis_v2_package

class FakeClient:
    def xrevrange(self, *args, **kwargs):
        raise AssertionError("must not be called")


class FakeRedisClass:
    calls = []

    @classmethod
    def from_url(cls, url):
        cls.calls.append(url)
        return FakeClient()


class FakeModule:
    Redis = FakeRedisClass


def test_factory_uses_url_env_when_url_none(monkeypatch) -> None:
    FakeRedisClass.calls = []
    url = "redis://x:1"
    monkeypatch.setattr(factory, "redis", FakeModule)
    monkeypatch.setattr(factory, "read_v2_redis_url", lambda *, env=None: url)

    factory.make_real_redis_stream_latest_id_reader()

    assert FakeRedisClass.calls == [url]
