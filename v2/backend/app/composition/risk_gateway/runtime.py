from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.risk_gateway import assemble_risk_decision_record

from .errors import RiskGatewayCompositionError


RiskDecisionEvaluator = Callable[..., RiskDecisionRecord]


def build_risk_decision_evaluator(
    *,
    now_ms_clock: Callable[[], int],
) -> RiskDecisionEvaluator:
    if not callable(now_ms_clock):
        raise RiskGatewayCompositionError("must_be_callable", field="now_ms_clock")

    _now_ms_clock = now_ms_clock

    def _evaluator(*, decision: OrchestratorDecisionRecord, **kwargs: object) -> RiskDecisionRecord:
        return assemble_risk_decision_record(
            decision=decision,
            now_ms_clock=_now_ms_clock,
            **kwargs,
        )

    return _evaluator
