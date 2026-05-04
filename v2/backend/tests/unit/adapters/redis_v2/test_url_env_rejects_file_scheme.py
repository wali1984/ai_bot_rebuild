import pytest

from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError
from v2.backend.app.adapters.redis_v2.url_env import read_v2_redis_url


def test_url_env_rejects_file_scheme() -> None:
    with pytest.raises(RedisStreamReaderError) as exc_info:
        read_v2_redis_url(env={"V2_REDIS_URL": "file:///tmp/socket"})

    assert exc_info.value.code == "must_use_allowed_scheme"
    assert exc_info.value.field == "V2_REDIS_URL"
