import pytest

from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs
from v2.backend.app.domain.trainer_liveness_observation_collector import ObservationCollectorError
from v2.backend.app.services.trainer_parity import evaluate_trainer_liveness


class _FakeReader:
    def latest_stream_id(self, stream_name: str) -> str | None:
        return None


def test_evaluate_propagates_collector_errors(monkeypatch):
    def raise_forced(reader, *, stream_names, clock_ms):
        raise ObservationCollectorError("forced", field="reader")

    monkeypatch.setattr(
        "v2.backend.app.services.trainer_parity.liveness_service.collect_stream_id_observations",
        raise_forced,
    )
    with pytest.raises(ObservationCollectorError) as raised:
        evaluate_trainer_liveness(
            _FakeReader(),
            base_inputs=LivenessSnapshotBaseInputs(1, 1, 1, 2, True, 1, 1, 1, 1, False, 1),
            prediction_history=(),
            proposal_history=(),
            growth_config=GrowthWindowConfig(1000),
            now_ms_clock=lambda: 1,
            prediction_stream_name="pred",
            proposal_stream_name="prop",
            max_history_per_stream=1,
        )
    assert raised.value.code == "forced"
    assert raised.value.field == "reader"
    assert str(raised.value) == "forced (reader)"
