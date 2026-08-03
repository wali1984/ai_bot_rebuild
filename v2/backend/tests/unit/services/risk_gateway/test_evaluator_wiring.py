from __future__ import annotations

from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_REASON_DENY_HALT_MANAGER_ACTIVE,
    RISK_DECISION_REASON_DENY_MARGIN_GOVERNOR_LEVERAGE_INCREASE_BLOCKED,
    RISK_DECISION_REASON_DENY_SHARED_RISK_BUDGET_EXHAUSTED,
)
from v2.backend.app.services.risk_gateway import assemble_risk_decision_record
from v2.backend.app.services.risk_gateway.service import evaluate_risk_evaluator_context


def _decision(action: str = "open_long") -> OrchestratorDecisionRecord:
    return OrchestratorDecisionRecord(
        decision_id=f"dec_{action}",
        prediction_id=f"pred_{action}",
        feature_snapshot_id=f"snap_{action}",
        symbol="BTCUSDT",
        decision_ts_ms=10,
        decision_action=action,
        decision_reason_code="proceed_long" if action == "open_long" else "proceed_short",
        input_prediction_direction="long" if action == "open_long" else "short",
        input_prediction_confidence_calibrated=0.85,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )


def test_risk_evaluator_context_runs_all_gates_on_allow_candidate() -> None:
    evaluations = evaluate_risk_evaluator_context(decision=_decision())

    gate_ids = {evaluation.gate_id for evaluation in evaluations}
    assert {
        "kill_switch",
        "halt_manager",
        "reduce_only_latch",
        "intelligent_close_guard",
        "auto_deleverager",
        "shared_risk_gate",
        "margin_governor",
        "phase_controller",
        "microstructure_toxicity",
    }.issubset(gate_ids)
    assert all(evaluation.live_blocked is True for evaluation in evaluations)


def test_kill_switch_context_denies_open_long() -> None:
    record = assemble_risk_decision_record(
        decision=_decision(),
        now_ms_clock=lambda: 1000,
        risk_context={"kill_switch_active": True},
    )

    assert record.risk_action == "deny"
    assert record.risk_reason_code == "deny_kill_switch_active"


def test_reduce_only_latch_context_denies_risk_add() -> None:
    record = assemble_risk_decision_record(
        decision=_decision("open_short"),
        now_ms_clock=lambda: 1000,
        risk_context={"reduce_only_latch_active": True, "is_risk_add": True},
    )

    assert record.risk_action == "deny"
    assert record.risk_reason_code == "deny_reduce_only_latch"


def test_halt_context_denies_open_long_before_allow() -> None:
    record = assemble_risk_decision_record(
        decision=_decision(),
        now_ms_clock=lambda: 1000,
        risk_context={"halt_active": True},
    )

    assert record.risk_action == "deny"
    assert record.risk_reason_code == RISK_DECISION_REASON_DENY_HALT_MANAGER_ACTIVE


def test_budget_context_denies_risk_add_before_allow() -> None:
    record = assemble_risk_decision_record(
        decision=_decision(),
        now_ms_clock=lambda: 1000,
        risk_context={
            "budget_remaining": 0.0,
            "budget_required": 1.0,
            "is_risk_add": True,
        },
    )

    assert record.risk_action == "deny"
    assert record.risk_reason_code == RISK_DECISION_REASON_DENY_SHARED_RISK_BUDGET_EXHAUSTED


def test_margin_context_denies_leverage_increase_before_allow() -> None:
    record = assemble_risk_decision_record(
        decision=_decision(),
        now_ms_clock=lambda: 1000,
        risk_context={
            "proposed_leverage": 2.0,
            "max_allowed_leverage": 1.0,
        },
    )

    assert record.risk_action == "deny"
    assert (
        record.risk_reason_code
        == RISK_DECISION_REASON_DENY_MARGIN_GOVERNOR_LEVERAGE_INCREASE_BLOCKED
    )
