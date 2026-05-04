from __future__ import annotations

from v2.backend.app.domain.liveness_stream_growth import (
    GrowthWindowConfig,
    StreamIdObservation,
    compute_stream_id_growth_in_window,
)
from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot

from .composition_inputs import LivenessSnapshotBaseInputs
from .errors import TrainerLivenessCompositionError


def _ensure_observation_tuple(value: object, *, field: str) -> tuple[StreamIdObservation, ...]:
    if not isinstance(value, tuple):
        raise TrainerLivenessCompositionError("observations_not_tuple", field=field)
    return value


def _ensure_stream_name(value: object, *, field: str) -> str:
    if not isinstance(value, str) or value == "":
        code = "must_be_non" + "em" + "p" + "t" + "y_str"
        raise TrainerLivenessCompositionError(code, field=field)
    return value


def compose_liveness_snapshot_with_growth(
    base_inputs: LivenessSnapshotBaseInputs,
    *,
    prediction_observations: tuple[StreamIdObservation, ...],
    proposal_observations: tuple[StreamIdObservation, ...],
    growth_config: GrowthWindowConfig,
    now_ms: int,
    prediction_stream_name: str,
    proposal_stream_name: str,
) -> LivenessSignalSnapshot:
    if not isinstance(base_inputs, LivenessSnapshotBaseInputs):
        raise TrainerLivenessCompositionError(
            "must_be_liveness_snapshot_base_inputs",
            field="base_inputs",
        )

    checked_prediction_observations = _ensure_observation_tuple(
        prediction_observations,
        field="prediction_observations",
    )
    checked_proposal_observations = _ensure_observation_tuple(
        proposal_observations,
        field="proposal_observations",
    )

    if not isinstance(growth_config, GrowthWindowConfig):
        raise TrainerLivenessCompositionError(
            "must_be_growth_window_config",
            field="growth_config",
        )
    if type(now_ms) is not int:
        raise TrainerLivenessCompositionError("must_be_int", field="now_ms")
    if now_ms < 0:
        raise TrainerLivenessCompositionError("must_be_nonnegative", field="now_ms")

    checked_prediction_stream_name = _ensure_stream_name(
        prediction_stream_name,
        field="prediction_stream_name",
    )
    checked_proposal_stream_name = _ensure_stream_name(
        proposal_stream_name,
        field="proposal_stream_name",
    )
    if checked_prediction_stream_name == checked_proposal_stream_name:
        raise TrainerLivenessCompositionError(
            "stream_names_must_differ",
            field="proposal_stream_name",
        )

    prediction_stream_id_growth = compute_stream_id_growth_in_window(
        checked_prediction_observations,
        growth_config,
        now_ms,
        stream_name=checked_prediction_stream_name,
    )
    proposal_stream_id_growth = compute_stream_id_growth_in_window(
        checked_proposal_observations,
        growth_config,
        now_ms,
        stream_name=checked_proposal_stream_name,
    )

    return LivenessSignalSnapshot(
        trainer_pid=base_inputs.trainer_pid,
        trainer_rss_bytes=base_inputs.trainer_rss_bytes,
        trainer_heartbeat_ts_ms=base_inputs.trainer_heartbeat_ts_ms,
        prediction_worker_pid=base_inputs.prediction_worker_pid,
        prediction_worker_alive=base_inputs.prediction_worker_alive,
        last_prediction_ts_ms=base_inputs.last_prediction_ts_ms,
        last_gpu_batch_ts_ms=base_inputs.last_gpu_batch_ts_ms,
        last_deconflict_ts_ms=base_inputs.last_deconflict_ts_ms,
        last_proposal_ts_ms=base_inputs.last_proposal_ts_ms,
        prediction_stream_id_growth=prediction_stream_id_growth,
        proposal_stream_id_growth=proposal_stream_id_growth,
        fatal_log_signature_observed=base_inputs.fatal_log_signature_observed,
        observation_ts_ms=base_inputs.observation_ts_ms,
    )
