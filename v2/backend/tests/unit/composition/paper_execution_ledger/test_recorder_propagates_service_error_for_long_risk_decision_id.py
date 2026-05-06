import pytest


def test_recorder_propagates_service_error_for_long_risk_decision_id():
    from v2.backend.app.composition.paper_execution_ledger import build_paper_execution_ledger_recorder
    from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
    from v2.backend.app.services.paper_execution_ledger import PaperExecutionLedgerServiceError

    recorder = build_paper_execution_ledger_recorder(now_ms_clock=lambda: 1)
    decision = RiskDecisionRecord(
        risk_decision_id="r" * 126,
        decision_id="decision_1",
        prediction_id="prediction_1",
        feature_snapshot_id="feature_1",
        symbol="BTCUSD",
        risk_decision_ts_ms=1,
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )

    with pytest.raises(PaperExecutionLedgerServiceError) as exc_info:
        recorder(decision=decision)
    assert exc_info.value.code == "risk_decision_id_too_long_for_paper_trade_id_derivation"
    assert exc_info.value.field == "decision.risk_decision_id"
