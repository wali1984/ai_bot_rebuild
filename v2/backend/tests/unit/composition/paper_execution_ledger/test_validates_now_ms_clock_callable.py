import pytest


def test_validates_now_ms_clock_callable():
    from v2.backend.app.composition.paper_execution_ledger import (
        PaperExecutionLedgerCompositionError,
        build_paper_execution_ledger_recorder,
    )

    for value in (42, None, "not_callable"):
        with pytest.raises(PaperExecutionLedgerCompositionError) as exc_info:
            build_paper_execution_ledger_recorder(now_ms_clock=value)
        assert exc_info.value.code == "must_be_callable"
        assert exc_info.value.field == "now_ms_clock"
