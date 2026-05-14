from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_REASON_ALLOW_CLOSE_ONLY_INTELLIGENT_CLOSE_GUARD,
    RISK_DECISION_REASON_DENY_ADAPTIVE_MICROSTRUCTURE_TOXIC,
    RISK_DECISION_REASON_DENY_AUTO_DELEVERAGER_TRIGGERED,
    RISK_DECISION_REASON_DENY_HALT_MANAGER_ACTIVE,
    RISK_DECISION_REASON_DENY_KILL_SWITCH_ACTIVE,
    RISK_DECISION_REASON_DENY_MARGIN_GOVERNOR_LEVERAGE_INCREASE_BLOCKED,
    RISK_DECISION_REASON_DENY_PHASE_CONTROLLER_WARMUP,
    RISK_DECISION_REASON_DENY_REDUCE_ONLY_LATCH,
    RISK_DECISION_REASON_DENY_SHARED_RISK_BUDGET_EXHAUSTED,
)
from v2.backend.app.services.risk_gateway.adaptive_gate import evaluate_toxicity_block
from v2.backend.app.services.risk_gateway.auto_deleverager import evaluate_adl_state
from v2.backend.app.services.risk_gateway.halt_manager import evaluate_halt_state
from v2.backend.app.services.risk_gateway.intelligent_close_guard import evaluate_close_guard
from v2.backend.app.services.risk_gateway.kill_switch import evaluate_kill_switch_state
from v2.backend.app.services.risk_gateway.margin_governor import evaluate_margin_state
from v2.backend.app.services.risk_gateway.phase_controller import evaluate_phase_gate
from v2.backend.app.services.risk_gateway.reduce_only_latch import evaluate_latch_state
from v2.backend.app.services.risk_gateway.shared_risk_gate import evaluate_budget_state


def test_kill_switch_active_denies() -> None:
    result = evaluate_kill_switch_state(kill_switch_active=True)
    assert result.passed is False
    assert result.risk_reason_code == RISK_DECISION_REASON_DENY_KILL_SWITCH_ACTIVE
    assert result.live_blocked is True


def test_kill_switch_account_scope_uses_legacy_case_insensitive_match() -> None:
    result = evaluate_kill_switch_state(
        active=True,
        scope="ACCOUNT",
        account="Primary",
        account_query="primary",
    )
    assert result.passed is False
    assert result.risk_reason_code == RISK_DECISION_REASON_DENY_KILL_SWITCH_ACTIVE
    assert result.detail == "kill_switch_active_account_match"


def test_kill_switch_symbol_scope_allows_case_mismatch_when_symbol_differs() -> None:
    result = evaluate_kill_switch_state(
        active=True,
        scope="SYMBOL",
        symbol="ETHUSDT",
        symbol_query="BTCUSDT",
    )
    assert result.passed is True
    assert result.detail == "kill_switch_symbol_mismatch"


def test_halt_manager_active_denies() -> None:
    result = evaluate_halt_state(halt_active=True)
    assert result.passed is False
    assert result.risk_reason_code == RISK_DECISION_REASON_DENY_HALT_MANAGER_ACTIVE


def test_reduce_only_latch_denies_risk_increase() -> None:
    result = evaluate_latch_state(reduce_only_latch_active=True, increases_risk=True)
    assert result.passed is False
    assert result.risk_reason_code == RISK_DECISION_REASON_DENY_REDUCE_ONLY_LATCH


def test_intelligent_close_guard_returns_close_only_for_unproven_loss_close() -> None:
    result = evaluate_close_guard(close_allowed=None, loss_realizing_close=True)
    assert result.passed is False
    assert result.close_only is True
    assert result.gate_action == "close_only"
    assert result.risk_reason_code == RISK_DECISION_REASON_ALLOW_CLOSE_ONLY_INTELLIGENT_CLOSE_GUARD
    assert result.evidence_status == "missing"


def test_auto_deleverager_trigger_denies() -> None:
    result = evaluate_adl_state(deleverager_triggered=True)
    assert result.passed is False
    assert result.risk_reason_code == RISK_DECISION_REASON_DENY_AUTO_DELEVERAGER_TRIGGERED


def test_shared_risk_budget_exhaustion_denies() -> None:
    result = evaluate_budget_state(budget_remaining=0.5, budget_required=1.0)
    assert result.passed is False
    assert result.risk_reason_code == RISK_DECISION_REASON_DENY_SHARED_RISK_BUDGET_EXHAUSTED


def test_margin_governor_blocks_leverage_or_margin_mismatch() -> None:
    result = evaluate_margin_state(
        proposed_leverage=5.0,
        max_allowed_leverage=1.0,
        margin_mode="cross",
        required_margin_mode="isolated",
    )
    assert result.passed is False
    assert (
        result.risk_reason_code
        == RISK_DECISION_REASON_DENY_MARGIN_GOVERNOR_LEVERAGE_INCREASE_BLOCKED
    )


def test_phase_controller_warmup_denies() -> None:
    result = evaluate_phase_gate(warmup_complete=False)
    assert result.passed is False
    assert result.risk_reason_code == RISK_DECISION_REASON_DENY_PHASE_CONTROLLER_WARMUP


def test_adaptive_gate_microstructure_toxicity_denies() -> None:
    result = evaluate_toxicity_block(toxicity_score=0.91, toxic_threshold=0.65)
    assert result.passed is False
    assert result.gate_id == "microstructure_toxicity"
    assert result.risk_reason_code == RISK_DECISION_REASON_DENY_ADAPTIVE_MICROSTRUCTURE_TOXIC


def test_microstructure_toxicity_reduce_only_passes_even_when_score_extreme() -> None:
    result = evaluate_toxicity_block(toxicity_score=0.99, is_risk_add=False)
    assert result.passed is True
    assert result.gate_id == "microstructure_toxicity"
    assert result.detail == "toxicity_reduce_only_passes"


def test_all_legacy_gate_evaluators_clear_when_evidence_is_safe() -> None:
    results = (
        evaluate_kill_switch_state(kill_switch_active=False),
        evaluate_halt_state(halt_active=False),
        evaluate_latch_state(reduce_only_latch_active=False),
        evaluate_close_guard(close_allowed=True),
        evaluate_adl_state(deleverager_triggered=False),
        evaluate_budget_state(budget_remaining=3.0, budget_required=1.0),
        evaluate_margin_state(proposed_leverage=1.0, max_allowed_leverage=1.0),
        evaluate_phase_gate(warmup_complete=True),
        evaluate_toxicity_block(toxicity_score=0.2),
    )
    assert all(result.passed is True for result in results)
    assert all(result.live_blocked is True for result in results)
