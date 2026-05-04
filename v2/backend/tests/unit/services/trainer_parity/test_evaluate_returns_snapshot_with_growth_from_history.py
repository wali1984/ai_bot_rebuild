from v2.backend.app.domain.liveness_stream_growth import (
    GrowthWindowConfig,
    StreamIdObservation,
    compute_stream_id_growth_in_window,
)
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs
from v2.backend.app.services.trainer_parity import evaluate_trainer_liveness


class _FakeReader:
    def __init__(self, values: dict[str, str | None]) -> None:
        self.values = values

    def latest_stream_id(self, stream_name: str) -> str | None:
        return self.values.get(stream_name)


def test_evaluate_returns_snapshot_with_growth_from_history():
    config = GrowthWindowConfig(1000)
    result = evaluate_trainer_liveness(
        _FakeReader({"pred": "3-0", "prop": "8-0"}),
        base_inputs=LivenessSnapshotBaseInputs(1, 1, 1, 2, True, 1, 1, 1, 1, False, 1),
        prediction_history=(
            StreamIdObservation("pred", "1-0", 900),
            StreamIdObservation("pred", "2-0", 950),
        ),
        proposal_history=(
            StreamIdObservation("prop", "6-0", 900),
            StreamIdObservation("prop", "7-0", 950),
        ),
        growth_config=config,
        now_ms_clock=lambda: 1000,
        prediction_stream_name="pred",
        proposal_stream_name="prop",
        max_history_per_stream=5,
    )
    assert result.snapshot.prediction_stream_id_growth >= 0
    assert result.snapshot.proposal_stream_id_growth >= 0
    assert result.snapshot.prediction_stream_id_growth == compute_stream_id_growth_in_window(
        result.prediction_history,
        config,
        1000,
        stream_name="pred",
    )
    assert result.snapshot.proposal_stream_id_growth == compute_stream_id_growth_in_window(
        result.proposal_history,
        config,
        1000,
        stream_name="prop",
    )
