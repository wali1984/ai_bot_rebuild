from v2.backend.app.adapters.redis_v2.url_env import read_v2_redis_url


def test_url_env_accepts_redis_scheme() -> None:
    url = "redis://cache:6379/1"

    assert read_v2_redis_url(env={"V2_REDIS_URL": url}) == url
