import pytest

from v2.backend.app.domain.trainer_liveness_observation_collector import (
    ObservationCollectorError,
    collect_stream_id_observations,
)


class _NonCallableReader:
    latest_stream_id = "not-callable"


def test_collect_rejects_missing_reader_protocol_method() -> None:
    for reader in (object(), _NonCallableReader()):
        with pytest.raises(ObservationCollectorError) as exc_info:
            collect_stream_id_observations(
                reader,  # type: ignore[arg-type]
                stream_names=("prediction",),
                clock_ms=lambda: 1,
            )

        assert exc_info.value.code == "must_be_stream_latest_id_reader"
        assert exc_info.value.field == "reader"
