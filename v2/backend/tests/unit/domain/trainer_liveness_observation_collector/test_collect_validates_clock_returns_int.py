import pytest

from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    ObservationCollectorError,
    collect_stream_id_observations,
)


def test_collect_rejects_clock_return_that_is_not_exact_int() -> None:
    reader = InMemoryStreamLatestIdReader({"prediction": "1-0"})

    for now_ms in (True, 1.0, "1"):
        with pytest.raises(ObservationCollectorError) as exc_info:
            collect_stream_id_observations(
                reader,
                stream_names=("prediction",),
                clock_ms=lambda now_ms=now_ms: now_ms,  # type: ignore[return-value]
            )

        assert exc_info.value.code == "must_be_int"
        assert exc_info.value.field == "now_ms"
