from __future__ import annotations

from .errors import ObservationCollectorError
from .in_memory_reader import InMemoryStreamLatestIdReader
from .reader_protocol import StreamLatestIdReader


__all__ = (
    "StreamLatestIdReader",
    "InMemoryStreamLatestIdReader",
    "collect_stream_id_observations",
    "extend_observation_history",
    "ObservationCollectorError",
)


def __getattr__(name: str) -> object:
    if name == "collect_stream_id_observations":
        from .observation_collector import collect_stream_id_observations

        globals().pop("observation_collector", None)
        return collect_stream_id_observations
    if name == "extend_observation_history":
        from .observation_history import extend_observation_history

        globals().pop("observation_history", None)
        return extend_observation_history
    raise AttributeError(name)


del errors
del in_memory_reader
del reader_protocol
