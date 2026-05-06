def test_public_surface() -> None:
    from v2.backend.app.services import paper_execution_ledger

    assert paper_execution_ledger.__all__ == (
        "assemble_paper_execution_ledger_entry",
        "PaperExecutionLedgerServiceError",
    )
    assert callable(paper_execution_ledger.assemble_paper_execution_ledger_entry)
    assert issubclass(paper_execution_ledger.PaperExecutionLedgerServiceError, ValueError)
