def test_errors_invariants() -> None:
    from v2.backend.app.services.trainer_worker_health import TrainerWorkerHealthServiceError

    error = TrainerWorkerHealthServiceError("some_code", field="some_field")

    assert error.code == "some_code"
    assert error.field == "some_field"
    assert str(error) == "some_code (some_field)"
    assert repr(error) == "TrainerWorkerHealthServiceError(code='some_code', field='some_field')"
