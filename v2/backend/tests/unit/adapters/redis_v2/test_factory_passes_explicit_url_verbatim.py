from v2.backend.app.adapters.redis_v2 import factory


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
