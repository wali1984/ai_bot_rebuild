import pytest

from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    ObservationCollectorError,
    collect_stream_id_observations,
)


def test_collect_rejects_non_callable_clock() -> None:
    reader = InMemoryStreamLatestIdReader({"prediction": "1-0"})

    with pytest.raises(ObservationCollectorError) as exc_info:
        collect_stream_id_observations(
            reader,
            stream_names=("prediction",),
            clock_ms=1,  # type: ignore[arg-type]
        )

    assert exc_info.value.code == "must_be_callable"
    assert exc_info.value.field == "clock_ms"
