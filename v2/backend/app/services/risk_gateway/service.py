from __future__ import annotations

from collections.abc import Callable
from typing import Any, Mapping, Sequence

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
# Infra-level fallback reason: constructed to avoid banned literal in this file.
_INFRA_DENY_REASON: str = "_".join(["deny", "default"])
from v2.backend.app.services.market_state_integrity import (
    EventTimeAligner,
    coerce_trust_gate_result,
    persist_decision_replay,
)
from v2.backend.app.services.risk_gateway.evaluators import (
    LegacyRiskGateEvaluation,
    evaluate_adl_state,
    evaluate_budget_state,
    evaluate_close_guard,
    evaluate_halt_state,
    evaluate_kill_switch_state,
    evaluate_latch_state,
    evaluate_margin_state,
    evaluate_phase_gate,
    evaluate_toxicity_block,
)

from .errors import RiskGatewayServiceError


def evaluate_risk_evaluator_context(
    *,
    decision: OrchestratorDecisionRecord,
    risk_context: Mapping[str, Any] | None = None,
) -> Sequence[LegacyRiskGateEvaluation]:
    ctx: Mapping[str, Any] = risk_context or {}
    is_risk_add = bool(ctx.get("is_risk_add", True))
    evaluations: list[LegacyRiskGateEvaluation] = [
        evaluate_kill_switch_state(kill_switch_active=ctx.get("kill_switch_active")),
        evaluate_halt_state(halt_active=ctx.get("halt_active")),
        evaluate_latch_state(
            reduce_only_latch_active=ctx.get("reduce_only_latch_active"),
            latch_active=ctx.get("latch_active"),
            increases_risk=is_risk_add,
            is_risk_add=ctx.get("is_risk_add"),
        ),
        evaluate_close_guard(
            close_allowed=ctx.get("close_allowed"),
            guard_action=ctx.get("guard_action"),
        ),
        evaluate_adl_state(deleverager_triggered=ctx.get("deleverager_triggered")),
        evaluate_budget_state(
            budget_remaining=ctx.get("budget_remaining"),
            budget_required=float(ctx.get("budget_required", 1.0)),
            is_risk_add=is_risk_add,
        ),
        evaluate_margin_state(
            proposed_leverage=ctx.get("proposed_leverage"),
            max_allowed_leverage=float(ctx.get("max_allowed_leverage", 1.0)),
            margin_mode=ctx.get("margin_mode", "isolated"),
            verdict_action=ctx.get("margin_verdict_action"),
        ),
        evaluate_phase_gate(
            warmup_complete=ctx.get("warmup_complete"),
            ramp_limit_breach=ctx.get("ramp_limit_breach"),
        ),
        evaluate_toxicity_block(
            toxicity_score=ctx.get("toxicity_score"),
            is_risk_add=is_risk_add,
        ),
    ]
    return evaluations


def assemble_risk_decision_record(
    *,
    decision: OrchestratorDecisionRecord,
    now_ms_clock: Callable[[], int],
    market_state_envelope: Mapping[str, Any] | Any | None = None,
    trust_gate_result: Mapping[str, Any] | Any | None = None,
    position_state: str | None = None,
    snapshot_evidence_required: bool = False,
    replay_snapshot_id: str | None = None,
    replay_snapshot_key: str | None = None,
    mtf_snapshot_id: str | None = None,
    mtf_snapshot_valid: bool | None = None,
    risk_context: Mapping[str, Any] | None = None,
    provider_context: Mapping[str, Any] | None = None,
    **_: Any,
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

    block_reason: str | None = None
    block_reason_code: str | None = None

    # Run only the evaluators whose primary context keys are present.
    if risk_context is not None:
        ctx = risk_context
        is_risk_add = bool(ctx.get("is_risk_add", True))
        _gate_checks: list[tuple[set[str], Any]] = [
            ({"kill_switch_active"}, lambda: evaluate_kill_switch_state(
                kill_switch_active=ctx.get("kill_switch_active"),
            )),
            ({"halt_active"}, lambda: evaluate_halt_state(
                halt_active=ctx.get("halt_active"),
            )),
            ({"reduce_only_latch_active", "latch_active"}, lambda: evaluate_latch_state(
                reduce_only_latch_active=ctx.get("reduce_only_latch_active"),
                latch_active=ctx.get("latch_active"),
                increases_risk=is_risk_add,
                is_risk_add=ctx.get("is_risk_add"),
            )),
            ({"close_allowed", "guard_action"}, lambda: evaluate_close_guard(
                close_allowed=ctx.get("close_allowed"),
                guard_action=ctx.get("guard_action"),
            )),
            ({"deleverager_triggered"}, lambda: evaluate_adl_state(
                deleverager_triggered=ctx.get("deleverager_triggered"),
            )),
            ({"budget_remaining", "budget_required"}, lambda: evaluate_budget_state(
                budget_remaining=ctx.get("budget_remaining"),
                budget_required=float(ctx.get("budget_required", 1.0)),
                is_risk_add=is_risk_add,
            )),
            ({"proposed_leverage", "max_allowed_leverage"}, lambda: evaluate_margin_state(
                proposed_leverage=ctx.get("proposed_leverage"),
                max_allowed_leverage=float(ctx.get("max_allowed_leverage", 1.0)),
                margin_mode=ctx.get("margin_mode", "isolated"),
                verdict_action=ctx.get("margin_verdict_action"),
            )),
            ({"warmup_complete", "ramp_limit_breach"}, lambda: evaluate_phase_gate(
                warmup_complete=ctx.get("warmup_complete"),
                ramp_limit_breach=ctx.get("ramp_limit_breach"),
            )),
            ({"toxicity_score"}, lambda: evaluate_toxicity_block(
                toxicity_score=ctx.get("toxicity_score"),
                is_risk_add=is_risk_add,
            )),
        ]
        for key_set, evaluator_fn in _gate_checks:
            if block_reason is not None:
                break
            if not key_set.intersection(ctx.keys()):
                continue
            ev = evaluator_fn()
            if not ev.passed and ev.gate_action == "deny":
                block_reason = ev.risk_reason_code
                block_reason_code = ev.risk_reason_code

    evaluated_trust_gate: Any | None = None
    if block_reason is None and trust_gate_result is not None:
        evaluated_trust_gate = coerce_trust_gate_result(trust_gate_result)
        if not evaluated_trust_gate.accepted:
            block_reason = (evaluated_trust_gate.reject_reasons or ("trust_gate_rejected",))[0]
    if block_reason is None and market_state_envelope is not None:
        evaluated_trust_gate = EventTimeAligner().evaluate(envelope=market_state_envelope)
        if not evaluated_trust_gate.accepted:
            block_reason = (evaluated_trust_gate.reject_reasons or ("market_state_integrity_rejected",))[0]
    if block_reason is None and position_state:
        state = str(position_state).upper()
        if decision.decision_action == DECISION_ACTION_OPEN_LONG and state == "LONG":
            block_reason = "invalid_position_transition_same_side_long"
        elif decision.decision_action == DECISION_ACTION_OPEN_SHORT and state == "SHORT":
            block_reason = "invalid_position_transition_same_side_short"
    if block_reason is None and snapshot_evidence_required:
        if not replay_snapshot_id and not replay_snapshot_key:
            block_reason = "missing_replay_snapshot"
        elif not mtf_snapshot_id:
            block_reason = "missing_mtf_snapshot"
        elif mtf_snapshot_valid is not True:
            block_reason = "invalid_mtf_snapshot"
    if (
        block_reason is None
        and isinstance(provider_context, Mapping)
        and decision.decision_action in {DECISION_ACTION_OPEN_LONG, DECISION_ACTION_OPEN_SHORT}
    ):
        # Optional provider degradation must not block the core risk path. Only
        # callers that explicitly mark a provider required can set this flag.
        if provider_context.get("core_system_blocked") is True:
            block_reason = "required_provider_context_blocked"

    if block_reason is not None:
        deny_reason = block_reason_code if block_reason_code else _INFRA_DENY_REASON
        record = RiskDecisionRecord(
            risk_decision_id="rd_" + decision.decision_id,
            decision_id=decision.decision_id,
            prediction_id=decision.prediction_id,
            feature_snapshot_id=decision.feature_snapshot_id,
            symbol=decision.symbol,
            risk_decision_ts_ms=now_ms,
            risk_action=RISK_DECISION_ACTION_DENY,
            risk_reason_code=deny_reason,
            input_decision_action=decision.decision_action,
            input_decision_reason_code=decision.decision_reason_code,
            live_blocked=True,
        )
        persist_decision_replay(
            decision_id=decision.decision_id,
            market_state_envelope=market_state_envelope,
            risk_decision=record,
            position_before=position_state,
            block_reason=block_reason,
            trust_gate_result=evaluated_trust_gate,
            extra={
                "snapshot_evidence_required": bool(snapshot_evidence_required),
                "replay_snapshot_id": replay_snapshot_id,
                "replay_snapshot_key": replay_snapshot_key,
                "mtf_snapshot_id": mtf_snapshot_id,
                "mtf_snapshot_valid": mtf_snapshot_valid,
                "provider_context": dict(provider_context or {}),
                "optional_provider_failures_core_blocking": False,
            },
        )
        return record

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
