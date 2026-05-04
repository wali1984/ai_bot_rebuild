import pytest

from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs
from v2.backend.app.services.trainer_parity import TrainerParityServiceError, evaluate_trainer_liveness


class _FakeReader:
    def latest_stream_id(self, stream_name: str) -> str | None:
        return None


def test_evaluate_rejects_non_callable_clock():
    with pytest.raises(TrainerParityServiceError) as raised:
        evaluate_trainer_liveness(
            _FakeReader(),
            base_inputs=LivenessSnapshotBaseInputs(1, 1, 1, 2, True, 1, 1, 1, 1, False, 1),
            prediction_history=(),
            proposal_history=(),
            growth_config=GrowthWindowConfig(1000),
            now_ms_clock=12345,
            prediction_stream_name="pred",
            proposal_stream_name="prop",
            max_history_per_stream=1,
        )
    assert raised.value.code == "must_be_callable"
    assert raised.value.field == "now_ms_clock"
