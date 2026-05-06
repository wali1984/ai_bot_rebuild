from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    assemble_paper_execution_ledger_entry,
)


def test_assemble_input_risk_action_propagates() -> None:
    rows = (
        ("allow", "allow_proceed_long", "open_long", "proceed_long"),
        ("deny", "deny_orchestrator_held", "hold", "hold_flat_direction"),
    )

    for risk_action, risk_reason_code, input_action, input_reason in rows:
        decision = RiskDecisionRecord(
            risk_decision_id="rd_dec_action_" + risk_action,
            decision_id="dec_action_" + risk_action,
            prediction_id="pred_action_" + risk_action,
            feature_snapshot_id="snap_action_" + risk_action,
            symbol="BTCUSDT",
            risk_decision_ts_ms=1,
            risk_action=risk_action,
            risk_reason_code=risk_reason_code,
            input_decision_action=input_action,
            input_decision_reason_code=input_reason,
            live_blocked=True,
        )
        entry = assemble_paper_execution_ledger_entry(
            decision=decision,
            now_ms_clock=lambda: 7,
        )
        assert entry.input_risk_action == risk_action
