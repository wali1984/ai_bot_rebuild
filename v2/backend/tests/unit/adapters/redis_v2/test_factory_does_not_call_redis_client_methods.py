from v2.backend.app.adapters.redis_v2 import factory


class RecordingClient:
    def __init__(self) -> None:
        self.seen = []

    def __getattribute__(self, name):
        if name in {"seen", "__class__"}:
            return object.__getattribute__(self, name)
        object.__getattribute__(self, "seen").append(name)
        return object.__getattribute__(self, name)

    def xrevrange(self, *args, **kwargs):
        raise AssertionError("must not be called")


class FakeRedisClass:
    client = RecordingClient()

    @classmethod
    def from_url(cls, url):
        return cls.client


class FakeModule:
    Redis = FakeRedisClass


def test_factory_does_not_call_redis_client_methods(monkeypatch) -> None:
    FakeRedisClass.client = RecordingClient()
    monkeypatch.setattr(factory, "redis", FakeModule)

    factory.make_real_redis_stream_latest_id_reader(url="redis://cache:6379/0")

    assert FakeRedisClass.client.seen == ["xrevrange"]
