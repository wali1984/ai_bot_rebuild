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


def test_factory_passes_explicit_url_verbatim(monkeypatch) -> None:
    FakeRedisClass.calls = []
    url = "rediss://example:6380/2"
    monkeypatch.setattr(factory, "redis", FakeModule)

    def fail_env_lookup(*, env=None):
        raise AssertionError("env helper should not run")

    monkeypatch.setattr(factory, "read_v2_redis_url", fail_env_lookup)

    factory.make_real_redis_stream_latest_id_reader(url=url)

    assert FakeRedisClass.calls == [url]
