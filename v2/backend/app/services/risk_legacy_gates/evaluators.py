from __future__ import annotations

from collections.abc import Callable

from .errors import RiskLegacyGatesServiceError
from .inputs import (
    AutoDeleveragerState,
    BudgetState,
    CloseGuardState,
    HaltState,
    KillSwitchState,
    LatchState,
    MarginGovernorState,
    PhaseGateState,
    ToxicityState,
)
from .verdict import (
    GATE_NAME_AUTO_DELEVERAGER,
    GATE_NAME_HALT_MANAGER,
    GATE_NAME_INTELLIGENT_CLOSE_GUARD,
    GATE_NAME_KILL_SWITCH,
    GATE_NAME_MARGIN_GOVERNOR,
    GATE_NAME_MICROSTRUCTURE_TOXICITY,
    GATE_NAME_PHASE_CONTROLLER,
    GATE_NAME_REDUCE_ONLY_LATCH,
    GATE_NAME_SHARED_RISK_GATE,
    LEGACY_GATE_ACTION_ALLOW,
    LEGACY_GATE_ACTION_CLOSE_ONLY,
    LEGACY_GATE_ACTION_DENY,
    LegacyGateVerdict,
)


_LEGACY_SOURCE_PATHS = {
    GATE_NAME_KILL_SWITCH: "v2/legacy_preserved/full_runtime_closure/risk/kill_switch.py",
    GATE_NAME_HALT_MANAGER: "v2/legacy_preserved/full_runtime_closure/risk/halt_manager.py",
    GATE_NAME_REDUCE_ONLY_LATCH: "v2/legacy_preserved/full_runtime_closure/risk/reduce_only_latch.py",
    GATE_NAME_INTELLIGENT_CLOSE_GUARD: "v2/legacy_preserved/full_runtime_closure/risk/intelligent_close_guard.py",
    GATE_NAME_AUTO_DELEVERAGER: "v2/legacy_preserved/full_runtime_closure/risk/auto_deleverager.py",
    GATE_NAME_SHARED_RISK_GATE: "v2/legacy_preserved/full_runtime_closure/risk/shared_risk_gate.py",
    GATE_NAME_MARGIN_GOVERNOR: "v2/legacy_preserved/full_runtime_closure/risk/margin_governor.py",
    GATE_NAME_PHASE_CONTROLLER: "v2/legacy_preserved/full_runtime_closure/risk/phase_controller.py",
    GATE_NAME_MICROSTRUCTURE_TOXICITY: "v2/legacy_preserved/full_runtime_closure/risk/microstructure_toxicity.py",
}

_LEGACY_SOURCE_SHA256 = {
    GATE_NAME_KILL_SWITCH: "bf730c6fa425097aa0c246dfbab88e4f8d158afdd606a905c8f9e3c7695df59e",
    GATE_NAME_HALT_MANAGER: "49504d73a9fef319eb0ac6282d571492714a62526bc1c9849148685ad7eac314",
    GATE_NAME_REDUCE_ONLY_LATCH: "e0dc68486a5cc2fa0fc0ea1d1197f66373f8c090deb889a403257e187c7ac611",
    GATE_NAME_INTELLIGENT_CLOSE_GUARD: "7edf6d5eca3e8654bc17f0fad22831e4daedb411138d576904a29ab0a352c3ee",
    GATE_NAME_AUTO_DELEVERAGER: "76652e99ec0b0717a3bfea887c25f78746df7765ba3f5e4eff6a21d0e820a377",
    GATE_NAME_SHARED_RISK_GATE: "62c2403f2cf2ce5dec71522b919f1db6a2f6908e338903e359e021c75c59dd7f",
    GATE_NAME_MARGIN_GOVERNOR: "e8448d2ee70697a97fbb4af27555adabe2af590d8185ebfc644b965070376eee",
    GATE_NAME_PHASE_CONTROLLER: "ecd566ca7537551a9e6e267da4880a41764d346a1d43137d4088003951211ee1",
    GATE_NAME_MICROSTRUCTURE_TOXICITY: "5103e3078e15734eaca310e9ae58dd8e89725ebf4317a98313f078c8bd74beef",
}


def _resolve_now_ms(now_ms_clock: Callable[[], int]) -> int:
    if not callable(now_ms_clock):
        raise RiskLegacyGatesServiceError(
            "must_be_callable", field="now_ms_clock"
        )
    now_ms = now_ms_clock()
    if type(now_ms) is not int:
        raise RiskLegacyGatesServiceError(
            "must_be_int", field="now_ms_clock"
        )
    if now_ms < 0:
        raise RiskLegacyGatesServiceError(
            "must_be_nonnegative", field="now_ms_clock"
        )
    return now_ms


def _build(
    *,
    gate_name: str,
    action: str,
    reason_code: str,
    evaluated_at_ms: int,
) -> LegacyGateVerdict:
    return LegacyGateVerdict(
        gate_name=gate_name,
        action=action,
        reason_code=reason_code,
        legacy_source_path=_LEGACY_SOURCE_PATHS[gate_name],
        legacy_source_sha256=_LEGACY_SOURCE_SHA256[gate_name],
        evaluated_at_ms=evaluated_at_ms,
        live_blocked=True,
    )


def evaluate_kill_switch_state(
    state: KillSwitchState,
    *,
    now_ms_clock: Callable[[], int],
) -> LegacyGateVerdict:
    if not isinstance(state, KillSwitchState):
        raise RiskLegacyGatesServiceError(
            "must_be_kill_switch_state", field="state"
        )
    now_ms = _resolve_now_ms(now_ms_clock)

    if not state.evidence_present:
        return _build(
            gate_name=GATE_NAME_KILL_SWITCH,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_kill_switch_evidence_missing",
            evaluated_at_ms=now_ms,
        )
    if not state.active:
        return _build(
            gate_name=GATE_NAME_KILL_SWITCH,
            action=LEGACY_GATE_ACTION_ALLOW,
            reason_code="allow_kill_switch_inactive",
            evaluated_at_ms=now_ms,
        )
    if state.payload_corrupt:
        return _build(
            gate_name=GATE_NAME_KILL_SWITCH,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_kill_switch_corrupt",
            evaluated_at_ms=now_ms,
        )
    if state.scope == "" or state.scope == "GLOBAL":
        return _build(
            gate_name=GATE_NAME_KILL_SWITCH,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_kill_switch_active_global",
            evaluated_at_ms=now_ms,
        )
    if state.scope == "ACCOUNT":
        if state.account_query == "":
            return _build(
                gate_name=GATE_NAME_KILL_SWITCH,
                action=LEGACY_GATE_ACTION_DENY,
                reason_code="deny_kill_switch_active_account",
                evaluated_at_ms=now_ms,
            )
        if state.account.lower() == state.account_query.lower():
            return _build(
                gate_name=GATE_NAME_KILL_SWITCH,
                action=LEGACY_GATE_ACTION_DENY,
                reason_code="deny_kill_switch_active_account",
                evaluated_at_ms=now_ms,
            )
        return _build(
            gate_name=GATE_NAME_KILL_SWITCH,
            action=LEGACY_GATE_ACTION_ALLOW,
            reason_code="allow_kill_switch_inactive",
            evaluated_at_ms=now_ms,
        )
    if state.scope == "SYMBOL":
        if state.symbol_query == "":
            return _build(
                gate_name=GATE_NAME_KILL_SWITCH,
                action=LEGACY_GATE_ACTION_DENY,
                reason_code="deny_kill_switch_active_symbol",
                evaluated_at_ms=now_ms,
            )
        if state.symbol.upper() == state.symbol_query.upper():
            return _build(
                gate_name=GATE_NAME_KILL_SWITCH,
                action=LEGACY_GATE_ACTION_DENY,
                reason_code="deny_kill_switch_active_symbol",
                evaluated_at_ms=now_ms,
            )
        return _build(
            gate_name=GATE_NAME_KILL_SWITCH,
            action=LEGACY_GATE_ACTION_ALLOW,
            reason_code="allow_kill_switch_inactive",
            evaluated_at_ms=now_ms,
        )
    return _build(
        gate_name=GATE_NAME_KILL_SWITCH,
        action=LEGACY_GATE_ACTION_DENY,
        reason_code="deny_kill_switch_evidence_missing",
        evaluated_at_ms=now_ms,
    )


def evaluate_halt_state(
    state: HaltState,
    *,
    now_ms_clock: Callable[[], int],
) -> LegacyGateVerdict:
    if not isinstance(state, HaltState):
        raise RiskLegacyGatesServiceError(
            "must_be_halt_state", field="state"
        )
    now_ms = _resolve_now_ms(now_ms_clock)

    if not state.evidence_present:
        return _build(
            gate_name=GATE_NAME_HALT_MANAGER,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_halt_evidence_missing",
            evaluated_at_ms=now_ms,
        )
    if not state.halted:
        return _build(
            gate_name=GATE_NAME_HALT_MANAGER,
            action=LEGACY_GATE_ACTION_ALLOW,
            reason_code="allow_halt_inactive",
            evaluated_at_ms=now_ms,
        )
    if state.halt_code == "kill_switch_active":
        return _build(
            gate_name=GATE_NAME_HALT_MANAGER,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_halt_active",
            evaluated_at_ms=now_ms,
        )
    if state.halt_code == "fail_storm":
        return _build(
            gate_name=GATE_NAME_HALT_MANAGER,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_halt_fail_storm",
            evaluated_at_ms=now_ms,
        )
    if state.halt_code == "mu_breach_sustained":
        return _build(
            gate_name=GATE_NAME_HALT_MANAGER,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_halt_mu_breach_sustained",
            evaluated_at_ms=now_ms,
        )
    return _build(
        gate_name=GATE_NAME_HALT_MANAGER,
        action=LEGACY_GATE_ACTION_DENY,
        reason_code="deny_halt_evidence_missing",
        evaluated_at_ms=now_ms,
    )


def evaluate_latch_state(
    state: LatchState,
    *,
    now_ms_clock: Callable[[], int],
) -> LegacyGateVerdict:
    if not isinstance(state, LatchState):
        raise RiskLegacyGatesServiceError(
            "must_be_latch_state", field="state"
        )
    now_ms = _resolve_now_ms(now_ms_clock)

    if not state.evidence_present:
        return _build(
            gate_name=GATE_NAME_REDUCE_ONLY_LATCH,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_latch_evidence_missing",
            evaluated_at_ms=now_ms,
        )
    if not state.latch_active:
        return _build(
            gate_name=GATE_NAME_REDUCE_ONLY_LATCH,
            action=LEGACY_GATE_ACTION_ALLOW,
            reason_code="allow_latch_inactive",
            evaluated_at_ms=now_ms,
        )
    if state.is_risk_add:
        return _build(
            gate_name=GATE_NAME_REDUCE_ONLY_LATCH,
            action=LEGACY_GATE_ACTION_CLOSE_ONLY,
            reason_code="close_only_latch_active",
            evaluated_at_ms=now_ms,
        )
    return _build(
        gate_name=GATE_NAME_REDUCE_ONLY_LATCH,
        action=LEGACY_GATE_ACTION_ALLOW,
        reason_code="allow_latch_inactive",
        evaluated_at_ms=now_ms,
    )


def evaluate_close_guard(
    state: CloseGuardState,
    *,
    now_ms_clock: Callable[[], int],
) -> LegacyGateVerdict:
    if not isinstance(state, CloseGuardState):
        raise RiskLegacyGatesServiceError(
            "must_be_close_guard_state", field="state"
        )
    now_ms = _resolve_now_ms(now_ms_clock)

    if not state.evidence_present:
        return _build(
            gate_name=GATE_NAME_INTELLIGENT_CLOSE_GUARD,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_close_guard_evidence_missing",
            evaluated_at_ms=now_ms,
        )
    if state.guard_action == "allow_close":
        return _build(
            gate_name=GATE_NAME_INTELLIGENT_CLOSE_GUARD,
            action=LEGACY_GATE_ACTION_ALLOW,
            reason_code="allow_close_guard_allow_close",
            evaluated_at_ms=now_ms,
        )
    if state.guard_action == "defer_close":
        return _build(
            gate_name=GATE_NAME_INTELLIGENT_CLOSE_GUARD,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_close_guard_defer_close",
            evaluated_at_ms=now_ms,
        )
    if state.guard_action == "emergency_bypass":
        return _build(
            gate_name=GATE_NAME_INTELLIGENT_CLOSE_GUARD,
            action=LEGACY_GATE_ACTION_CLOSE_ONLY,
            reason_code="close_only_close_guard_emergency_bypass",
            evaluated_at_ms=now_ms,
        )
    return _build(
        gate_name=GATE_NAME_INTELLIGENT_CLOSE_GUARD,
        action=LEGACY_GATE_ACTION_DENY,
        reason_code="deny_close_guard_evidence_missing",
        evaluated_at_ms=now_ms,
    )


def evaluate_adl_state(
    state: AutoDeleveragerState,
    *,
    now_ms_clock: Callable[[], int],
) -> LegacyGateVerdict:
    if not isinstance(state, AutoDeleveragerState):
        raise RiskLegacyGatesServiceError(
            "must_be_auto_deleverager_state", field="state"
        )
    now_ms = _resolve_now_ms(now_ms_clock)

    if not state.evidence_present:
        return _build(
            gate_name=GATE_NAME_AUTO_DELEVERAGER,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_adl_evidence_missing",
            evaluated_at_ms=now_ms,
        )
    if state.cap_breach == "":
        return _build(
            gate_name=GATE_NAME_AUTO_DELEVERAGER,
            action=LEGACY_GATE_ACTION_ALLOW,
            reason_code="allow_adl_inactive",
            evaluated_at_ms=now_ms,
        )
    if state.cap_breach == "account":
        return _build(
            gate_name=GATE_NAME_AUTO_DELEVERAGER,
            action=LEGACY_GATE_ACTION_CLOSE_ONLY,
            reason_code="close_only_adl_account_cap_breach",
            evaluated_at_ms=now_ms,
        )
    if state.cap_breach == "mu":
        return _build(
            gate_name=GATE_NAME_AUTO_DELEVERAGER,
            action=LEGACY_GATE_ACTION_CLOSE_ONLY,
            reason_code="close_only_adl_mu_cap_breach",
            evaluated_at_ms=now_ms,
        )
    if state.cap_breach == "symbol":
        return _build(
            gate_name=GATE_NAME_AUTO_DELEVERAGER,
            action=LEGACY_GATE_ACTION_CLOSE_ONLY,
            reason_code="close_only_adl_symbol_cap_breach",
            evaluated_at_ms=now_ms,
        )
    return _build(
        gate_name=GATE_NAME_AUTO_DELEVERAGER,
        action=LEGACY_GATE_ACTION_DENY,
        reason_code="deny_adl_evidence_missing",
        evaluated_at_ms=now_ms,
    )


def evaluate_budget_state(
    state: BudgetState,
    *,
    now_ms_clock: Callable[[], int],
) -> LegacyGateVerdict:
    if not isinstance(state, BudgetState):
        raise RiskLegacyGatesServiceError(
            "must_be_budget_state", field="state"
        )
    now_ms = _resolve_now_ms(now_ms_clock)

    if not state.evidence_present:
        return _build(
            gate_name=GATE_NAME_SHARED_RISK_GATE,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_budget_evidence_missing",
            evaluated_at_ms=now_ms,
        )
    if state.is_reduce and not state.is_risk_add:
        return _build(
            gate_name=GATE_NAME_SHARED_RISK_GATE,
            action=LEGACY_GATE_ACTION_ALLOW,
            reason_code="allow_budget_within_limits",
            evaluated_at_ms=now_ms,
        )
    if not state.is_risk_add:
        return _build(
            gate_name=GATE_NAME_SHARED_RISK_GATE,
            action=LEGACY_GATE_ACTION_ALLOW,
            reason_code="allow_budget_within_limits",
            evaluated_at_ms=now_ms,
        )
    if state.block_code == "":
        return _build(
            gate_name=GATE_NAME_SHARED_RISK_GATE,
            action=LEGACY_GATE_ACTION_ALLOW,
            reason_code="allow_budget_within_limits",
            evaluated_at_ms=now_ms,
        )
    if state.block_code == "cadence":
        return _build(
            gate_name=GATE_NAME_SHARED_RISK_GATE,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_budget_cadence_block",
            evaluated_at_ms=now_ms,
        )
    if state.block_code == "max_symbols":
        return _build(
            gate_name=GATE_NAME_SHARED_RISK_GATE,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_budget_max_symbols_block",
            evaluated_at_ms=now_ms,
        )
    if state.block_code == "reversal":
        return _build(
            gate_name=GATE_NAME_SHARED_RISK_GATE,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_budget_reversal_block",
            evaluated_at_ms=now_ms,
        )
    if state.block_code == "emergency_margin":
        return _build(
            gate_name=GATE_NAME_SHARED_RISK_GATE,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_budget_emergency_margin_block",
            evaluated_at_ms=now_ms,
        )
    return _build(
        gate_name=GATE_NAME_SHARED_RISK_GATE,
        action=LEGACY_GATE_ACTION_DENY,
        reason_code="deny_budget_evidence_missing",
        evaluated_at_ms=now_ms,
    )


def evaluate_margin_state(
    state: MarginGovernorState,
    *,
    now_ms_clock: Callable[[], int],
) -> LegacyGateVerdict:
    if not isinstance(state, MarginGovernorState):
        raise RiskLegacyGatesServiceError(
            "must_be_margin_governor_state", field="state"
        )
    now_ms = _resolve_now_ms(now_ms_clock)

    if not state.evidence_present:
        return _build(
            gate_name=GATE_NAME_MARGIN_GOVERNOR,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_margin_evidence_missing",
            evaluated_at_ms=now_ms,
        )
    if state.verdict_action == "allow":
        return _build(
            gate_name=GATE_NAME_MARGIN_GOVERNOR,
            action=LEGACY_GATE_ACTION_ALLOW,
            reason_code="allow_margin_within_caps",
            evaluated_at_ms=now_ms,
        )
    if state.verdict_action == "block_account":
        return _build(
            gate_name=GATE_NAME_MARGIN_GOVERNOR,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_margin_account_breach",
            evaluated_at_ms=now_ms,
        )
    if state.verdict_action == "block_symbol":
        return _build(
            gate_name=GATE_NAME_MARGIN_GOVERNOR,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_margin_symbol_breach",
            evaluated_at_ms=now_ms,
        )
    if state.verdict_action == "deleverage":
        return _build(
            gate_name=GATE_NAME_MARGIN_GOVERNOR,
            action=LEGACY_GATE_ACTION_CLOSE_ONLY,
            reason_code="close_only_margin_deleverage_required",
            evaluated_at_ms=now_ms,
        )
    return _build(
        gate_name=GATE_NAME_MARGIN_GOVERNOR,
        action=LEGACY_GATE_ACTION_DENY,
        reason_code="deny_margin_evidence_missing",
        evaluated_at_ms=now_ms,
    )


def evaluate_phase_gate(
    state: PhaseGateState,
    *,
    now_ms_clock: Callable[[], int],
) -> LegacyGateVerdict:
    if not isinstance(state, PhaseGateState):
        raise RiskLegacyGatesServiceError(
            "must_be_phase_gate_state", field="state"
        )
    now_ms = _resolve_now_ms(now_ms_clock)

    if not state.evidence_present:
        return _build(
            gate_name=GATE_NAME_PHASE_CONTROLLER,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_phase_evidence_missing",
            evaluated_at_ms=now_ms,
        )
    if state.ramp_limit_breach == "":
        return _build(
            gate_name=GATE_NAME_PHASE_CONTROLLER,
            action=LEGACY_GATE_ACTION_ALLOW,
            reason_code="allow_phase_within_ramp_limits",
            evaluated_at_ms=now_ms,
        )
    if state.ramp_limit_breach == "max_mu":
        return _build(
            gate_name=GATE_NAME_PHASE_CONTROLLER,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_phase_max_mu_exceeded",
            evaluated_at_ms=now_ms,
        )
    if state.ramp_limit_breach == "min_free_margin_ratio":
        return _build(
            gate_name=GATE_NAME_PHASE_CONTROLLER,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_phase_min_free_margin_violated",
            evaluated_at_ms=now_ms,
        )
    if state.ramp_limit_breach == "max_positions":
        return _build(
            gate_name=GATE_NAME_PHASE_CONTROLLER,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_phase_max_positions_exceeded",
            evaluated_at_ms=now_ms,
        )
    if state.ramp_limit_breach == "per_symbol_margin":
        return _build(
            gate_name=GATE_NAME_PHASE_CONTROLLER,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_phase_per_symbol_margin_exceeded",
            evaluated_at_ms=now_ms,
        )
    if state.ramp_limit_breach == "equity_missing_or_nan":
        return _build(
            gate_name=GATE_NAME_PHASE_CONTROLLER,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_phase_equity_missing_or_nan",
            evaluated_at_ms=now_ms,
        )
    return _build(
        gate_name=GATE_NAME_PHASE_CONTROLLER,
        action=LEGACY_GATE_ACTION_DENY,
        reason_code="deny_phase_evidence_missing",
        evaluated_at_ms=now_ms,
    )


def evaluate_toxicity_block(
    state: ToxicityState,
    *,
    now_ms_clock: Callable[[], int],
) -> LegacyGateVerdict:
    if not isinstance(state, ToxicityState):
        raise RiskLegacyGatesServiceError(
            "must_be_toxicity_state", field="state"
        )
    now_ms = _resolve_now_ms(now_ms_clock)

    if not state.evidence_present:
        return _build(
            gate_name=GATE_NAME_MICROSTRUCTURE_TOXICITY,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_toxicity_evidence_missing",
            evaluated_at_ms=now_ms,
        )
    if not state.is_risk_add:
        return _build(
            gate_name=GATE_NAME_MICROSTRUCTURE_TOXICITY,
            action=LEGACY_GATE_ACTION_ALLOW,
            reason_code="allow_toxicity_within_threshold",
            evaluated_at_ms=now_ms,
        )
    if float(state.score) >= float(state.extreme_threshold):
        return _build(
            gate_name=GATE_NAME_MICROSTRUCTURE_TOXICITY,
            action=LEGACY_GATE_ACTION_DENY,
            reason_code="deny_toxicity_extreme_block",
            evaluated_at_ms=now_ms,
        )
    return _build(
        gate_name=GATE_NAME_MICROSTRUCTURE_TOXICITY,
        action=LEGACY_GATE_ACTION_ALLOW,
        reason_code="allow_toxicity_within_threshold",
        evaluated_at_ms=now_ms,
    )
