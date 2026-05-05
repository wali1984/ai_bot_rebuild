from v2.backend.app.composition.trainer_worker_health import TrainerWorkerHealthCompositionError


def test_errors_invariants():
    with_field = TrainerWorkerHealthCompositionError("c1", field="f1")
    without_field = TrainerWorkerHealthCompositionError("c2")

    assert with_field.code == "c1"
    assert with_field.field == "f1"
    assert str(with_field) == "c1 (f1)"
    assert without_field.code == "c2"
    assert without_field.field is None
    assert str(without_field) == "c2"
    assert issubclass(TrainerWorkerHealthCompositionError, Exception)
