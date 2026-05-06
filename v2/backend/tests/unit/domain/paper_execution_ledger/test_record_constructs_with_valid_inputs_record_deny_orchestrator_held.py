from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry


def test_record_constructs_with_valid_inputs_record_deny_orchestrator_held() -> None:
    entry = PaperExecutionLedgerEntry(
        paper_trade_id="paper-3",
        risk_decision_id="risk-3",
        decision_id="decision-3",
        prediction_id="prediction-3",
        feature_snapshot_id="snapshot-3",
        symbol="SOLUSDT",
        ledger_entry_ts_ms=2,
        ledger_action="record_deny",
        ledger_reason_code="mirror_deny_orchestrator_held",
        input_risk_action="deny",
        input_risk_reason_code="deny_orchestrator_held",
        live_blocked=True,
    )
    assert entry.input_risk_reason_code == "deny_orchestrator_held"
