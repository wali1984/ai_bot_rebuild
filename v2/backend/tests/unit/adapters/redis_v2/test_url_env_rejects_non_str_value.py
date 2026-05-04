import pytest

from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError
from v2.backend.app.adapters.redis_v2.url_env import read_v2_redis_url


def test_url_env_rejects_non_str_value() -> None:
    for value in (123, b"redis://cache:6379/0"):
        with pytest.raises(RedisStreamReaderError) as exc_info:
            read_v2_redis_url(env={"V2_REDIS_URL": value})

        assert exc_info.value.code == "must_be_str"
        assert exc_info.value.field == "V2_REDIS_URL"
