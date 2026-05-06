import pytest


def test_recorder_propagates_service_error_for_non_record_decision():
    from v2.backend.app.composition.paper_execution_ledger import build_paper_execution_ledger_recorder
    from v2.backend.app.services.paper_execution_ledger import PaperExecutionLedgerServiceError

    recorder = build_paper_execution_ledger_recorder(now_ms_clock=lambda: 1)

    with pytest.raises(PaperExecutionLedgerServiceError) as exc_info:
        recorder(decision="not a record")
    assert exc_info.value.code == "must_be_risk_decision_record"
    assert exc_info.value.field == "decision"
