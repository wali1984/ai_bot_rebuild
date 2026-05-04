import pytest

from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    ObservationCollectorError,
    collect_stream_id_observations,
)


def test_collect_rejects_negative_clock_return() -> None:
    reader = InMemoryStreamLatestIdReader({"prediction": "1-0"})

    with pytest.raises(ObservationCollectorError) as exc_info:
        collect_stream_id_observations(
            reader,
            stream_names=("prediction",),
            clock_ms=lambda: -1,
        )

    assert exc_info.value.code == "must_be_nonnegative"
    assert exc_info.value.field == "now_ms"
