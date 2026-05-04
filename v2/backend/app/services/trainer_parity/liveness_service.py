from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.liveness_stream_growth import (
    GrowthWindowConfig,
    StreamIdObservation,
)
from v2.backend.app.domain.trainer_liveness_composition import (
    LivenessSnapshotBaseInputs,
    compose_liveness_snapshot_with_growth,
)
from v2.backend.app.domain.trainer_liveness_observation_collector import (
    StreamLatestIdReader,
    collect_stream_id_observations,
    extend_observation_history,
)

from .errors import TrainerParityServiceError
from .evaluation import TrainerLivenessEvaluation


def evaluate_trainer_liveness(
    reader: StreamLatestIdReader,
    *,
    base_inputs: LivenessSnapshotBaseInputs,
    prediction_history: tuple[StreamIdObservation, ...],
    proposal_history: tuple[StreamIdObservation, ...],
    growth_config: GrowthWindowConfig,
    now_ms_clock: Callable[[], int],
    prediction_stream_name: str,
    proposal_stream_name: str,
    max_history_per_stream: int,
) -> TrainerLivenessEvaluation:
    latest_stream_id = getattr(reader, "latest_stream_id", None)
    if not callable(latest_stream_id):
        raise TrainerParityServiceError("must_be_stream_latest_id_reader", field="reader")

    if not isinstance(base_inputs, LivenessSnapshotBaseInputs):
        raise TrainerParityServiceError("must_be_liveness_snapshot_base_inputs", field="base_inputs")

    if not isinstance(prediction_history, tuple):
        raise TrainerParityServiceError("must_be_tuple", field="prediction_history")

    if not isinstance(proposal_history, tuple):
        raise TrainerParityServiceError("must_be_tuple", field="proposal_history")

    for observation in prediction_history:
        if not isinstance(observation, StreamIdObservation):
            raise TrainerParityServiceError("must_be_stream_id_observation", field="prediction_history")

    for observation in proposal_history:
        if not isinstance(observation, StreamIdObservation):
            raise TrainerParityServiceError("must_be_stream_id_observation", field="proposal_history")

    if not isinstance(growth_config, GrowthWindowConfig):
        raise TrainerParityServiceError("must_be_growth_window_config", field="growth_config")

    if not callable(now_ms_clock):
        raise TrainerParityServiceError("must_be_callable", field="now_ms_clock")

    if not isinstance(prediction_stream_name, str) or prediction_stream_name == "":
        raise TrainerParityServiceError("must_be_nonempty_str", field="prediction_stream_name")

    if not isinstance(proposal_stream_name, str) or proposal_stream_name == "":
        raise TrainerParityServiceError("must_be_nonempty_str", field="proposal_stream_name")

    if prediction_stream_name == proposal_stream_name:
        raise TrainerParityServiceError("stream_names_must_differ", field="proposal_stream_name")

    if type(max_history_per_stream) is not int:
        raise TrainerParityServiceError("must_be_int", field="max_history_per_stream")

    if max_history_per_stream < 1:
        raise TrainerParityServiceError("must_be_positive", field="max_history_per_stream")

    now_ms = now_ms_clock()
    if type(now_ms) is not int:
        raise TrainerParityServiceError("must_be_int", field="now_ms_clock")
    if now_ms < 0:
        raise TrainerParityServiceError("must_be_nonnegative", field="now_ms_clock")

    def cached_clock() -> int:
        return now_ms

    fresh = collect_stream_id_observations(
        reader,
        stream_names=(prediction_stream_name, proposal_stream_name),
        clock_ms=cached_clock,
    )
    fresh_prediction = tuple(o for o in fresh if o.stream_name == prediction_stream_name)
    fresh_proposal = tuple(o for o in fresh if o.stream_name == proposal_stream_name)
    new_prediction_history = extend_observation_history(
        prediction_history,
        fresh_prediction,
        max_total=max_history_per_stream,
    )
    new_proposal_history = extend_observation_history(
        proposal_history,
        fresh_proposal,
        max_total=max_history_per_stream,
    )
    snapshot = compose_liveness_snapshot_with_growth(
        base_inputs,
        prediction_observations=new_prediction_history,
        proposal_observations=new_proposal_history,
        growth_config=growth_config,
        now_ms=now_ms,
        prediction_stream_name=prediction_stream_name,
        proposal_stream_name=proposal_stream_name,
    )
    return TrainerLivenessEvaluation(
        snapshot=snapshot,
        prediction_history=new_prediction_history,
        proposal_history=new_proposal_history,
    )
