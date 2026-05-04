from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (
    RedisStreamLatestIdReader,
)


class FakeClient:
    def __init__(self):
        self.calls = []

    def xrevrange(self, stream_name: str, *, max: str, min: str, count: int):
        self.calls.append(("xrevrange", (stream_name,), {"max": max, "min": min, "count": count}))
        return [("1700000000000-0", {"k": "v"})]


def test_reader_returns_str_id_when_xrevrange_returns_str() -> None:
    assert RedisStreamLatestIdReader(FakeClient()).latest_stream_id("s") == "1700000000000-0"
