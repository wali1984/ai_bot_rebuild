from v2.backend.app.adapters.redis_v2.url_env import read_v2_redis_url


def test_url_env_does_not_mutate_supplied_env() -> None:
    env = {"V2_REDIS_URL": "redis://cache:6379/0", "OTHER": "value"}
    before = dict(env)

    read_v2_redis_url(env=env)

    assert env == before
