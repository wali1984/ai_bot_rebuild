import dataclasses

import pytest

from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry


def test_record_constructs_with_valid_inputs_record_allow_long() -> None:
    entry = PaperExecutionLedgerEntry(
        paper_trade_id="paper-1",
        risk_decision_id="risk-1",
        decision_id="decision-1",
        prediction_id="prediction-1",
        feature_snapshot_id="snapshot-1",
        symbol="BTCUSDT",
        ledger_entry_ts_ms=0,
        ledger_action="record_allow",
        ledger_reason_code="mirror_allow_proceed_long",
        input_risk_action="allow",
        input_risk_reason_code="allow_proceed_long",
        live_blocked=True,
    )
    assert entry.paper_trade_id == "paper-1"
    assert entry.ledger_reason_code == "mirror_allow_proceed_long"
    assert isinstance(entry.__class__.__dict__.get("__slots__"), tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.paper_trade_id = "x"  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
        setattr(entry, "unknown_attribute", "x")
