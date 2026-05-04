import pytest

from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError
from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (
    RedisStreamLatestIdReader,
)


class FakeClient:
    def xrevrange(self, stream_name: str, *, max: str, min: str, count: int):
        raise AssertionError("xrevrange must not be called")


def test_reader_validates_stream_name_nonempty() -> None:
    reader = RedisStreamLatestIdReader(FakeClient())

    with pytest.raises(RedisStreamReaderError) as raised:
        reader.latest_stream_id("")

    assert raised.value.code == "must_be_nonempty_str"
    assert raised.value.field == "stream_name"
