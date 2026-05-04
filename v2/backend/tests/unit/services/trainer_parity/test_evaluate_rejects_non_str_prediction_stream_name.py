import pytest

from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs
from v2.backend.app.services.trainer_parity import TrainerParityServiceError, evaluate_trainer_liveness


class _FakeReader:
    def latest_stream_id(self, stream_name: str) -> str | None:
        return None


def test_evaluate_rejects_non_str_prediction_stream_name():
    with pytest.raises(TrainerParityServiceError) as raised:
        evaluate_trainer_liveness(
            _FakeReader(),
            base_inputs=LivenessSnapshotBaseInputs(1, 1, 1, 2, True, 1, 1, 1, 1, False, 1),
            prediction_history=(),
            proposal_history=(),
            growth_config=GrowthWindowConfig(1000),
            now_ms_clock=lambda: 1,
            prediction_stream_name=1,
            proposal_stream_name="prop",
            max_history_per_stream=1,
        )
    assert raised.value.code == "must_be_nonempty_str"
    assert raised.value.field == "prediction_stream_name"
