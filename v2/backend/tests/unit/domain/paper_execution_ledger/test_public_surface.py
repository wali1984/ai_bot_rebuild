import v2.backend.app.domain.paper_execution_ledger as paper_execution_ledger


def test_public_surface() -> None:
    assert paper_execution_ledger.__all__ == (
        "PaperExecutionLedgerDomainError",
        "PaperExecutionLedgerEntry",
        "PAPER_LEDGER_ACTION_RECORD_ALLOW",
        "PAPER_LEDGER_ACTION_RECORD_DENY",
        "PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG",
        "PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT",
        "PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED",
        "PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD",
        "PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT",
    )
