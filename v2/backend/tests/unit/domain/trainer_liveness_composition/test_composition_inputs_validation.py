from __future__ import annotations

import pytest

from v2.backend.app.domain.trainer_liveness_composition import TrainerLivenessCompositionError
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs


def base_inputs(**overrides: object) -> LivenessSnapshotBaseInputs:
    values = {
        "trainer_pid": 101,
        "trainer_rss_bytes": 4096,
        "trainer_heartbeat_ts_ms": 900,
        "prediction_worker_pid": 202,
        "prediction_worker_alive": True,
        "last_prediction_ts_ms": 910,
        "last_gpu_batch_ts_ms": 920,
        "last_deconflict_ts_ms": 930,
        "last_proposal_ts_ms": 940,
        "fatal_log_signature_observed": False,
        "observation_ts_ms": 1000,
    }
    values.update(overrides)
    return LivenessSnapshotBaseInputs(**values)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("prediction_worker_alive", "yes", "must_be_bool"),
        ("fatal_log_signature_observed", 1, "must_be_bool"),
        ("observation_ts_ms", "1000", "must_be_int"),
        ("observation_ts_ms", -1, "must_be_nonnegative"),
    ],
)
def test_base_inputs_validation(field: str, value: object, code: str) -> None:
    with pytest.raises(TrainerLivenessCompositionError) as exc:
        base_inputs(**{field: value})

    assert exc.value.code == code
    assert exc.value.field == field
