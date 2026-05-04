from v2.backend.app.adapters.redis_v2.url_env import read_v2_redis_url


def test_url_env_reads_v2_redis_url_from_supplied_env() -> None:
    url = "redis://localhost:6379/0"

    assert read_v2_redis_url(env={"V2_REDIS_URL": url}) == url
