from v2.backend.app.services.paper_execution_ledger import (
    PaperExecutionLedgerServiceError,
)


def test_errors_invariants() -> None:
    error = PaperExecutionLedgerServiceError("must_be_int", field="now_ms_clock")

    assert error.code == "must_be_int"
    assert error.field == "now_ms_clock"
    assert str(error) == "must_be_int (now_ms_clock)"
    assert isinstance(error, ValueError) is True
