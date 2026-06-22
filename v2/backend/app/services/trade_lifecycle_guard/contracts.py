from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TradeLifecycleGuardInput:
    symbol: str
    side: str
    action: str = "open"
    lineage_present: bool = True
    market_state_valid: bool = True
    risk_decision_valid: bool = True
    symbol_cap_valid: bool = True
    total_exposure_valid: bool = True
    netting_rule_valid: bool = True
    drawdown_guard_valid: bool = True
    kill_switch_active: bool = False
    halt_active: bool = False
    reduce_only_latch_active: bool = False
    close_or_reduce: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TradeLifecycleGuardResult:
    allowed: bool
    blockers: tuple[str, ...]
    action: str
    symbol: str
    side: str
    paper_only: bool = True
    places_real_order: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "blockers": list(self.blockers),
            "action": self.action,
            "symbol": self.symbol,
            "side": self.side,
            "paper_only": self.paper_only,
            "places_real_order": self.places_real_order,
        }
