from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    assemble_paper_execution_ledger_entry,
)


def test_assemble_propagates_input_lineage_fields() -> None:
    decision = RiskDecisionRecord(
        risk_decision_id="rd_dec_lineage_xyz",
        decision_id="dec_lineage_xyz",
        prediction_id="pred_lineage_xyz",
        feature_snapshot_id="snap_lineage_xyz",
        symbol="ETHUSDT",
        risk_decision_ts_ms=1,
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )

    entry = assemble_paper_execution_ledger_entry(
        decision=decision,
        now_ms_clock=lambda: 5,
    )

    assert entry.risk_decision_id == "rd_dec_lineage_xyz"
    assert entry.decision_id == "dec_lineage_xyz"
    assert entry.prediction_id == "pred_lineage_xyz"
    assert entry.feature_snapshot_id == "snap_lineage_xyz"
    assert entry.symbol == "ETHUSDT"
    assert entry.paper_trade_id == "pt_rd_dec_lineage_xyz"
    assert entry.input_risk_action == "allow"
    assert entry.input_risk_reason_code == "allow_proceed_long"
    assert entry.live_blocked is True
