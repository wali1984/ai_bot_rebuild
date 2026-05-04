from __future__ import annotations

from .errors import LivenessStreamGrowthDomainError
from .growth_window_config import GrowthWindowConfig
from .stream_observation import StreamIdObservation, _ensure_stream_name


def compute_stream_id_growth_in_window(
    observations: tuple[StreamIdObservation, ...],
    config: GrowthWindowConfig,
    now_ms: int,
    *,
    stream_name: str,
) -> int:
    if not isinstance(observations, tuple):
        raise LivenessStreamGrowthDomainError("observations_not_tuple", field="observations")
    if not isinstance(config, GrowthWindowConfig):
        raise LivenessStreamGrowthDomainError("must_be_growth_window_config", field="config")
    if type(now_ms) is not int:
        raise LivenessStreamGrowthDomainError("must_be_int", field="now_ms")
    if now_ms < 0:
        raise LivenessStreamGrowthDomainError("must_be_nonnegative", field="now_ms")
    _ensure_stream_name(stream_name, field="stream_name")

    lo = now_ms - config.window_ms
    distinct_stream_ids: set[str] = set()

    for observation in observations:
        if not isinstance(observation, StreamIdObservation):
            raise LivenessStreamGrowthDomainError("must_be_stream_id_observation", field="observations")
        # A future observation invalidates the entire supplied window before stream filtering.
        if observation.observation_ts_ms > now_ms:
            raise LivenessStreamGrowthDomainError("observation_in_future", field="observation_ts_ms")
        if observation.stream_name != stream_name:
            continue
        if config.boundary_inclusive:
            in_window = observation.observation_ts_ms >= lo
        else:
            in_window = observation.observation_ts_ms > lo
        if in_window:
            # Redis stream IDs are counted as literal observed IDs, not normalized numeric offsets.
            distinct_stream_ids.add(observation.stream_id)

    return len(distinct_stream_ids)
