from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (
    RedisStreamLatestIdReader,
)


class FakeClient:
    def __init__(self):
        self.calls = []

    def xrevrange(self, stream_name: str, *, max: str, min: str, count: int):
        self.calls.append(("xrevrange", (stream_name,), {"max": max, "min": min, "count": count}))
        return [("1-0", {})]

    def __getattr__(self, name: str):
        def recorder(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return None

        return recorder


def test_reader_does_not_call_any_other_method() -> None:
    client = FakeClient()
    RedisStreamLatestIdReader(client).latest_stream_id("s")

    assert [call[0] for call in client.calls] == ["xrevrange"]
