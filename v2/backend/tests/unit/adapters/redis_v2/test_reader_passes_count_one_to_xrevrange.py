from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (
    RedisStreamLatestIdReader,
)


class FakeClient:
    def __init__(self):
        self.calls = []

    def xrevrange(self, stream_name: str, *, max: str, min: str, count: int):
        self.calls.append(("xrevrange", (stream_name,), {"max": max, "min": min, "count": count}))
        return [("1-0", {})]


def test_reader_passes_count_one_to_xrevrange() -> None:
    client = FakeClient()
    RedisStreamLatestIdReader(client).latest_stream_id("s")

    assert client.calls == [("xrevrange", ("s",), {"max": "+", "min": "-", "count": 1})]
