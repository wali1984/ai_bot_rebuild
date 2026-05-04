import pytest

from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    ObservationCollectorError,
    collect_stream_id_observations,
)


def test_collect_rejects_stream_names_that_are_not_tuple() -> None:
    reader = InMemoryStreamLatestIdReader({"prediction": "1-0"})

    with pytest.raises(ObservationCollectorError) as exc_info:
        collect_stream_id_observations(
            reader,
            stream_names=["prediction"],  # type: ignore[arg-type]
            clock_ms=lambda: 1,
        )

    assert exc_info.value.code == "must_be_tuple"
    assert exc_info.value.field == "stream_names"
