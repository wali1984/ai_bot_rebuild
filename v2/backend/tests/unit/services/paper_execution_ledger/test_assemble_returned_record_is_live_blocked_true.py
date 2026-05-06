from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    assemble_paper_execution_ledger_entry,
)


def test_assemble_returned_record_is_live_blocked_true() -> None:
    decision = RiskDecisionRecord(
        risk_decision_id="rd_dec_live_blocked",
        decision_id="dec_live_blocked",
        prediction_id="pred_live_blocked",
        feature_snapshot_id="snap_live_blocked",
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
        now_ms_clock=lambda: 6,
    )

    assert entry.live_blocked is True
    assert entry.live_blocked == True
    assert type(entry.live_blocked) is bool
