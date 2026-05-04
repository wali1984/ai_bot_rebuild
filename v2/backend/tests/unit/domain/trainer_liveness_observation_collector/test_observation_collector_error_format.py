from v2.backend.app.domain.trainer_liveness_observation_collector import ObservationCollectorError


def test_observation_collector_error_stores_and_formats_code_and_field() -> None:
    without_field = ObservationCollectorError("must_be_dict")
    with_field = ObservationCollectorError("must_be_dict", field="latest_ids")

    assert without_field.code == "must_be_dict"
    assert without_field.field is None
    assert str(without_field) == "must_be_dict"
    assert with_field.code == "must_be_dict"
    assert with_field.field == "latest_ids"
    assert str(with_field) == "must_be_dict (latest_ids)"
    assert ObservationCollectorError.__bases__ == (Exception,)
