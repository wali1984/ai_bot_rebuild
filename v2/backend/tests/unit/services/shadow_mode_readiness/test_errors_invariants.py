from v2.backend.app.services.shadow_mode_readiness.errors import (
    ShadowModeReadinessServiceError,
)


def test_errors_invariants() -> None:
    error = ShadowModeReadinessServiceError("must_be_str", field="requested_state")

    assert error.code == "must_be_str"
    assert error.field == "requested_state"
    assert str(error) == "must_be_str (requested_state)"
    assert repr(error) == (
        "ShadowModeReadinessServiceError(code='must_be_str', field='requested_state')"
    )
    assert isinstance(error, ValueError) is True
