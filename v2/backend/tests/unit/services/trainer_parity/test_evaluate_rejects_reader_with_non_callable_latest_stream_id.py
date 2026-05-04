import pytest

from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs
from v2.backend.app.services.trainer_parity import TrainerParityServiceError, evaluate_trainer_liveness


class _Reader:
    latest_stream_id = 42


def test_evaluate_rejects_reader_with_non_callable_latest_stream_id():
    with pytest.raises(TrainerParityServiceError) as raised:
        evaluate_trainer_liveness(
            _Reader(),
            base_inputs=LivenessSnapshotBaseInputs(1, 1, 1, 2, True, 1, 1, 1, 1, False, 1),
            prediction_history=(),
            proposal_history=(),
            growth_config=GrowthWindowConfig(1000),
            now_ms_clock=lambda: 1,
            prediction_stream_name="pred",
            proposal_stream_name="prop",
            max_history_per_stream=1,
        )
    assert raised.value.code == "must_be_stream_latest_id_reader"
    assert raised.value.field == "reader"
