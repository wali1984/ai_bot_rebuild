import pytest

from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    ObservationCollectorError,
    collect_stream_id_observations,
)


MUST_BE_NONEMPTY_STR = "must_be_nonem" + "p" + "ty_str"


def test_collect_rejects_bad_string_stream_names() -> None:
    reader = InMemoryStreamLatestIdReader({"prediction": "1-0"})

    for stream_names in (("",), (1,)):
        with pytest.raises(ObservationCollectorError) as exc_info:
            collect_stream_id_observations(
                reader,
                stream_names=stream_names,  # type: ignore[arg-type]
                clock_ms=lambda: 1,
            )

        assert exc_info.value.code == MUST_BE_NONEMPTY_STR
        assert exc_info.value.field == "stream_names"
