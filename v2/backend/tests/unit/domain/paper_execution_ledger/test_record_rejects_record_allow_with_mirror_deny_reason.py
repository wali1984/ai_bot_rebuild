import pytest

from v2.backend.app.domain.paper_execution_ledger import (
    PaperExecutionLedgerDomainError,
    PaperExecutionLedgerEntry,
)


def test_record_rejects_record_allow_with_mirror_deny_reason() -> None:
    with pytest.raises(PaperExecutionLedgerDomainError) as exc_info:
        PaperExecutionLedgerEntry(
            paper_trade_id="paper-1",
            risk_decision_id="risk-1",
            decision_id="decision-1",
            prediction_id="prediction-1",
            feature_snapshot_id="snapshot-1",
            symbol="BTCUSDT",
            ledger_entry_ts_ms=0,
            ledger_action="record_allow",
            ledger_reason_code="mirror_deny_orchestrator_held",
            input_risk_action="allow",
            input_risk_reason_code="deny_orchestrator_held",
            live_blocked=True,
        )
    assert exc_info.value.reason == "record_allow_requires_mirror_allow_prefix_reason"
