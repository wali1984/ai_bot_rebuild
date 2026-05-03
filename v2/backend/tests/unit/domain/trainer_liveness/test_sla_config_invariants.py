from __future__ import annotations

import pytest

from v2.backend.app.domain.trainer_liveness import LivenessDomainError, LivenessSLAConfig


def test_sla_config_accepts_positive_thresholds(liveness_sla: LivenessSLAConfig) -> None:
    assert liveness_sla.prediction_age_max_ms == 500
    assert liveness_sla.gpu_batch_age_max_ms == 750
    assert liveness_sla.proposal_age_max_ms == 600
    assert liveness_sla.prediction_stream_zero_growth_window_ms == 1_000


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prediction_age_max_ms", 0),
        ("prediction_age_max_ms", -1),
        ("gpu_batch_age_max_ms", 0),
        ("gpu_batch_age_max_ms", -1),
        ("proposal_age_max_ms", 0),
        ("proposal_age_max_ms", -1),
        ("prediction_stream_zero_growth_window_ms", 0),
        ("prediction_stream_zero_growth_window_ms", -1),
    ],
)
def test_sla_config_rejects_non_positive_thresholds(field: str, value: int) -> None:
    values = {
        "prediction_age_max_ms": 500,
        "gpu_batch_age_max_ms": 750,
        "proposal_age_max_ms": 600,
        "prediction_stream_zero_growth_window_ms": 1_000,
    }
    values[field] = value

    with pytest.raises(LivenessDomainError, match=field):
        LivenessSLAConfig(**values)
