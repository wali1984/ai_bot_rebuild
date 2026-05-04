import pytest

from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError
from v2.backend.app.adapters.redis_v2.factory import (
    make_real_redis_stream_latest_id_reader,
)


def test_factory_rejects_empty_url() -> None:
    with pytest.raises(RedisStreamReaderError) as exc_info:
        make_real_redis_stream_latest_id_reader(url="")

    assert exc_info.value.code == "must_be_nonempty_str"
    assert exc_info.value.field == "url"
