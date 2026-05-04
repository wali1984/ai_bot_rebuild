from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (
    RedisStreamLatestIdReader,
)


class FakeClient:
    def __init__(self, result):
        self.calls = []
        self.result = result

    def xrevrange(self, stream_name: str, *, max: str, min: str, count: int):
        self.calls.append(("xrevrange", (stream_name,), {"max": max, "min": min, "count": count}))
        return self.result


def test_reader_does_not_mutate_inputs() -> None:
    stream_name = "s"
    result = [("1-0", {"k": "v"})]
    client = FakeClient(result)
    reader = RedisStreamLatestIdReader(client)

    assert reader.latest_stream_id(stream_name) == "1-0"
    assert stream_name == "s"
    assert result == [("1-0", {"k": "v"})]
    assert client.calls == [("xrevrange", ("s",), {"max": "+", "min": "-", "count": 1})]
    assert not hasattr(reader, "__dict__")
