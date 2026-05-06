from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    assemble_paper_execution_ledger_entry,
)


def test_assemble_paper_trade_id_derived_from_risk_decision_id() -> None:
    decision = RiskDecisionRecord(
        risk_decision_id="rd_dec_pred_abc",
        decision_id="dec_pred_abc",
        prediction_id="pred_abc",
        feature_snapshot_id="snap_abc",
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
        now_ms_clock=lambda: 2,
    )

    assert entry.paper_trade_id == "pt_rd_dec_pred_abc"
