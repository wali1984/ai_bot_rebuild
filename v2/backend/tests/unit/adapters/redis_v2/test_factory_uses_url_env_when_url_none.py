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


def test_factory_uses_url_env_when_url_none(monkeypatch) -> None:
    FakeRedisClass.calls = []
    url = "redis://x:1"
    monkeypatch.setattr(factory, "redis", FakeModule)
    monkeypatch.setattr(factory, "read_v2_redis_url", lambda *, env=None: url)

    factory.make_real_redis_stream_latest_id_reader()

    assert FakeRedisClass.calls == [url]
