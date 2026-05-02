from __future__ import annotations

from .models import ManualOverride, SymbolOverride, SymbolState, SymbolStateRecord


ALLOWED_TRANSITIONS = {
    SymbolState.DISCOVERED.value: {SymbolState.OBSERVED.value, SymbolState.DISABLED.value, SymbolState.REMOVED.value},
    SymbolState.OBSERVED.value: {
        SymbolState.ELIGIBLE_FOR_TRAINING.value,
        SymbolState.DISABLED.value,
        SymbolState.REMOVED.value,
    },
    SymbolState.ELIGIBLE_FOR_TRAINING.value: {
        SymbolState.TRAINING_ACTIVE.value,
        SymbolState.DISABLED.value,
        SymbolState.REMOVED.value,
    },
    SymbolState.TRAINING_ACTIVE.value: {
        SymbolState.ELIGIBLE_FOR_PAPER.value,
        SymbolState.DISABLED.value,
        SymbolState.REMOVED.value,
    },
    SymbolState.ELIGIBLE_FOR_PAPER.value: {
        SymbolState.PAPER_TRADING.value,
        SymbolState.SHADOW_CANDIDATE.value,
        SymbolState.DISABLED.value,
        SymbolState.REMOVED.value,
    },
    SymbolState.PAPER_TRADING.value: {
        SymbolState.SHADOW_CANDIDATE.value,
        SymbolState.DISABLED.value,
        SymbolState.REMOVED.value,
    },
    SymbolState.SHADOW_CANDIDATE.value: {
        SymbolState.LIVE_BLOCKED.value,
        SymbolState.DISABLED.value,
        SymbolState.REMOVED.value,
    },
    SymbolState.LIVE_BLOCKED.value: {SymbolState.DISABLED.value, SymbolState.REMOVED.value},
    SymbolState.DISABLED.value: {SymbolState.OBSERVED.value, SymbolState.REMOVED.value},
    SymbolState.REMOVED.value: set(),
    SymbolState.MANUAL_OVERRIDE.value: {
        SymbolState.OBSERVED.value,
        SymbolState.TRAINING_ACTIVE.value,
        SymbolState.PAPER_TRADING.value,
        SymbolState.SHADOW_CANDIDATE.value,
        SymbolState.DISABLED.value,
        SymbolState.REMOVED.value,
    },
}


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())


def transition(record: SymbolStateRecord, target: str, reason: str) -> SymbolStateRecord:
    if not can_transition(record.state, target):
        raise ValueError(f"invalid symbol transition: {record.state} -> {target}")
    if target not in {SymbolState.DISABLED.value, SymbolState.REMOVED.value} and not record.identity.is_trading():
        raise ValueError("non-trading symbols cannot become active without manual override")
    return SymbolStateRecord(identity=record.identity, state=target, override=record.override, state_reason=reason)


def apply_override(record: SymbolStateRecord, override: SymbolOverride) -> SymbolStateRecord:
    action = override.action
    if action == ManualOverride.FORCE_OBSERVE.value:
        target = SymbolState.OBSERVED.value
    elif action == ManualOverride.FORCE_TRAIN.value:
        target = SymbolState.TRAINING_ACTIVE.value
    elif action == ManualOverride.FORCE_DISABLE.value:
        target = SymbolState.DISABLED.value
    elif action == ManualOverride.FORCE_PAPER.value:
        target = SymbolState.PAPER_TRADING.value
    elif action == ManualOverride.FORCE_SHADOW_CANDIDATE.value:
        target = SymbolState.SHADOW_CANDIDATE.value
    elif action == ManualOverride.REMOVE.value:
        target = SymbolState.REMOVED.value
    elif action in {ManualOverride.SET_PRIORITY.value, ManualOverride.SET_MAX_RISK.value, ManualOverride.PAUSE_SYMBOL.value}:
        target = SymbolState.MANUAL_OVERRIDE.value
    else:
        raise ValueError(f"unknown manual override: {action}")
    return SymbolStateRecord(
        identity=record.identity,
        state=target,
        override=override,
        state_reason=f"manual_override:{action}",
    )

