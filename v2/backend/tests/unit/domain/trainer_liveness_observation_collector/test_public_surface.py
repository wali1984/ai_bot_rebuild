from v2.backend.app.domain import trainer_liveness_observation_collector as gamma


def test_public_surface_exports_documented_names_only() -> None:
    assert gamma.__all__ == (
        "StreamLatestIdReader",
        "InMemoryStreamLatestIdReader",
        "collect_stream_id_observations",
        "extend_observation_history",
        "ObservationCollectorError",
    )

    visible_names = {
        name
        for name in dir(gamma)
        if not name.startswith("_") and name not in {"annotations"}
    }
    assert visible_names == {
        "StreamLatestIdReader",
        "InMemoryStreamLatestIdReader",
        "ObservationCollectorError",
    }
