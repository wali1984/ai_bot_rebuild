from __future__ import annotations

from dataclasses import dataclass

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


LEGACY_SOURCE_SHA256 = {
    "adaptive_gate": "a5057ea4ad4542881a6ebf14b9d789cbeed7873fc763c9d74d06c7c781674bce",
    "auto_deleverager": "76652e99ec0b0717a3bfea887c25f78746df7765ba3f5e4eff6a21d0e820a377",
    "halt_manager": "49504d73a9fef319eb0ac6282d571492714a62526bc1c9849148685ad7eac314",
    "intelligent_close_guard": "7edf6d5eca3e8654bc17f0fad22831e4daedb411138d576904a29ab0a352c3ee",
    "kill_switch": "bf730c6fa425097aa0c246dfbab88e4f8d158afdd606a905c8f9e3c7695df59e",
    "margin_governor": "e8448d2ee70697a97fbb4af27555adabe2af590d8185ebfc644b965070376eee",
    "microstructure_toxicity": "5103e3078e15734eaca310e9ae58dd8e89725ebf4317a98313f078c8bd74beef",
    "phase_controller": "ecd566ca7537551a9e6e267da4880a41764d346a1d43137d4088003951211ee1",
    "reduce_only_latch": "e0dc68486a5cc2fa0fc0ea1d1197f66373f8c090deb889a403257e187c7ac611",
    "shared_risk_gate": "62c2403f2cf2ce5dec71522b919f1db6a2f6908e338903e359e021c75c59dd7f",
}


@dataclass(frozen=True, slots=True)
class LegacyRiskGateEvaluation:
    gate_id: str
    gate_action: str
    passed: bool
    risk_reason_code: str
    evidence_status: str
    detail: str
    legacy_source_sha256: str
    close_only: bool = False
    live_blocked: bool = True


def _allow(gate_id: str, *, source_key: str, detail: str = "gate_clear") -> LegacyRiskGateEvaluation:
    return LegacyRiskGateEvaluation(
        gate_id=gate_id,
        gate_action="allow",
        passed=True,
        risk_reason_code="",
        evidence_status="present",
        detail=detail,
        legacy_source_sha256=LEGACY_SOURCE_SHA256[source_key],
    )


def _deny(
    gate_id: str,
    *,
    source_key: str,
    reason_code: str,
    missing: bool,
    detail: str,
) -> LegacyRiskGateEvaluation:
    return LegacyRiskGateEvaluation(
        gate_id=gate_id,
        gate_action="deny",
        passed=False,
        risk_reason_code=reason_code,
        evidence_status="missing" if missing else "present",
        detail=detail,
        legacy_source_sha256=LEGACY_SOURCE_SHA256[source_key],
    )


def _close_only(
    gate_id: str,
    *,
    source_key: str,
    missing: bool,
    detail: str,
) -> LegacyRiskGateEvaluation:
    return LegacyRiskGateEvaluation(
        gate_id=gate_id,
        gate_action="close_only",
        passed=False,
        risk_reason_code=RISK_DECISION_REASON_ALLOW_CLOSE_ONLY_INTELLIGENT_CLOSE_GUARD,
        evidence_status="missing" if missing else "present",
        detail=detail,
        legacy_source_sha256=LEGACY_SOURCE_SHA256[source_key],
        close_only=True,
    )


def evaluate_kill_switch_state(
    *,
    kill_switch_active: bool | None = None,
    active: bool | None = None,
    scope: str = "GLOBAL",
    account: str | None = None,
    account_query: str | None = None,
    symbol: str | None = None,
    symbol_query: str | None = None,
    payload_corrupt: bool = False,
) -> LegacyRiskGateEvaluation:
    observed_active = kill_switch_active if active is None else active
    if observed_active is False:
        return _allow("kill_switch", source_key="kill_switch")
    if observed_active is None:
        return _deny(
            "kill_switch",
            source_key="kill_switch",
            reason_code=RISK_DECISION_REASON_DENY_KILL_SWITCH_ACTIVE,
            missing=True,
            detail="kill_switch_evidence_missing",
        )
    if payload_corrupt:
        return _deny(
            "kill_switch",
            source_key="kill_switch",
            reason_code=RISK_DECISION_REASON_DENY_KILL_SWITCH_ACTIVE,
            missing=False,
            detail="kill_switch_corrupt_payload_blocks_globally",
        )
    normalized_scope = str(scope or "GLOBAL").upper()
    if normalized_scope == "GLOBAL":
        detail = "kill_switch_active_global"
        blocks = True
    elif normalized_scope == "ACCOUNT":
        if not account_query:
            detail = "kill_switch_active_account_without_query"
            blocks = True
        else:
            blocks = str(account_query).lower() == str(account or "").lower()
            detail = "kill_switch_active_account_match" if blocks else "kill_switch_account_mismatch"
    elif normalized_scope == "SYMBOL":
        if not symbol_query:
            detail = "kill_switch_active_symbol_without_query"
            blocks = True
        else:
            blocks = str(symbol_query).upper() == str(symbol or "").upper()
            detail = "kill_switch_active_symbol_match" if blocks else "kill_switch_symbol_mismatch"
    else:
        detail = "kill_switch_unknown_scope_blocks"
        blocks = True
    if not blocks:
        return _allow("kill_switch", source_key="kill_switch", detail=detail)
    return _deny(
        "kill_switch",
        source_key="kill_switch",
        reason_code=RISK_DECISION_REASON_DENY_KILL_SWITCH_ACTIVE,
        missing=False,
        detail=detail,
    )


def evaluate_halt_state(*, halt_active: bool | None) -> LegacyRiskGateEvaluation:
    if halt_active is False:
        return _allow("halt_manager", source_key="halt_manager")
    return _deny(
        "halt_manager",
        source_key="halt_manager",
        reason_code=RISK_DECISION_REASON_DENY_HALT_MANAGER_ACTIVE,
        missing=halt_active is None,
        detail="halt_active_or_unproven",
    )


def evaluate_latch_state(
    *,
    reduce_only_latch_active: bool | None = None,
    latch_active: bool | None = None,
    increases_risk: bool = True,
    is_risk_add: bool | None = None,
) -> LegacyRiskGateEvaluation:
    observed_active = reduce_only_latch_active if latch_active is None else latch_active
    risk_add = increases_risk if is_risk_add is None else is_risk_add
    if observed_active is False or not risk_add:
        return _allow("reduce_only_latch", source_key="reduce_only_latch")
    return _deny(
        "reduce_only_latch",
        source_key="reduce_only_latch",
        reason_code=RISK_DECISION_REASON_DENY_REDUCE_ONLY_LATCH,
        missing=observed_active is None,
        detail="reduce_only_latch_blocks_risk_increase",
    )


def evaluate_close_guard(
    *,
    close_allowed: bool | None = None,
    guard_action: str | None = None,
    loss_realizing_close: bool = True,
) -> LegacyRiskGateEvaluation:
    if guard_action:
        normalized = guard_action.lower()
        if normalized == "allow_close":
            close_allowed = True
        elif normalized == "emergency_bypass":
            return _close_only(
                "intelligent_close_guard",
                source_key="intelligent_close_guard",
                missing=False,
                detail="close_guard_emergency_bypass",
            )
        elif normalized == "defer_close":
            close_allowed = False
    if close_allowed is True:
        return _allow("intelligent_close_guard", source_key="intelligent_close_guard")
    detail = "loss_close_not_proven_safe" if loss_realizing_close else "close_guard_not_proven"
    return _close_only(
        "intelligent_close_guard",
        source_key="intelligent_close_guard",
        missing=close_allowed is None,
        detail=detail,
    )


def evaluate_adl_state(
    *,
    deleverager_triggered: bool | None = None,
    cap_breach: str | None = None,
) -> LegacyRiskGateEvaluation:
    observed_trigger = deleverager_triggered
    if cap_breach is not None:
        observed_trigger = bool(cap_breach)
    if observed_trigger is False:
        return _allow("auto_deleverager", source_key="auto_deleverager")
    return _deny(
        "auto_deleverager",
        source_key="auto_deleverager",
        reason_code=RISK_DECISION_REASON_DENY_AUTO_DELEVERAGER_TRIGGERED,
        missing=observed_trigger is None,
        detail="deleverager_triggered_or_unproven",
    )


def evaluate_budget_state(
    *,
    budget_remaining: float | None = None,
    budget_required: float = 1.0,
    block_code: str | None = None,
    is_risk_add: bool = True,
    is_reduce: bool = False,
) -> LegacyRiskGateEvaluation:
    if is_reduce and not is_risk_add:
        return _allow("shared_risk_gate", source_key="shared_risk_gate", detail="reduce_only_passes")
    if block_code:
        return _deny(
            "shared_risk_gate",
            source_key="shared_risk_gate",
            reason_code=RISK_DECISION_REASON_DENY_SHARED_RISK_BUDGET_EXHAUSTED,
            missing=False,
            detail=f"shared_risk_gate_{block_code}_block",
        )
    if budget_remaining is not None and budget_remaining >= budget_required:
        return _allow("shared_risk_gate", source_key="shared_risk_gate")
    return _deny(
        "shared_risk_gate",
        source_key="shared_risk_gate",
        reason_code=RISK_DECISION_REASON_DENY_SHARED_RISK_BUDGET_EXHAUSTED,
        missing=budget_remaining is None,
        detail="shared_budget_exhausted_or_unproven",
    )


def evaluate_margin_state(
    *,
    proposed_leverage: float | None = None,
    max_allowed_leverage: float = 1.0,
    margin_mode: str | None = "isolated",
    required_margin_mode: str = "isolated",
    verdict_action: str | None = None,
) -> LegacyRiskGateEvaluation:
    if verdict_action:
        normalized = verdict_action.lower()
        if normalized == "allow":
            return _allow("margin_governor", source_key="margin_governor")
        return _deny(
            "margin_governor",
            source_key="margin_governor",
            reason_code=RISK_DECISION_REASON_DENY_MARGIN_GOVERNOR_LEVERAGE_INCREASE_BLOCKED,
            missing=False,
            detail=f"margin_governor_{normalized}",
        )
    leverage_ok = proposed_leverage is not None and proposed_leverage <= max_allowed_leverage
    margin_ok = str(margin_mode or "").lower() == required_margin_mode.lower()
    if leverage_ok and margin_ok:
        return _allow("margin_governor", source_key="margin_governor")
    return _deny(
        "margin_governor",
        source_key="margin_governor",
        reason_code=RISK_DECISION_REASON_DENY_MARGIN_GOVERNOR_LEVERAGE_INCREASE_BLOCKED,
        missing=proposed_leverage is None or margin_mode is None,
        detail="leverage_or_margin_mode_not_allowed",
    )


def evaluate_phase_gate(
    *,
    warmup_complete: bool | None = None,
    ramp_limit_breach: str | None = None,
) -> LegacyRiskGateEvaluation:
    if ramp_limit_breach:
        return _deny(
            "phase_controller",
            source_key="phase_controller",
            reason_code=RISK_DECISION_REASON_DENY_PHASE_CONTROLLER_WARMUP,
            missing=False,
            detail=f"phase_controller_{ramp_limit_breach}",
        )
    if warmup_complete is True:
        return _allow("phase_controller", source_key="phase_controller")
    return _deny(
        "phase_controller",
        source_key="phase_controller",
        reason_code=RISK_DECISION_REASON_DENY_PHASE_CONTROLLER_WARMUP,
        missing=warmup_complete is None,
        detail="phase_warmup_blocks_risk_add",
    )


def evaluate_toxicity_block(
    *,
    toxicity_score: float | None,
    toxic_threshold: float = 0.85,
    extreme_threshold: float | None = None,
    is_risk_add: bool = True,
) -> LegacyRiskGateEvaluation:
    threshold = toxic_threshold if extreme_threshold is None else extreme_threshold
    if not is_risk_add:
        return _allow("microstructure_toxicity", source_key="microstructure_toxicity", detail="toxicity_reduce_only_passes")
    if toxicity_score is not None and toxicity_score < threshold:
        return _allow("microstructure_toxicity", source_key="microstructure_toxicity")
    return _deny(
        "microstructure_toxicity",
        source_key="microstructure_toxicity",
        reason_code=RISK_DECISION_REASON_DENY_ADAPTIVE_MICROSTRUCTURE_TOXIC,
        missing=toxicity_score is None,
        detail="microstructure_toxic_or_unproven",
    )
