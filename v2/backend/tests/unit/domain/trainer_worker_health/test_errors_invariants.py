def test_errors_invariants() -> None:
    from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthDomainError

    bare = TrainerWorkerHealthDomainError("foo")
    with_field = TrainerWorkerHealthDomainError("foo", field="bar")

    assert issubclass(TrainerWorkerHealthDomainError, ValueError)
    assert bare.reason == "foo"
    assert bare.field is None
    assert str(bare) == "foo"
    assert with_field.reason == "foo"
    assert with_field.field == "bar"
    assert str(with_field) == "bar: foo"
