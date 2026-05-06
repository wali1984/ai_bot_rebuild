import pytest

from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    PaperExecutionLedgerServiceError,
    assemble_paper_execution_ledger_entry,
)


def test_assemble_rejects_non_callable_clock() -> None:
    decision = RiskDecisionRecord(
        risk_decision_id="rd_dec_bad_clock",
        decision_id="dec_bad_clock",
        prediction_id="pred_bad_clock",
        feature_snapshot_id="snap_bad_clock",
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
            decision=decision,
            now_ms_clock=42,  # type: ignore[arg-type]
        )

    assert raised.value.code == "must_be_callable"
    assert raised.value.field == "now_ms_clock"
