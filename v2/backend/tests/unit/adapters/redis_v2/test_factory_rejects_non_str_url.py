import pytest

from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError
from v2.backend.app.adapters.redis_v2.factory import (
    make_real_redis_stream_latest_id_reader,
)


def test_factory_rejects_non_str_url() -> None:
    with pytest.raises(RedisStreamReaderError) as exc_info:
        make_real_redis_stream_latest_id_reader(url=123)

    assert exc_info.value.code == "must_be_str"
    assert exc_info.value.field == "url"
