from __future__ import annotations

from v2.backend.app.domain.liveness_stream_growth import StreamIdObservation

from .errors import ObservationCollectorError


def extend_observation_history(
    history: tuple[StreamIdObservation, ...],
    new: tuple[StreamIdObservation, ...],
    *,
    max_total: int,
) -> tuple[StreamIdObservation, ...]:
    if not isinstance(history, tuple):
        raise ObservationCollectorError("must_be_tuple", field="history")

    if not isinstance(new, tuple):
        raise ObservationCollectorError("must_be_tuple", field="new")

    for observation in history:
        if not isinstance(observation, StreamIdObservation):
            raise ObservationCollectorError("must_be_stream_id_observation", field="history")

    for observation in new:
        if not isinstance(observation, StreamIdObservation):
            raise ObservationCollectorError("must_be_stream_id_observation", field="new")

    if type(max_total) is not int:
        raise ObservationCollectorError("must_be_int", field="max_total")

    if max_total < 1:
        raise ObservationCollectorError("must_be_positive", field="max_total")

    combined = history + new
    if len(combined) <= max_total:
        return combined
    return combined[-max_total:]
