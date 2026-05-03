from __future__ import annotations

from v2.backend.app.domain import trainer_liveness
from v2.backend.app.domain.trainer_liveness.alert import LIVENESS_ALERT_CODE


def test_public_surface_exports_expected_names() -> None:
    assert trainer_liveness.__all__ == [
        "LivenessSignalSnapshot",
        "LivenessSLAConfig",
        "LivenessAlert",
        "evaluate_liveness",
        "LivenessDomainError",
        "LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA",
        "LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA",
        "LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA",
        "LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH",
        "LIVENESS_REASON_PREDICTION_WORKER_DEAD",
        "LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED",
    ]


def test_public_surface_imports_are_usable() -> None:
    assert trainer_liveness.LivenessSignalSnapshot
    assert trainer_liveness.LivenessSLAConfig
    assert trainer_liveness.LivenessAlert
    assert trainer_liveness.evaluate_liveness
    assert trainer_liveness.LivenessDomainError
    assert trainer_liveness.LIVENESS_REASON_PREDICTION_WORKER_DEAD


def test_public_surface_excludes_internal_alert_code_and_errors_module() -> None:
    assert "LIVENESS_ALERT_CODE" not in trainer_liveness.__all__
    assert "errors" not in trainer_liveness.__all__
    assert LIVENESS_ALERT_CODE == "TRAINER_INTERNAL_LIVENESS_CRITICAL"
