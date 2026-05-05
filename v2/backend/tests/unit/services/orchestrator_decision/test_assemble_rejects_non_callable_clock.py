import pytest

from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord
from v2.backend.app.services.orchestrator_decision import (
    OrchestratorDecisionServiceError,
    assemble_orchestrator_decision_record,
)


def test_assemble_rejects_non_callable_clock() -> None:
    prediction = TrainerPredictionRecord(
        prediction_id="pred_bad_clock",
        feature_snapshot_id="snap_bad_clock",
        symbol="BTCUSDT",
        model_version="model",
        checkpoint_id="checkpoint",
        prediction_ts_ms=1,
        direction="long",
        confidence_raw=0.9,
        confidence_calibrated=0.9,
        worker_id="worker",
        worker_health_status="HEALTHY",
        freshness_flag="fresh",
        source_freshness_age_ms=1,
        top_positive_feature_codes=("pos",),
        top_negative_feature_codes=("neg",),
    )

    with pytest.raises(OrchestratorDecisionServiceError) as excinfo:
        assemble_orchestrator_decision_record(
            prediction=prediction,
            low_confidence_threshold=0.5,
            now_ms_clock=42,
        )
    assert (excinfo.value.code, excinfo.value.field) == (
        "must_be_callable",
        "now_ms_clock",
    )
