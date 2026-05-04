from v2.backend.app.adapters.redis_v2.url_env import read_v2_redis_url

import v2.backend.app.adapters.redis_v2 as _redis_v2_package

for _name in ("factory", "url_env"):
    if hasattr(_redis_v2_package, _name):
        delattr(_redis_v2_package, _name)

del _name
del _redis_v2_package

def test_url_env_reads_v2_redis_url_from_supplied_env() -> None:
    url = "redis://localhost:6379/0"

    assert read_v2_redis_url(env={"V2_REDIS_URL": url}) == url
