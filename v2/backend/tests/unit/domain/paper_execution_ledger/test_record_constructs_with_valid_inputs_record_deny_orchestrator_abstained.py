from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry


def test_record_constructs_with_valid_inputs_record_deny_orchestrator_abstained() -> None:
    entry = PaperExecutionLedgerEntry(
        paper_trade_id="paper-4",
        risk_decision_id="risk-4",
        decision_id="decision-4",
        prediction_id="prediction-4",
        feature_snapshot_id="snapshot-4",
        symbol="BNBUSDT",
        ledger_entry_ts_ms=3,
        ledger_action="record_deny",
        ledger_reason_code="mirror_deny_orchestrator_abstained",
        input_risk_action="deny",
        input_risk_reason_code="deny_orchestrator_abstained",
        live_blocked=True,
    )
    assert entry.ledger_action == "record_deny"
