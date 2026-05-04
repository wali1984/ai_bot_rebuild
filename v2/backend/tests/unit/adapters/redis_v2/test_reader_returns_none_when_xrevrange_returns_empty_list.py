from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (
    RedisStreamLatestIdReader,
)


class FakeClient:
    def __init__(self):
        self.calls = []

    def xrevrange(self, stream_name: str, *, max: str, min: str, count: int):
        self.calls.append(("xrevrange", (stream_name,), {"max": max, "min": min, "count": count}))
        return []


def test_reader_returns_none_when_xrevrange_returns_empty_list() -> None:
    client = FakeClient()

    assert RedisStreamLatestIdReader(client).latest_stream_id("s") is None
    assert len(client.calls) == 1
