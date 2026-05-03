from __future__ import annotations

from v2.backend.app.domain import trainer_liveness


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
        "LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED",
    ]


def test_public_surface_imports_are_usable() -> None:
    assert trainer_liveness.LivenessSignalSnapshot
    assert trainer_liveness.LivenessSLAConfig
    assert trainer_liveness.LivenessAlert
    assert trainer_liveness.evaluate_liveness
    assert trainer_liveness.LivenessDomainError
