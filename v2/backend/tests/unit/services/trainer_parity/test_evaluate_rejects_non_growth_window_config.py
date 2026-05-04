import pytest

from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs
from v2.backend.app.services.trainer_parity import TrainerParityServiceError, evaluate_trainer_liveness


class _FakeReader:
    def latest_stream_id(self, stream_name: str) -> str | None:
        return None


def test_evaluate_rejects_non_growth_window_config():
    with pytest.raises(TrainerParityServiceError) as raised:
        evaluate_trainer_liveness(
            _FakeReader(),
            base_inputs=LivenessSnapshotBaseInputs(1, 1, 1, 2, True, 1, 1, 1, 1, False, 1),
            prediction_history=(),
            proposal_history=(),
            growth_config={},
            now_ms_clock=lambda: 1,
            prediction_stream_name="pred",
            proposal_stream_name="prop",
            max_history_per_stream=1,
        )
    assert raised.value.code == "must_be_growth_window_config"
    assert raised.value.field == "growth_config"
