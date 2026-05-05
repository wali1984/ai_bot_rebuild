from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord
from v2.backend.app.services.trainer_prediction_output import assemble_prediction_record

from .errors import TrainerPredictionOutputCompositionError


TrainerPredictionOutputEvaluator = Callable[..., TrainerPredictionRecord]


def build_trainer_prediction_output_evaluator(
    *,
    now_ms_clock: Callable[[], int],
) -> TrainerPredictionOutputEvaluator:
    if not callable(now_ms_clock):
        raise TrainerPredictionOutputCompositionError("must_be_callable", field="now_ms_clock")

    _now_ms_clock = now_ms_clock

    def _evaluator(
        *,
        prediction_id,
        feature_snapshot_id,
        symbol,
        model_version,
        checkpoint_id,
        direction,
        confidence_raw,
        confidence_calibrated,
        worker_id,
        worker_health_status,
        freshness_flag,
        source_freshness_age_ms,
        top_positive_feature_codes,
        top_negative_feature_codes,
    ) -> TrainerPredictionRecord:
        return assemble_prediction_record(
            prediction_id=prediction_id,
            feature_snapshot_id=feature_snapshot_id,
            symbol=symbol,
            model_version=model_version,
            checkpoint_id=checkpoint_id,
            direction=direction,
            confidence_raw=confidence_raw,
            confidence_calibrated=confidence_calibrated,
            worker_id=worker_id,
            worker_health_status=worker_health_status,
            freshness_flag=freshness_flag,
            source_freshness_age_ms=source_freshness_age_ms,
            top_positive_feature_codes=top_positive_feature_codes,
            top_negative_feature_codes=top_negative_feature_codes,
            now_ms_clock=_now_ms_clock,
        )

    return _evaluator
