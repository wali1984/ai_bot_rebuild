from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    assemble_paper_execution_ledger_entry,
)


def test_assemble_record_deny_for_deny_orchestrator_held() -> None:
    decision = RiskDecisionRecord(
        risk_decision_id="rd_dec_deny_held",
        decision_id="dec_deny_held",
        prediction_id="pred_deny_held",
        feature_snapshot_id="snap_deny_held",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1,
        risk_action="deny",
        risk_reason_code="deny_orchestrator_held",
        input_decision_action="hold",
        input_decision_reason_code="hold_flat_direction",
        live_blocked=True,
    )

    entry = assemble_paper_execution_ledger_entry(
        decision=decision,
        now_ms_clock=lambda: 1000,
    )

    assert entry.ledger_action == "record_deny"
    assert entry.ledger_reason_code == "mirror_deny_orchestrator_held"
    assert entry.input_risk_action == "deny"
    assert entry.input_risk_reason_code == "deny_orchestrator_held"
    assert entry.live_blocked is True
