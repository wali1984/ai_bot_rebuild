from __future__ import annotations

import redis

from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError
from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (
    RedisStreamLatestIdReader,
)
from v2.backend.app.adapters.redis_v2.url_env import read_v2_redis_url


def make_real_redis_stream_latest_id_reader(
    *,
    url: str | None = None,
    env: object | None = None,
) -> RedisStreamLatestIdReader:
    if url is None:
        url = read_v2_redis_url(env=env)
    if not isinstance(url, str):
        raise RedisStreamReaderError("must_be_str", field="url")
    if url == "":
        raise RedisStreamReaderError("must_be_nonempty_str", field="url")

    client = redis.Redis.from_url(url)
    return RedisStreamLatestIdReader(client)
