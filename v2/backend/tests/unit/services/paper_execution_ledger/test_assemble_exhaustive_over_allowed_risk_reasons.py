import pytest

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
    PaperExecutionLedgerServiceError,
    assemble_paper_execution_ledger_entry,
)


def test_assemble_exhaustive_over_allowed_risk_reasons() -> None:
    rows = (
        (
            "allow",
            RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
            "open_long",
            "proceed_long",
            PAPER_LEDGER_ACTION_RECORD_ALLOW,
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
        ),
        (
            "allow",
            RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
            "open_short",
            "proceed_short",
            PAPER_LEDGER_ACTION_RECORD_ALLOW,
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
        ),
        (
            "deny",
            RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
            "hold",
            "hold_flat_direction",
            PAPER_LEDGER_ACTION_RECORD_DENY,
            PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
        ),
        (
            "deny",
            RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
            "abstain",
            "abstain_low_confidence",
            PAPER_LEDGER_ACTION_RECORD_DENY,
            PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
        ),
        (
            "deny",
            RISK_DECISION_REASON_DENY_DEFAULT,
            "open_long",
            "proceed_long",
            PAPER_LEDGER_ACTION_RECORD_DENY,
            PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT,
        ),
    )

    assert len(rows) == 5
    for index, (
        risk_action,
        risk_reason_code,
        input_action,
        input_reason,
        expected_action,
        expected_reason,
    ) in enumerate(rows):
        decision = RiskDecisionRecord(
            risk_decision_id="rd_dec_exhaustive_" + str(index),
            decision_id="dec_exhaustive_" + str(index),
            prediction_id="pred_exhaustive_" + str(index),
            feature_snapshot_id="snap_exhaustive_" + str(index),
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
            now_ms_clock=lambda: 9,
        )
        assert entry.ledger_action == expected_action
        assert entry.ledger_reason_code == expected_reason

    invalid = RiskDecisionRecord(
        risk_decision_id="rd_dec_exhaustive_invalid",
        decision_id="dec_exhaustive_invalid",
        prediction_id="pred_exhaustive_invalid",
        feature_snapshot_id="snap_exhaustive_invalid",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1,
        risk_action="deny",
        risk_reason_code=RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
        input_decision_action="hold",
        input_decision_reason_code="hold_flat_direction",
        live_blocked=True,
    )
    object.__setattr__(invalid, "risk_reason_code", "deny_unrecognized_synthetic")

    with pytest.raises(PaperExecutionLedgerServiceError) as raised:
        assemble_paper_execution_ledger_entry(
            decision=invalid,
            now_ms_clock=lambda: 9,
        )

    assert raised.value.code == "unrecognized_risk_reason_code"
    assert raised.value.field == "decision.risk_reason_code"
