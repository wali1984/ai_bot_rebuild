import pytest

from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError
from v2.backend.app.adapters.redis_v2.url_env import read_v2_redis_url

import v2.backend.app.adapters.redis_v2 as _redis_v2_package

for _name in ("factory", "url_env"):
    if hasattr(_redis_v2_package, _name):
        delattr(_redis_v2_package, _name)

del _name
del _redis_v2_package

class NoGetter:
    pass


def test_url_env_rejects_env_without_get() -> None:
    with pytest.raises(RedisStreamReaderError) as exc_info:
        read_v2_redis_url(env=NoGetter())

    assert exc_info.value.code == "must_expose_get"
    assert exc_info.value.field == "env"
