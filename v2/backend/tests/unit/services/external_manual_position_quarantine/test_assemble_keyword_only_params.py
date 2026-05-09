import pytest

from v2.backend.app.domain.external_manual_position_quarantine import (
    MANUAL_POSITION_NOT_PRESENT,
    ManualPositionFlag,
)
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.external_manual_position_quarantine import (
    assemble_external_position_quarantine_record,
)


def test_assemble_keyword_only_params() -> None:
    decision = RiskDecisionRecord(
        risk_decision_id="risk-kw",
        decision_id="decision-kw",
        prediction_id="prediction-kw",
        feature_snapshot_id="snapshot-kw",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1,
        risk_action="allow",
        risk_reason_code="allow_proceed_long",
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )
    flag = ManualPositionFlag(state=MANUAL_POSITION_NOT_PRESENT, live_blocked=True)

    with pytest.raises(TypeError):
        assemble_external_position_quarantine_record(decision, flag)  # type: ignore[misc]
