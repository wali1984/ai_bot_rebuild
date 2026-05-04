from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.adapters.redis_v2.factory import make_real_redis_stream_latest_id_reader
from v2.backend.app.domain.liveness_stream_growth import (
    GrowthWindowConfig,
    StreamIdObservation,
)
from v2.backend.app.domain.trainer_liveness_composition import (
    LivenessSnapshotBaseInputs,
)
from v2.backend.app.services.trainer_parity import (
    TrainerLivenessEvaluation,
    evaluate_trainer_liveness,
)

from .errors import TrainerParityCompositionError


TrainerLivenessEvaluator = Callable[
    [tuple[StreamIdObservation, ...], tuple[StreamIdObservation, ...]],
    TrainerLivenessEvaluation,
]


def build_trainer_liveness_evaluator(
    *,
    base_inputs: LivenessSnapshotBaseInputs,
    growth_config: GrowthWindowConfig,
    now_ms_clock: Callable[[], int],
    prediction_stream_name: str,
    proposal_stream_name: str,
    max_history_per_stream: int,
    env: object | None = None,
    url: str | None = None,
) -> TrainerLivenessEvaluator:
    if not isinstance(base_inputs, LivenessSnapshotBaseInputs):
        raise TrainerParityCompositionError(
            "must_be_liveness_snapshot_base_inputs",
            field="base_inputs",
        )
    if not isinstance(growth_config, GrowthWindowConfig):
        raise TrainerParityCompositionError(
            "must_be_growth_window_config",
            field="growth_config",
        )
    if not callable(now_ms_clock):
        raise TrainerParityCompositionError("must_be_callable", field="now_ms_clock")
    if not isinstance(prediction_stream_name, str) or prediction_stream_name == "":
        raise TrainerParityCompositionError(
            "must_be_nonempty_str",
            field="prediction_stream_name",
        )
    if not isinstance(proposal_stream_name, str) or proposal_stream_name == "":
        raise TrainerParityCompositionError(
            "must_be_nonempty_str",
            field="proposal_stream_name",
        )
    if prediction_stream_name == proposal_stream_name:
        raise TrainerParityCompositionError(
            "stream_names_must_differ",
            field="proposal_stream_name",
        )
    if type(max_history_per_stream) is not int:
        raise TrainerParityCompositionError("must_be_int", field="max_history_per_stream")
    if max_history_per_stream < 1:
        raise TrainerParityCompositionError(
            "must_be_positive",
            field="max_history_per_stream",
        )

    reader = make_real_redis_stream_latest_id_reader(url=url, env=env)

    _base_inputs = base_inputs
    _growth_config = growth_config
    _now_ms_clock = now_ms_clock
    _prediction_stream_name = prediction_stream_name
    _proposal_stream_name = proposal_stream_name
    _max_history_per_stream = max_history_per_stream
    _reader = reader

    def _evaluator(
        prediction_history: tuple[StreamIdObservation, ...],
        proposal_history: tuple[StreamIdObservation, ...],
    ) -> TrainerLivenessEvaluation:
        return evaluate_trainer_liveness(
            _reader,
            base_inputs=_base_inputs,
            prediction_history=prediction_history,
            proposal_history=proposal_history,
            growth_config=_growth_config,
            now_ms_clock=_now_ms_clock,
            prediction_stream_name=_prediction_stream_name,
            proposal_stream_name=_proposal_stream_name,
            max_history_per_stream=_max_history_per_stream,
        )

    return _evaluator
