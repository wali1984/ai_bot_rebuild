from __future__ import annotations

from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError


class RedisStreamLatestIdReader:
    __slots__ = ("_client",)

    def __init__(self, redis_client: object) -> None:
        xrevrange = getattr(redis_client, "xrevrange", None)
        if not callable(xrevrange):
            raise RedisStreamReaderError(
                "must_expose_xrevrange",
                field="redis_client",
            )
        self._client = redis_client

    def latest_stream_id(self, stream_name: str) -> str | None:
        if not isinstance(stream_name, str) or stream_name == "":
            raise RedisStreamReaderError(
                "must_be_nonempty_str",
                field="stream_name",
            )

        result = self._client.xrevrange(stream_name, max="+", min="-", count=1)

        if not result:
            return None
        if not isinstance(result, (list, tuple)):
            raise RedisStreamReaderError(
                "xrevrange_returned_unexpected_type",
                field="result",
            )

        first = result[0]
        if not isinstance(first, (list, tuple)) or len(first) < 1:
            raise RedisStreamReaderError(
                "xrevrange_entry_malformed",
                field="result",
            )

        raw_id = first[0]
        if isinstance(raw_id, bytes):
            return raw_id.decode("ascii")
        if isinstance(raw_id, str):
            return raw_id
        raise RedisStreamReaderError(
            "xrevrange_entry_id_not_str_or_bytes",
            field="result",
        )
