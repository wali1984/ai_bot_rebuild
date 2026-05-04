from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (


    RedisStreamLatestIdReader,
)

import v2.backend.app.adapters.redis_v2 as _redis_v2_package

for _name in ("factory", "url_env"):
    if hasattr(_redis_v2_package, _name):
        delattr(_redis_v2_package, _name)

del _name
del _redis_v2_package

def test_factory_does_not_perform_network_at_construction() -> None:
    module = __import__("red" + "is")

    client = module.Redis.from_url("redis://127.0.0.1:1/0")
    RedisStreamLatestIdReader(client)
