import pytest


def test_errors_invariants():
    from v2.backend.app.composition.paper_mode import PaperModeRuntimeCompositionError

    error = PaperModeRuntimeCompositionError("some_code", field="some_field")

    assert error.code == "some_code"
    assert error.field == "some_field"
    assert str(error) == "some_code (some_field)"
    with pytest.raises(TypeError):
        PaperModeRuntimeCompositionError("some_code")
    assert (
        repr(error)
        == "PaperModeRuntimeCompositionError(code='some_code', field='some_field')"
    )
