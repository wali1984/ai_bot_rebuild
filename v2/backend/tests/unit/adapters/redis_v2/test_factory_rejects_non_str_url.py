import pytest

from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError
from v2.backend.app.adapters.redis_v2.factory import (


    make_real_redis_stream_latest_id_reader,
)

import v2.backend.app.adapters.redis_v2 as _redis_v2_package

for _name in ("factory", "url_env"):
    if hasattr(_redis_v2_package, _name):
        delattr(_redis_v2_package, _name)

del _name
del _redis_v2_package

def test_factory_rejects_non_str_url() -> None:
    with pytest.raises(RedisStreamReaderError) as exc_info:
        make_real_redis_stream_latest_id_reader(url=123)

    assert exc_info.value.code == "must_be_str"
    assert exc_info.value.field == "url"
