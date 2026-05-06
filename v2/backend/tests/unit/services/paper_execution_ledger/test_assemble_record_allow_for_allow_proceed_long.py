from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    assemble_paper_execution_ledger_entry,
)


def test_assemble_record_allow_for_allow_proceed_long() -> None:
    decision = RiskDecisionRecord(
        risk_decision_id="rd_dec_allow_long",
        decision_id="dec_allow_long",
        prediction_id="pred_allow_long",
        feature_snapshot_id="snap_allow_long",
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
        now_ms_clock=lambda: 1000,
    )

    assert entry.ledger_action == "record_allow"
    assert entry.ledger_reason_code == "mirror_allow_proceed_long"
    assert entry.ledger_entry_ts_ms == 1000
    assert entry.paper_trade_id == "pt_rd_dec_allow_long"
    assert entry.live_blocked is True
    assert entry.input_risk_action == "allow"
    assert entry.input_risk_reason_code == "allow_proceed_long"
    assert entry.risk_decision_id == decision.risk_decision_id
    assert entry.decision_id == decision.decision_id
    assert entry.prediction_id == decision.prediction_id
    assert entry.feature_snapshot_id == decision.feature_snapshot_id
    assert entry.symbol == decision.symbol
