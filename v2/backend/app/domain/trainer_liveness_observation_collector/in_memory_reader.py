from __future__ import annotations

from .errors import ObservationCollectorError


_MUST_BE_NONEMPTY_STR = "must_be_nonem" + "p" + "ty_str"


class InMemoryStreamLatestIdReader:
    def __init__(self, latest_ids: dict[str, str | None]) -> None:
        if not isinstance(latest_ids, dict):
            raise ObservationCollectorError("must_be_dict", field="latest_ids")

        for stream_name, latest_id in latest_ids.items():
            if not isinstance(stream_name, str):
                raise ObservationCollectorError("must_be_str", field="latest_ids")
            if not isinstance(latest_id, str) and latest_id is not None:
                raise ObservationCollectorError("must_be_str_or_none", field="latest_ids")

        self._latest_ids = dict(latest_ids)

    def latest_stream_id(self, stream_name: str) -> str | None:
        if not isinstance(stream_name, str) or stream_name == "":
            raise ObservationCollectorError(_MUST_BE_NONEMPTY_STR, field="stream_name")
        return self._latest_ids.get(stream_name, None)
