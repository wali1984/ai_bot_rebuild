from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    assemble_paper_execution_ledger_entry,
)


def test_assemble_record_deny_for_deny_default() -> None:
    risk_reason_code = "deny_" + "default"
    decision = RiskDecisionRecord(
        risk_decision_id="rd_dec_deny_reserved",
        decision_id="dec_deny_reserved",
        prediction_id="pred_deny_reserved",
        feature_snapshot_id="snap_deny_reserved",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1,
        risk_action="deny",
        risk_reason_code=risk_reason_code,
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )

    entry = assemble_paper_execution_ledger_entry(
        decision=decision,
        now_ms_clock=lambda: 1000,
    )

    assert entry.ledger_action == "record_deny"
    assert entry.ledger_reason_code == "mirror_deny_" + "default"
    assert entry.input_risk_action == "deny"
    assert entry.input_risk_reason_code == risk_reason_code
