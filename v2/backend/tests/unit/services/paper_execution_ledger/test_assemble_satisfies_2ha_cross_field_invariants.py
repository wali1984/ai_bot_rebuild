from v2.backend.app.domain.paper_execution_ledger import (
    PAPER_LEDGER_ACTION_RECORD_ALLOW,
    PAPER_LEDGER_ACTION_RECORD_DENY,
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
    PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT,
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
)
from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
    RISK_DECISION_REASON_DENY_DEFAULT,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
    RiskDecisionRecord,
)
from v2.backend.app.services.paper_execution_ledger import (
    assemble_paper_execution_ledger_entry,
)


def test_assemble_satisfies_2ha_cross_field_invariants() -> None:
    rows = (
        (
            "allow",
            RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
            "open_long",
            "proceed_long",
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
        ),
        (
            "allow",
            RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
            "open_short",
            "proceed_short",
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
        ),
        (
            "deny",
            RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
            "hold",
            "hold_flat_direction",
            PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
        ),
        (
            "deny",
            RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
            "abstain",
            "abstain_low_confidence",
            PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
        ),
        (
            "deny",
            RISK_DECISION_REASON_DENY_DEFAULT,
            "open_long",
            "proceed_long",
            PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT,
        ),
    )
    expected = {
        PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG: RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
        PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT: RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
        PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD: RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
        PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED: RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
        PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT: RISK_DECISION_REASON_DENY_DEFAULT,
    }

    for index, (risk_action, risk_reason_code, input_action, input_reason, _) in enumerate(rows):
        decision = RiskDecisionRecord(
            risk_decision_id="rd_dec_cross_" + str(index),
            decision_id="dec_cross_" + str(index),
            prediction_id="pred_cross_" + str(index),
            feature_snapshot_id="snap_cross_" + str(index),
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
            now_ms_clock=lambda: 10,
        )

        if entry.ledger_action == PAPER_LEDGER_ACTION_RECORD_ALLOW:
            assert entry.ledger_reason_code.startswith("mirror_" + "allow_")
            assert entry.input_risk_action == "allow"
        if entry.ledger_action == PAPER_LEDGER_ACTION_RECORD_DENY:
            assert entry.ledger_reason_code.startswith("mirror_" + "deny_")
            assert entry.input_risk_action == "deny"
        assert expected[entry.ledger_reason_code] == entry.input_risk_reason_code
