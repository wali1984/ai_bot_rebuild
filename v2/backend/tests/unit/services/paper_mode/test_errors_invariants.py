from v2.backend.app.services.paper_mode import PaperModeServiceError


def test_errors_invariants() -> None:
    error = PaperModeServiceError("must_be_str", field="requested_mode")
    assert error.code == "must_be_str"
    assert error.field == "requested_mode"
    assert str(error) == "must_be_str (requested_mode)"
    assert repr(error) == (
        "PaperModeServiceError(code='must_be_str', field='requested_mode')"
    )
    assert isinstance(error, ValueError) is True
