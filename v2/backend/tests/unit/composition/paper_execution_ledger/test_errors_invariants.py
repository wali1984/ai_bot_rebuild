import pytest


def test_errors_invariants():
    from v2.backend.app.composition.paper_execution_ledger import (
        PaperExecutionLedgerCompositionError,
    )

    error = PaperExecutionLedgerCompositionError("some_code", field="some_field")

    assert error.code == "some_code"
    assert error.field == "some_field"
    assert str(error) == "some_code (some_field)"
    with pytest.raises(TypeError):
        PaperExecutionLedgerCompositionError("some_code")
