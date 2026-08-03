from dataclasses import is_dataclass

import v2.backend.app.domain.risk_gateway as risk_gateway


def test_public_surface_exports_exact_ordered_names() -> None:
    expected = (
        "RiskGatewayDomainError",
        "RiskDecisionRecord",
        "RISK_DECISION_ACTION_ALLOW",
        "RISK_DECISION_ACTION_DENY",
        "RISK_DECISION_REASON_ALLOW_PROCEED_LONG",
        "RISK_DECISION_REASON_ALLOW_PROCEED_SHORT",
        "RISK_DECISION_REASON_ALLOW_CLOSE_ONLY_INTELLIGENT_CLOSE_GUARD",
        "RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED",
        "RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD",
        "RISK_DECISION_REASON_DENY_DEFAULT",
        "RISK_DECISION_REASON_DENY_KILL_SWITCH_ACTIVE",
        "RISK_DECISION_REASON_DENY_HALT_MANAGER_ACTIVE",
        "RISK_DECISION_REASON_DENY_REDUCE_ONLY_LATCH",
        "RISK_DECISION_REASON_DENY_AUTO_DELEVERAGER_TRIGGERED",
        "RISK_DECISION_REASON_DENY_SHARED_RISK_BUDGET_EXHAUSTED",
        "RISK_DECISION_REASON_DENY_MARGIN_GOVERNOR_LEVERAGE_INCREASE_BLOCKED",
        "RISK_DECISION_REASON_DENY_PHASE_CONTROLLER_WARMUP",
        "RISK_DECISION_REASON_DENY_ADAPTIVE_MICROSTRUCTURE_TOXIC",
        "evaluate_risk_evaluator_context",
    )
    assert risk_gateway.__all__ == expected
    assert issubclass(risk_gateway.RiskGatewayDomainError, ValueError)
    assert is_dataclass(risk_gateway.RiskDecisionRecord)
    assert risk_gateway.RiskDecisionRecord.__dataclass_fields__
    assert isinstance(risk_gateway.RISK_DECISION_ACTION_ALLOW, str)
    assert isinstance(risk_gateway.RISK_DECISION_ACTION_DENY, str)
    assert isinstance(risk_gateway.RISK_DECISION_REASON_ALLOW_PROCEED_LONG, str)
    assert isinstance(risk_gateway.RISK_DECISION_REASON_ALLOW_PROCEED_SHORT, str)
    assert isinstance(risk_gateway.RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED, str)
    assert isinstance(risk_gateway.RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD, str)
    assert isinstance(risk_gateway.RISK_DECISION_REASON_DENY_DEFAULT, str)
    assert isinstance(risk_gateway.RISK_DECISION_REASON_DENY_HALT_MANAGER_ACTIVE, str)
    assert callable(risk_gateway.evaluate_risk_evaluator_context)
