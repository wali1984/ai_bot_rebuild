import pytest

from v2.backend.app.services.paper_execution_ledger import (
    PaperExecutionLedgerServiceError,
    assemble_paper_execution_ledger_entry,
)


def test_assemble_rejects_decision_not_record() -> None:
    for value in (object(), None):
        with pytest.raises(PaperExecutionLedgerServiceError) as raised:
            assemble_paper_execution_ledger_entry(
                decision=value,  # type: ignore[arg-type]
                now_ms_clock=lambda: 1,
            )
        assert raised.value.code == "must_be_risk_decision_record"
        assert raised.value.field == "decision"
