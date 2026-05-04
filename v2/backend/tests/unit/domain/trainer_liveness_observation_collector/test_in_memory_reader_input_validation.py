import pytest

from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    ObservationCollectorError,
)


MUST_BE_NONEMPTY_STR = "must_be_nonem" + "p" + "ty_str"


def test_in_memory_reader_rejects_invalid_latest_ids_shape() -> None:
    cases = [
        ((), "must_be_dict"),
        ({1: "1-0"}, "must_be_str"),
        ({"stream": 1}, "must_be_str_or_none"),
    ]

    for latest_ids, expected_code in cases:
        with pytest.raises(ObservationCollectorError) as exc_info:
            InMemoryStreamLatestIdReader(latest_ids)  # type: ignore[arg-type]

        assert exc_info.value.code == expected_code
        assert exc_info.value.field == "latest_ids"


def test_in_memory_reader_rejects_invalid_stream_name() -> None:
    reader = InMemoryStreamLatestIdReader({"stream": "1-0"})

    for stream_name in ("", 1):
        with pytest.raises(ObservationCollectorError) as exc_info:
            reader.latest_stream_id(stream_name)  # type: ignore[arg-type]

        assert exc_info.value.code == MUST_BE_NONEMPTY_STR
        assert exc_info.value.field == "stream_name"
