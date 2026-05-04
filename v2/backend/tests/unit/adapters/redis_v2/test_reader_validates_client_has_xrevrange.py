import pytest

from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError
from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (
    RedisStreamLatestIdReader,
)


def test_reader_validates_client_has_xrevrange() -> None:
    with pytest.raises(RedisStreamReaderError) as raised:
        RedisStreamLatestIdReader(object())

    assert raised.value.code == "must_expose_xrevrange"
    assert raised.value.field == "redis_client"
    assert str(raised.value) == "must_expose_xrevrange (redis_client)"
