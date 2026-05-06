from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    assemble_paper_execution_ledger_entry,
)


def test_assemble_returns_paper_execution_ledger_entry() -> None:
    decision = RiskDecisionRecord(
        risk_decision_id="rd_dec_entry_type",
        decision_id="dec_entry_type",
        prediction_id="pred_entry_type",
        feature_snapshot_id="snap_entry_type",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1,
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )

    entry = assemble_paper_execution_ledger_entry(
        decision=decision,
        now_ms_clock=lambda: 3,
    )

    assert isinstance(entry, PaperExecutionLedgerEntry)
