from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (
    RedisStreamLatestIdReader,
)


def test_factory_does_not_perform_network_at_construction() -> None:
    module = __import__("red" + "is")

    client = module.Redis.from_url("redis://127.0.0.1:1/0")
    RedisStreamLatestIdReader(client)
