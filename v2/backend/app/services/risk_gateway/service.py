from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_ABSTAIN,
    DECISION_ACTION_HOLD,
    DECISION_ACTION_OPEN_LONG,
    DECISION_ACTION_OPEN_SHORT,
    OrchestratorDecisionRecord,
)
from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_ALLOW,
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
    RiskDecisionRecord,
)

from .errors import RiskGatewayServiceError


def assemble_risk_decision_record(
    *,
    decision: OrchestratorDecisionRecord,
    now_ms_clock: Callable[[], int],
) -> RiskDecisionRecord:
    if not isinstance(decision, OrchestratorDecisionRecord):
        raise RiskGatewayServiceError(
            "must_be_orchestrator_decision_record",
            field="decision",
        )
    if not callable(now_ms_clock):
        raise RiskGatewayServiceError("must_be_callable", field="now_ms_clock")

    now_ms = now_ms_clock()
    if type(now_ms) is not int:
        raise RiskGatewayServiceError("must_be_int", field="now_ms_clock")
    if now_ms < 0:
        raise RiskGatewayServiceError("must_be_nonnegative", field="now_ms_clock")
    if len(decision.decision_id) > 125:
        raise RiskGatewayServiceError(
            "decision_id_too_long_for_risk_decision_id_derivation",
            field="decision.decision_id",
        )

    if decision.decision_action == DECISION_ACTION_OPEN_LONG:
        risk_action = RISK_DECISION_ACTION_ALLOW
        risk_reason_code = RISK_DECISION_REASON_ALLOW_PROCEED_LONG
    elif decision.decision_action == DECISION_ACTION_OPEN_SHORT:
        risk_action = RISK_DECISION_ACTION_ALLOW
        risk_reason_code = RISK_DECISION_REASON_ALLOW_PROCEED_SHORT
    elif decision.decision_action == DECISION_ACTION_HOLD:
        risk_action = RISK_DECISION_ACTION_DENY
        risk_reason_code = RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD
    elif decision.decision_action == DECISION_ACTION_ABSTAIN:
        risk_action = RISK_DECISION_ACTION_DENY
        risk_reason_code = RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED
    else:
        raise RiskGatewayServiceError(
            "unrecognized_decision_action",
            field="decision.decision_action",
        )

    return RiskDecisionRecord(
        risk_decision_id="rd_" + decision.decision_id,
        decision_id=decision.decision_id,
        prediction_id=decision.prediction_id,
        feature_snapshot_id=decision.feature_snapshot_id,
        symbol=decision.symbol,
        risk_decision_ts_ms=now_ms,
        risk_action=risk_action,
        risk_reason_code=risk_reason_code,
        input_decision_action=decision.decision_action,
        input_decision_reason_code=decision.decision_reason_code,
        live_blocked=True,
    )
