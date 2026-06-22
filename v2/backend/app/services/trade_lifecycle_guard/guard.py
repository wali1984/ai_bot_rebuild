from __future__ import annotations

from .contracts import TradeLifecycleGuardInput, TradeLifecycleGuardResult


def evaluate_trade_lifecycle_guard(candidate: TradeLifecycleGuardInput) -> TradeLifecycleGuardResult:
    blockers: list[str] = []
    if not candidate.lineage_present:
        blockers.append("TRADE_LIFECYCLE_LINEAGE_MISSING")
    if not candidate.market_state_valid:
        blockers.append("TRADE_LIFECYCLE_MARKET_STATE_INVALID")
    if not candidate.risk_decision_valid:
        blockers.append("TRADE_LIFECYCLE_RISK_DECISION_INVALID")
    if not candidate.symbol_cap_valid:
        blockers.append("TRADE_LIFECYCLE_SYMBOL_CAP_BLOCK")
    if not candidate.total_exposure_valid:
        blockers.append("TRADE_LIFECYCLE_TOTAL_EXPOSURE_BLOCK")
    if not candidate.netting_rule_valid:
        blockers.append("TRADE_LIFECYCLE_NETTING_RULE_BLOCK")
    if not candidate.drawdown_guard_valid:
        blockers.append("TRADE_LIFECYCLE_DRAWDOWN_GUARD_BLOCK")
    if candidate.kill_switch_active:
        blockers.append("TRADE_LIFECYCLE_KILL_SWITCH_ACTIVE")
    if candidate.halt_active:
        blockers.append("TRADE_LIFECYCLE_HALT_ACTIVE")
    if candidate.reduce_only_latch_active and not candidate.close_or_reduce:
        blockers.append("TRADE_LIFECYCLE_REDUCE_ONLY_LATCH_BLOCKS_NEW_ENTRY")
    return TradeLifecycleGuardResult(
        allowed=not blockers,
        blockers=tuple(blockers),
        action=candidate.action,
        symbol=candidate.symbol,
        side=candidate.side,
    )
