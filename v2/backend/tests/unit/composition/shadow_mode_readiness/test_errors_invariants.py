import pytest

from v2.backend.app.composition.shadow_mode_readiness import (
    ShadowModeReadinessRuntimeCompositionError,
)


def test_errors_invariants():
    error = ShadowModeReadinessRuntimeCompositionError("some_code", field="some_field")

    assert error.code == "some_code"
    assert error.field == "some_field"
    assert str(error) == "some_code (some_field)"
    with pytest.raises(TypeError):
        ShadowModeReadinessRuntimeCompositionError("some_code")
    assert (
        repr(error)
        == "ShadowModeReadinessRuntimeCompositionError(code='some_code', field='some_field')"
    )
