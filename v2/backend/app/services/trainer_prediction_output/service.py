from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord

from .errors import TrainerPredictionOutputServiceError


def assemble_prediction_record(
    *,
    prediction_id: str,
    feature_snapshot_id: str,
    symbol: str,
    model_version: str,
    checkpoint_id: str,
    direction: str,
    confidence_raw: float,
    confidence_calibrated: float,
    worker_id: str,
    worker_health_status: str,
    freshness_flag: str,
    source_freshness_age_ms: int | None,
    top_positive_feature_codes: tuple[str, ...],
    top_negative_feature_codes: tuple[str, ...],
    now_ms_clock: Callable[[], int],
) -> TrainerPredictionRecord:
    if not callable(now_ms_clock):
        raise TrainerPredictionOutputServiceError("must_be_callable", field="now_ms_clock")

    now_ms = now_ms_clock()

    if type(now_ms) is not int:
        raise TrainerPredictionOutputServiceError("must_be_int", field="now_ms_clock")
    if now_ms < 0:
        raise TrainerPredictionOutputServiceError("must_be_nonnegative", field="now_ms_clock")

    return TrainerPredictionRecord(
        prediction_id=prediction_id,
        feature_snapshot_id=feature_snapshot_id,
        symbol=symbol,
        model_version=model_version,
        checkpoint_id=checkpoint_id,
        prediction_ts_ms=now_ms,
        direction=direction,
        confidence_raw=confidence_raw,
        confidence_calibrated=confidence_calibrated,
        worker_id=worker_id,
        worker_health_status=worker_health_status,
        freshness_flag=freshness_flag,
        source_freshness_age_ms=source_freshness_age_ms,
        top_positive_feature_codes=top_positive_feature_codes,
        top_negative_feature_codes=top_negative_feature_codes,
    )
