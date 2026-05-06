from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    assemble_paper_execution_ledger_entry,
)


def test_assemble_record_allow_for_allow_proceed_short() -> None:
    decision = RiskDecisionRecord(
        risk_decision_id="rd_dec_allow_short",
        decision_id="dec_allow_short",
        prediction_id="pred_allow_short",
        feature_snapshot_id="snap_allow_short",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1,
        risk_action="allow",
        risk_reason_code="allow_proceed_short",
        input_decision_action="open_short",
        input_decision_reason_code="proceed_short",
        live_blocked=True,
    )

    entry = assemble_paper_execution_ledger_entry(
        decision=decision,
        now_ms_clock=lambda: 1000,
    )

    assert entry.ledger_action == "record_allow"
    assert entry.ledger_reason_code == "mirror_allow_proceed_short"
    assert entry.input_risk_reason_code == "allow_proceed_short"
