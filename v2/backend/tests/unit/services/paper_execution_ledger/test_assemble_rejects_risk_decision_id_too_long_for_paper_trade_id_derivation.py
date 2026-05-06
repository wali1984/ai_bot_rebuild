import pytest

from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    PaperExecutionLedgerServiceError,
    assemble_paper_execution_ledger_entry,
)


def test_assemble_rejects_risk_decision_id_too_long_for_paper_trade_id_derivation() -> None:
    too_long = "r" * 126
    maximum = "r" * 125
    decision_too_long = RiskDecisionRecord(
        risk_decision_id=too_long,
        decision_id="dec_length",
        prediction_id="pred_length",
        feature_snapshot_id="snap_length",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1,
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )
    decision_maximum = RiskDecisionRecord(
        risk_decision_id=maximum,
        decision_id="dec_length",
        prediction_id="pred_length",
        feature_snapshot_id="snap_length",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1,
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )

    with pytest.raises(PaperExecutionLedgerServiceError) as raised:
        assemble_paper_execution_ledger_entry(
            decision=decision_too_long,
            now_ms_clock=lambda: 1,
        )
    assert raised.value.code == "risk_decision_id_too_long_for_paper_trade_id_derivation"
    assert raised.value.field == "decision.risk_decision_id"

    entry = assemble_paper_execution_ledger_entry(
        decision=decision_maximum,
        now_ms_clock=lambda: 1,
    )
    assert len(entry.paper_trade_id) == 128
