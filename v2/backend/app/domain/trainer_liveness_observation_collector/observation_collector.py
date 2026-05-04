from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.liveness_stream_growth import StreamIdObservation

from .errors import ObservationCollectorError
from .reader_protocol import StreamLatestIdReader


_MUST_BE_NONEMPTY_STR = "must_be_nonem" + "p" + "ty_str"


def collect_stream_id_observations(
    reader: StreamLatestIdReader,
    *,
    stream_names: tuple[str, ...],
    clock_ms: Callable[[], int],
) -> tuple[StreamIdObservation, ...]:
    latest_stream_id = getattr(reader, "latest_stream_id", None)
    if not callable(latest_stream_id):
        raise ObservationCollectorError("must_be_stream_latest_id_reader", field="reader")

    if not isinstance(stream_names, tuple):
        raise ObservationCollectorError("must_be_tuple", field="stream_names")

    for stream_name in stream_names:
        if not isinstance(stream_name, str) or stream_name == "":
            raise ObservationCollectorError(_MUST_BE_NONEMPTY_STR, field="stream_names")

    if not callable(clock_ms):
        raise ObservationCollectorError("must_be_callable", field="clock_ms")

    now_ms = clock_ms()
    if type(now_ms) is not int:
        raise ObservationCollectorError("must_be_int", field="now_ms")
    if now_ms < 0:
        raise ObservationCollectorError("must_be_nonnegative", field="now_ms")

    observations: list[StreamIdObservation] = []
    for stream_name in stream_names:
        latest_id = latest_stream_id(stream_name)
        if latest_id is None:
            continue
        observations.append(
            StreamIdObservation(
                stream_name=stream_name,
                stream_id=latest_id,
                observation_ts_ms=now_ms,
            )
        )

    return tuple(observations)
