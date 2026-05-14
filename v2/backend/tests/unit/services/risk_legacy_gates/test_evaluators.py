"""Real, non-skipped unit tests for the V2 risk-gateway legacy gate
callables introduced by
``claude_port_v2_risk_gateway_legacy_gate_implementations_from_legacy_action_map``.

These tests invoke the real V2 callables under
``v2.backend.app.services.risk_legacy_gates`` and assert deny / allow /
close-only behavior per gate, plus the fail-closed evidence-missing path
and the ``live_blocked=True`` invariant.

No legacy module is imported here. No Redis. No exchange. No file I/O.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from v2.backend.app.services.risk_legacy_gates import (
    AutoDeleveragerState,
    BudgetState,
    CloseGuardState,
    GATE_NAME_AUTO_DELEVERAGER,
    GATE_NAME_HALT_MANAGER,
    GATE_NAME_INTELLIGENT_CLOSE_GUARD,
    GATE_NAME_KILL_SWITCH,
    GATE_NAME_MARGIN_GOVERNOR,
    GATE_NAME_MICROSTRUCTURE_TOXICITY,
    GATE_NAME_PHASE_CONTROLLER,
    GATE_NAME_REDUCE_ONLY_LATCH,
    GATE_NAME_SHARED_RISK_GATE,
    HaltState,
    KillSwitchState,
    LatchState,
    LegacyGateVerdict,
    MarginGovernorState,
    PhaseGateState,
    RiskLegacyGatesServiceError,
    ToxicityState,
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


def _clock() -> int:
    return 1715731200000


# ---------------------------------------------------------------------------
# kill_switch
# ---------------------------------------------------------------------------


def test_kill_switch_evidence_missing_denies() -> None:
    v = evaluate_kill_switch_state(
        KillSwitchState(
            evidence_present=False,
            active=False,
            scope="",
            payload_corrupt=False,
            account="",
            account_query="",
            symbol="",
            symbol_query="",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_kill_switch_evidence_missing"
    assert v.gate_name == GATE_NAME_KILL_SWITCH
    assert v.live_blocked is True


def test_kill_switch_inactive_allows() -> None:
    v = evaluate_kill_switch_state(
        KillSwitchState(
            evidence_present=True,
            active=False,
            scope="",
            payload_corrupt=False,
            account="",
            account_query="",
            symbol="",
            symbol_query="",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "allow"
    assert v.reason_code == "allow_kill_switch_inactive"
    assert v.live_blocked is True


def test_kill_switch_global_denies() -> None:
    v = evaluate_kill_switch_state(
        KillSwitchState(
            evidence_present=True,
            active=True,
            scope="global",
            payload_corrupt=False,
            account="",
            account_query="",
            symbol="",
            symbol_query="",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_kill_switch_active_global"


def test_kill_switch_legacy_uppercase_scope_denies() -> None:
    v = evaluate_kill_switch_state(
        KillSwitchState(
            evidence_present=True,
            active=True,
            scope="GLOBAL",
            payload_corrupt=False,
            account="",
            account_query="",
            symbol="",
            symbol_query="",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_kill_switch_active_global"


def test_kill_switch_account_match_denies() -> None:
    v = evaluate_kill_switch_state(
        KillSwitchState(
            evidence_present=True,
            active=True,
            scope="account",
            payload_corrupt=False,
            account="primary",
            account_query="primary",
            symbol="",
            symbol_query="",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_kill_switch_active_account"


def test_kill_switch_account_match_is_case_insensitive_like_legacy() -> None:
    v = evaluate_kill_switch_state(
        KillSwitchState(
            evidence_present=True,
            active=True,
            scope="ACCOUNT",
            payload_corrupt=False,
            account="Primary",
            account_query="primary",
            symbol="",
            symbol_query="",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_kill_switch_active_account"


def test_kill_switch_account_mismatch_allows() -> None:
    v = evaluate_kill_switch_state(
        KillSwitchState(
            evidence_present=True,
            active=True,
            scope="account",
            payload_corrupt=False,
            account="primary",
            account_query="asjad",
            symbol="",
            symbol_query="",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "allow"
    assert v.reason_code == "allow_kill_switch_inactive"


def test_kill_switch_symbol_match_denies() -> None:
    v = evaluate_kill_switch_state(
        KillSwitchState(
            evidence_present=True,
            active=True,
            scope="symbol",
            payload_corrupt=False,
            account="",
            account_query="",
            symbol="BTCUSDT",
            symbol_query="BTCUSDT",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_kill_switch_active_symbol"


def test_kill_switch_symbol_match_is_case_insensitive_like_legacy() -> None:
    v = evaluate_kill_switch_state(
        KillSwitchState(
            evidence_present=True,
            active=True,
            scope="SYMBOL",
            payload_corrupt=False,
            account="",
            account_query="",
            symbol="btcusdt",
            symbol_query="BTCUSDT",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_kill_switch_active_symbol"


def test_kill_switch_unknown_scope_fails_closed_like_legacy_default() -> None:
    v = evaluate_kill_switch_state(
        KillSwitchState(
            evidence_present=True,
            active=True,
            scope="UNKNOWN_SCOPE",
            payload_corrupt=False,
            account="",
            account_query="",
            symbol="",
            symbol_query="",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_kill_switch_evidence_missing"


def test_kill_switch_corrupt_denies() -> None:
    v = evaluate_kill_switch_state(
        KillSwitchState(
            evidence_present=True,
            active=True,
            scope="global",
            payload_corrupt=True,
            account="",
            account_query="",
            symbol="",
            symbol_query="",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_kill_switch_corrupt"


# ---------------------------------------------------------------------------
# halt_manager
# ---------------------------------------------------------------------------


def test_halt_evidence_missing_denies() -> None:
    v = evaluate_halt_state(
        HaltState(evidence_present=False, halted=False, halt_code=""),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_halt_evidence_missing"
    assert v.gate_name == GATE_NAME_HALT_MANAGER


def test_halt_inactive_allows() -> None:
    v = evaluate_halt_state(
        HaltState(evidence_present=True, halted=False, halt_code=""),
        now_ms_clock=_clock,
    )
    assert v.action == "allow"
    assert v.reason_code == "allow_halt_inactive"


def test_halt_kill_switch_active_denies() -> None:
    v = evaluate_halt_state(
        HaltState(
            evidence_present=True,
            halted=True,
            halt_code="kill_switch_active",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_halt_active"


def test_halt_fail_storm_denies() -> None:
    v = evaluate_halt_state(
        HaltState(
            evidence_present=True, halted=True, halt_code="fail_storm"
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_halt_fail_storm"


def test_halt_mu_breach_sustained_denies() -> None:
    v = evaluate_halt_state(
        HaltState(
            evidence_present=True,
            halted=True,
            halt_code="mu_breach_sustained",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_halt_mu_breach_sustained"


# ---------------------------------------------------------------------------
# reduce_only_latch
# ---------------------------------------------------------------------------


def test_latch_evidence_missing_denies() -> None:
    v = evaluate_latch_state(
        LatchState(
            evidence_present=False, latch_active=False, is_risk_add=True
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_latch_evidence_missing"
    assert v.gate_name == GATE_NAME_REDUCE_ONLY_LATCH


def test_latch_inactive_allows() -> None:
    v = evaluate_latch_state(
        LatchState(
            evidence_present=True, latch_active=False, is_risk_add=True
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "allow"
    assert v.reason_code == "allow_latch_inactive"


def test_latch_active_risk_add_close_only() -> None:
    v = evaluate_latch_state(
        LatchState(
            evidence_present=True, latch_active=True, is_risk_add=True
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "close_only"
    assert v.reason_code == "close_only_latch_active"


def test_latch_active_reduce_allows() -> None:
    v = evaluate_latch_state(
        LatchState(
            evidence_present=True, latch_active=True, is_risk_add=False
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "allow"
    assert v.reason_code == "allow_latch_inactive"


# ---------------------------------------------------------------------------
# intelligent_close_guard
# ---------------------------------------------------------------------------


def test_close_guard_evidence_missing_denies() -> None:
    v = evaluate_close_guard(
        CloseGuardState(evidence_present=False, guard_action=""),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_close_guard_evidence_missing"
    assert v.gate_name == GATE_NAME_INTELLIGENT_CLOSE_GUARD


def test_close_guard_allow_close_allows() -> None:
    v = evaluate_close_guard(
        CloseGuardState(
            evidence_present=True, guard_action="allow_close"
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "allow"
    assert v.reason_code == "allow_close_guard_allow_close"


def test_close_guard_defer_close_denies() -> None:
    v = evaluate_close_guard(
        CloseGuardState(
            evidence_present=True, guard_action="defer_close"
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_close_guard_defer_close"


def test_close_guard_emergency_bypass_close_only() -> None:
    v = evaluate_close_guard(
        CloseGuardState(
            evidence_present=True, guard_action="emergency_bypass"
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "close_only"
    assert v.reason_code == "close_only_close_guard_emergency_bypass"


# ---------------------------------------------------------------------------
# auto_deleverager
# ---------------------------------------------------------------------------


def test_adl_evidence_missing_denies() -> None:
    v = evaluate_adl_state(
        AutoDeleveragerState(evidence_present=False, cap_breach=""),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_adl_evidence_missing"
    assert v.gate_name == GATE_NAME_AUTO_DELEVERAGER


def test_adl_inactive_allows() -> None:
    v = evaluate_adl_state(
        AutoDeleveragerState(evidence_present=True, cap_breach=""),
        now_ms_clock=_clock,
    )
    assert v.action == "allow"
    assert v.reason_code == "allow_adl_inactive"


def test_adl_account_breach_close_only() -> None:
    v = evaluate_adl_state(
        AutoDeleveragerState(evidence_present=True, cap_breach="account"),
        now_ms_clock=_clock,
    )
    assert v.action == "close_only"
    assert v.reason_code == "close_only_adl_account_cap_breach"


def test_adl_mu_breach_close_only() -> None:
    v = evaluate_adl_state(
        AutoDeleveragerState(evidence_present=True, cap_breach="mu"),
        now_ms_clock=_clock,
    )
    assert v.action == "close_only"
    assert v.reason_code == "close_only_adl_mu_cap_breach"


def test_adl_symbol_breach_close_only() -> None:
    v = evaluate_adl_state(
        AutoDeleveragerState(evidence_present=True, cap_breach="symbol"),
        now_ms_clock=_clock,
    )
    assert v.action == "close_only"
    assert v.reason_code == "close_only_adl_symbol_cap_breach"


# ---------------------------------------------------------------------------
# shared_risk_gate (budget)
# ---------------------------------------------------------------------------


def test_budget_evidence_missing_denies() -> None:
    v = evaluate_budget_state(
        BudgetState(
            evidence_present=False,
            is_risk_add=True,
            is_reduce=False,
            block_code="",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_budget_evidence_missing"
    assert v.gate_name == GATE_NAME_SHARED_RISK_GATE


def test_budget_reduce_allows() -> None:
    v = evaluate_budget_state(
        BudgetState(
            evidence_present=True,
            is_risk_add=False,
            is_reduce=True,
            block_code="cadence",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "allow"
    assert v.reason_code == "allow_budget_within_limits"


def test_budget_risk_add_no_block_allows() -> None:
    v = evaluate_budget_state(
        BudgetState(
            evidence_present=True,
            is_risk_add=True,
            is_reduce=False,
            block_code="",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "allow"
    assert v.reason_code == "allow_budget_within_limits"


def test_budget_cadence_block_denies() -> None:
    v = evaluate_budget_state(
        BudgetState(
            evidence_present=True,
            is_risk_add=True,
            is_reduce=False,
            block_code="cadence",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_budget_cadence_block"


def test_budget_max_symbols_block_denies() -> None:
    v = evaluate_budget_state(
        BudgetState(
            evidence_present=True,
            is_risk_add=True,
            is_reduce=False,
            block_code="max_symbols",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_budget_max_symbols_block"


def test_budget_reversal_block_denies() -> None:
    v = evaluate_budget_state(
        BudgetState(
            evidence_present=True,
            is_risk_add=True,
            is_reduce=False,
            block_code="reversal",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_budget_reversal_block"


def test_budget_emergency_margin_block_denies() -> None:
    v = evaluate_budget_state(
        BudgetState(
            evidence_present=True,
            is_risk_add=True,
            is_reduce=False,
            block_code="emergency_margin",
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_budget_emergency_margin_block"


# ---------------------------------------------------------------------------
# margin_governor
# ---------------------------------------------------------------------------


def test_margin_evidence_missing_denies() -> None:
    v = evaluate_margin_state(
        MarginGovernorState(evidence_present=False, verdict_action=""),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_margin_evidence_missing"
    assert v.gate_name == GATE_NAME_MARGIN_GOVERNOR


def test_margin_allow_allows() -> None:
    v = evaluate_margin_state(
        MarginGovernorState(
            evidence_present=True, verdict_action="allow"
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "allow"
    assert v.reason_code == "allow_margin_within_caps"


def test_margin_block_account_denies() -> None:
    v = evaluate_margin_state(
        MarginGovernorState(
            evidence_present=True, verdict_action="block_account"
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_margin_account_breach"


def test_margin_block_symbol_denies() -> None:
    v = evaluate_margin_state(
        MarginGovernorState(
            evidence_present=True, verdict_action="block_symbol"
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_margin_symbol_breach"


def test_margin_deleverage_close_only() -> None:
    v = evaluate_margin_state(
        MarginGovernorState(
            evidence_present=True, verdict_action="deleverage"
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "close_only"
    assert v.reason_code == "close_only_margin_deleverage_required"


# ---------------------------------------------------------------------------
# phase_controller
# ---------------------------------------------------------------------------


def test_phase_evidence_missing_denies() -> None:
    v = evaluate_phase_gate(
        PhaseGateState(evidence_present=False, ramp_limit_breach=""),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_phase_evidence_missing"
    assert v.gate_name == GATE_NAME_PHASE_CONTROLLER


def test_phase_within_limits_allows() -> None:
    v = evaluate_phase_gate(
        PhaseGateState(evidence_present=True, ramp_limit_breach=""),
        now_ms_clock=_clock,
    )
    assert v.action == "allow"
    assert v.reason_code == "allow_phase_within_ramp_limits"


@pytest.mark.parametrize(
    "breach, reason",
    [
        ("max_mu", "deny_phase_max_mu_exceeded"),
        ("min_free_margin_ratio", "deny_phase_min_free_margin_violated"),
        ("max_positions", "deny_phase_max_positions_exceeded"),
        ("per_symbol_margin", "deny_phase_per_symbol_margin_exceeded"),
        ("equity_missing_or_nan", "deny_phase_equity_missing_or_nan"),
    ],
)
def test_phase_breaches_deny(breach: str, reason: str) -> None:
    v = evaluate_phase_gate(
        PhaseGateState(
            evidence_present=True, ramp_limit_breach=breach
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == reason


# ---------------------------------------------------------------------------
# microstructure_toxicity
# ---------------------------------------------------------------------------


def test_toxicity_evidence_missing_denies() -> None:
    v = evaluate_toxicity_block(
        ToxicityState(
            evidence_present=False,
            is_risk_add=True,
            score=0.0,
            extreme_threshold=0.85,
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_toxicity_evidence_missing"
    assert v.gate_name == GATE_NAME_MICROSTRUCTURE_TOXICITY


def test_toxicity_within_threshold_allows() -> None:
    v = evaluate_toxicity_block(
        ToxicityState(
            evidence_present=True,
            is_risk_add=True,
            score=0.50,
            extreme_threshold=0.85,
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "allow"
    assert v.reason_code == "allow_toxicity_within_threshold"


def test_toxicity_extreme_denies() -> None:
    v = evaluate_toxicity_block(
        ToxicityState(
            evidence_present=True,
            is_risk_add=True,
            score=0.90,
            extreme_threshold=0.85,
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "deny"
    assert v.reason_code == "deny_toxicity_extreme_block"


def test_toxicity_extreme_but_reduce_allows() -> None:
    v = evaluate_toxicity_block(
        ToxicityState(
            evidence_present=True,
            is_risk_add=False,
            score=0.99,
            extreme_threshold=0.85,
        ),
        now_ms_clock=_clock,
    )
    assert v.action == "allow"
    assert v.reason_code == "allow_toxicity_within_threshold"


# ---------------------------------------------------------------------------
# cross-cutting invariants
# ---------------------------------------------------------------------------


def test_all_evaluators_carry_live_blocked_true() -> None:
    cases = [
        evaluate_kill_switch_state(
            KillSwitchState(
                evidence_present=True,
                active=False,
                scope="",
                payload_corrupt=False,
                account="",
                account_query="",
                symbol="",
                symbol_query="",
            ),
            now_ms_clock=_clock,
        ),
        evaluate_halt_state(
            HaltState(
                evidence_present=True, halted=False, halt_code=""
            ),
            now_ms_clock=_clock,
        ),
        evaluate_latch_state(
            LatchState(
                evidence_present=True,
                latch_active=False,
                is_risk_add=True,
            ),
            now_ms_clock=_clock,
        ),
        evaluate_close_guard(
            CloseGuardState(
                evidence_present=True, guard_action="allow_close"
            ),
            now_ms_clock=_clock,
        ),
        evaluate_adl_state(
            AutoDeleveragerState(
                evidence_present=True, cap_breach=""
            ),
            now_ms_clock=_clock,
        ),
        evaluate_budget_state(
            BudgetState(
                evidence_present=True,
                is_risk_add=True,
                is_reduce=False,
                block_code="",
            ),
            now_ms_clock=_clock,
        ),
        evaluate_margin_state(
            MarginGovernorState(
                evidence_present=True, verdict_action="allow"
            ),
            now_ms_clock=_clock,
        ),
        evaluate_phase_gate(
            PhaseGateState(
                evidence_present=True, ramp_limit_breach=""
            ),
            now_ms_clock=_clock,
        ),
        evaluate_toxicity_block(
            ToxicityState(
                evidence_present=True,
                is_risk_add=True,
                score=0.10,
                extreme_threshold=0.85,
            ),
            now_ms_clock=_clock,
        ),
    ]
    for v in cases:
        assert isinstance(v, LegacyGateVerdict)
        assert v.live_blocked is True
        assert len(v.legacy_source_sha256) == 64
        assert v.legacy_source_path.startswith(
            "v2/legacy_preserved/full_runtime_closure/risk/"
        )


def test_now_ms_clock_must_be_int() -> None:
    with pytest.raises(RiskLegacyGatesServiceError):
        evaluate_halt_state(
            HaltState(
                evidence_present=True, halted=False, halt_code=""
            ),
            now_ms_clock=lambda: "not_an_int",  # type: ignore[arg-type, return-value]
        )


def test_now_ms_clock_must_be_nonnegative() -> None:
    with pytest.raises(RiskLegacyGatesServiceError):
        evaluate_halt_state(
            HaltState(
                evidence_present=True, halted=False, halt_code=""
            ),
            now_ms_clock=lambda: -1,
        )


def test_evaluator_rejects_wrong_state_type() -> None:
    with pytest.raises(RiskLegacyGatesServiceError):
        evaluate_halt_state(
            object(),  # type: ignore[arg-type]
            now_ms_clock=_clock,
        )


def test_verdict_rejects_live_blocked_false() -> None:
    with pytest.raises(RiskLegacyGatesServiceError):
        LegacyGateVerdict(
            gate_name=GATE_NAME_HALT_MANAGER,
            action="allow",
            reason_code="allow_halt_inactive",
            legacy_source_path="v2/legacy_preserved/full_runtime_closure/risk/halt_manager.py",
            legacy_source_sha256="49504d73a9fef319eb0ac6282d571492714a62526bc1c9849148685ad7eac314",
            evaluated_at_ms=1,
            live_blocked=False,
        )


def test_inputs_reject_wrong_types() -> None:
    with pytest.raises(RiskLegacyGatesServiceError):
        ToxicityState(
            evidence_present=True,
            is_risk_add=True,
            score=1.5,
            extreme_threshold=0.85,
        )
