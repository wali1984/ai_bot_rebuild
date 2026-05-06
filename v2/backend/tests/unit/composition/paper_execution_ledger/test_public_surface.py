def test_public_surface():
    from v2.backend.app.composition import paper_execution_ledger

    assert paper_execution_ledger.__all__ == (
        "build_paper_execution_ledger_recorder",
        "PaperExecutionLedgerRecorder",
        "PaperExecutionLedgerCompositionError",
    )
    assert callable(paper_execution_ledger.build_paper_execution_ledger_recorder)
    assert isinstance(paper_execution_ledger.PaperExecutionLedgerCompositionError, type)
    assert issubclass(paper_execution_ledger.PaperExecutionLedgerCompositionError, Exception)
    assert not issubclass(paper_execution_ledger.PaperExecutionLedgerCompositionError, ValueError)
    assert paper_execution_ledger.PaperExecutionLedgerRecorder is not None
