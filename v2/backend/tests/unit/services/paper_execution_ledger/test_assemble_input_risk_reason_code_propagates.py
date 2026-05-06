from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    assemble_paper_execution_ledger_entry,
)


def test_assemble_input_risk_reason_code_propagates() -> None:
    rows = (
        ("allow", "allow_proceed_long", "open_long", "proceed_long"),
        ("allow", "allow_proceed_short", "open_short", "proceed_short"),
        ("deny", "deny_orchestrator_held", "hold", "hold_flat_direction"),
        ("deny", "deny_orchestrator_abstained", "abstain", "abstain_low_confidence"),
        ("deny", "deny_" + "default", "open_long", "proceed_long"),
    )

    for index, (risk_action, risk_reason_code, input_action, input_reason) in enumerate(rows):
        decision = RiskDecisionRecord(
            risk_decision_id="rd_dec_reason_" + str(index),
            decision_id="dec_reason_" + str(index),
            prediction_id="pred_reason_" + str(index),
            feature_snapshot_id="snap_reason_" + str(index),
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
            now_ms_clock=lambda: 8,
        )
        assert entry.input_risk_reason_code == risk_reason_code
