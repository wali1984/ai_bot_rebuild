from dataclasses import FrozenInstanceError

import pytest

from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import (
    assemble_paper_execution_ledger_entry,
)


def test_assemble_returns_frozen_record() -> None:
    decision = RiskDecisionRecord(
        risk_decision_id="rd_dec_frozen",
        decision_id="dec_frozen",
        prediction_id="pred_frozen",
        feature_snapshot_id="snap_frozen",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1,
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )
    entry = assemble_paper_execution_ledger_entry(
        decision=decision,
        now_ms_clock=lambda: 4,
    )

    with pytest.raises(FrozenInstanceError):
        entry.symbol = "ETHUSDT"
