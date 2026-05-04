from v2.backend.app.adapters.redis_v2 import factory


class FakeClient:
    def xrevrange(self, *args, **kwargs):
        raise AssertionError("must not be called")


class RecordingFromUrl:
    def __init__(self, calls):
        self._calls = calls

    def __call__(self, url):
        self._calls.append("Redis.from_url")
        return FakeClient()


class RecordingRedisClass:
    def __init__(self, calls):
        self.from_url = RecordingFromUrl(calls)


class RecordingModule:
    def __init__(self):
        self.calls = []
        self._klass = RecordingRedisClass(self.calls)

    def __getattribute__(self, name):
        if name in {"calls", "_klass", "__class__"}:
            return object.__getattribute__(self, name)
        if name == "Redis":
            object.__getattribute__(self, "calls").append(name)
            return object.__getattribute__(self, "_klass")
        raise AssertionError(name)


def test_factory_only_uses_redis_module_from_url(monkeypatch) -> None:
    module = RecordingModule()
    monkeypatch.setattr(factory, "redis", module)

    factory.make_real_redis_stream_latest_id_reader(url="redis://cache:6379/0")

    assert module.calls == ["Redis", "Redis.from_url"]
