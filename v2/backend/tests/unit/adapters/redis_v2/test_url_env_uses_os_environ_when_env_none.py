from v2.backend.app.adapters.redis_v2.url_env import read_v2_redis_url


def test_url_env_uses_os_environ_when_env_none(monkeypatch) -> None:
    url = "redis://env-cache:6379/0"
    monkeypatch.setenv("V2_REDIS_URL", url)

    assert read_v2_redis_url() == url
