from v2.backend.app.domain.trainer_liveness_observation_collector import InMemoryStreamLatestIdReader


def test_in_memory_reader_returns_none_when_configured_none() -> None:
    reader = InMemoryStreamLatestIdReader({"trainer:prediction": None})

    assert reader.latest_stream_id("trainer:prediction") is None
