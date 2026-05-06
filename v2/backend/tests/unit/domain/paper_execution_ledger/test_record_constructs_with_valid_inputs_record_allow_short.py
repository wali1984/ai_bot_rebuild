from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry


def test_record_constructs_with_valid_inputs_record_allow_short() -> None:
    entry = PaperExecutionLedgerEntry(
        paper_trade_id="paper-2",
        risk_decision_id="risk-2",
        decision_id="decision-2",
        prediction_id="prediction-2",
        feature_snapshot_id="snapshot-2",
        symbol="ETHUSDT",
        ledger_entry_ts_ms=1,
        ledger_action="record_allow",
        ledger_reason_code="mirror_allow_proceed_short",
        input_risk_action="allow",
        input_risk_reason_code="allow_proceed_short",
        live_blocked=True,
    )
    assert entry.ledger_reason_code == "mirror_allow_proceed_short"
