import pytest

from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError
from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (
    RedisStreamLatestIdReader,
)


class FakeClient:
    def xrevrange(self, stream_name: str, *, max: str, min: str, count: int):
        return [()]


def test_reader_raises_on_xrevrange_entry_malformed() -> None:
    with pytest.raises(RedisStreamReaderError) as raised:
        RedisStreamLatestIdReader(FakeClient()).latest_stream_id("s")

    assert raised.value.code == "xrevrange_entry_malformed"
    assert raised.value.field == "result"
