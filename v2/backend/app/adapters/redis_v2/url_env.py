import os

from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError


def read_v2_redis_url(*, env: object | None = None) -> str:
    source = os.environ if env is None else env
    get = getattr(source, "get", None)
    if not callable(get):
        raise RedisStreamReaderError("must_expose_get", field="env")

    raw = get("V2_REDIS_URL")
    if raw is None:
        raise RedisStreamReaderError("must_be_set", field="V2_REDIS_URL")
    if not isinstance(raw, str):
        raise RedisStreamReaderError("must_be_str", field="V2_REDIS_URL")
    if raw == "":
        raise RedisStreamReaderError("must_be_nonempty", field="V2_REDIS_URL")
    if (
        not raw.startswith("redis://")
        and not raw.startswith("rediss://")
        and not raw.startswith("unix://")
    ):
        raise RedisStreamReaderError(
            "must_use_allowed_scheme",
            field="V2_REDIS_URL",
        )
    return raw
