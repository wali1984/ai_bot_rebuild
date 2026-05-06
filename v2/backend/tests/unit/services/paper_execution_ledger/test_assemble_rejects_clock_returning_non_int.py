import pytest

from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    PaperExecutionLedgerServiceError,
    assemble_paper_execution_ledger_entry,
)


def test_assemble_rejects_clock_returning_non_int() -> None:
    decision = RiskDecisionRecord(
        risk_decision_id="rd_dec_non_int_clock",
        decision_id="dec_non_int_clock",
        prediction_id="pred_non_int_clock",
        feature_snapshot_id="snap_non_int_clock",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1,
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )

    for value in (1.0, True, "100"):
        with pytest.raises(PaperExecutionLedgerServiceError) as raised:
            assemble_paper_execution_ledger_entry(
                decision=decision,
                now_ms_clock=lambda value=value: value,  # type: ignore[return-value]
            )
        assert raised.value.code == "must_be_int"
        assert raised.value.field == "now_ms_clock"
