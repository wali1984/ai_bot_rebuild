from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    assemble_paper_execution_ledger_entry,
)


def test_assemble_calls_clock_exactly_once() -> None:
    calls: list[None] = []
    decision = RiskDecisionRecord(
        risk_decision_id="rd_dec_clock_once",
        decision_id="dec_clock_once",
        prediction_id="pred_clock_once",
        feature_snapshot_id="snap_clock_once",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1,
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )

    def clock() -> int:
        calls.append(None)
        if len(calls) == 1:
            return 1
        return 999

    entry = assemble_paper_execution_ledger_entry(
        decision=decision,
        now_ms_clock=clock,
    )

    assert len(calls) == 1
    assert entry.ledger_entry_ts_ms == 1
