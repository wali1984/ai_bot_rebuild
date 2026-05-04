from v2.backend.app.domain.trainer_liveness_observation_collector import InMemoryStreamLatestIdReader


def test_in_memory_reader_returns_configured_id() -> None:
    reader = InMemoryStreamLatestIdReader({"trainer:prediction": "101-0"})

    assert reader.latest_stream_id("trainer:prediction") == "101-0"
