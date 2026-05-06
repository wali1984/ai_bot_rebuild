from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry


def test_record_constructs_with_valid_inputs_record_deny_default() -> None:
    entry = PaperExecutionLedgerEntry(
        paper_trade_id="paper-5",
        risk_decision_id="risk-5",
        decision_id="decision-5",
        prediction_id="prediction-5",
        feature_snapshot_id="snapshot-5",
        symbol="ADAUSDT",
        ledger_entry_ts_ms=4,
        ledger_action="record_deny",
        ledger_reason_code="mirror_deny_default",
        input_risk_action="deny",
        input_risk_reason_code="deny_default",
        live_blocked=True,
    )
    assert entry.live_blocked is True
