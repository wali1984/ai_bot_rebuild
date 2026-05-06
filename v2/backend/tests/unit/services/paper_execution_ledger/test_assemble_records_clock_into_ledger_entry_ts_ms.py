from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    assemble_paper_execution_ledger_entry,
)


def test_assemble_records_clock_into_ledger_entry_ts_ms() -> None:
    decision = RiskDecisionRecord(
        risk_decision_id="rd_dec_clock_value",
        decision_id="dec_clock_value",
        prediction_id="pred_clock_value",
        feature_snapshot_id="snap_clock_value",
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
        now_ms_clock=lambda: 42,
    )

    assert entry.ledger_entry_ts_ms == 42
