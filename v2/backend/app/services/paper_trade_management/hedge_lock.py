"""HedgeLock — paper-only bounded hedge-and-wait state machine.

SAFETY RULES (non-negotiable):
  - Never submits real exchange orders.
  - Only activates when operator sets hedge_lock_enabled=True in lifecycle config.
  - Requires profitable excursion BEFORE the lock can open (no locking a fresh loser).
  - Hard cap on max pair drawdown and max hold time.
  - Net pair PnL exit closes both legs immediately when positive.
  - All state stored in Redis under v2:paper:hedge_locks:{hedge_id}.
  - No martingale, no stacking, no accidental double-hedge of same symbol.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


# ── Config ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HedgeLockConfig:
    """Operator-gated HedgeLock configuration.

    enabled defaults to False. Operator must explicitly enable via lifecycle config.
    This is a dangerous setting — see CLAUDE.md Admin Control Rule.
    """
    enabled: bool = False
    # Position must have reached this profit excursion (bps) before a lock can trigger.
    min_profit_excursion_before_lock_bps: float = 25.0
    # Maximum additional loss the locked pair is allowed to accumulate after hedging.
    max_pair_drawdown_bps: float = 120.0
    # Maximum wall-clock seconds a hedge lock may remain open.
    max_hedge_hold_seconds: int = 4 * 3600  # 4 hours
    # Net PnL threshold above which both legs are closed as a WIN.
    net_pnl_close_threshold_bps: float = 5.0
    # Fee overhead per hedge leg (bps). Hedge is skipped if fee > expected recovery.
    fee_per_leg_bps: float = 6.0


# ── State ──────────────────────────────────────────────────────────────────────

@dataclass
class HedgeLockPair:
    """Tracks a single locked pair (original + hedge leg)."""
    hedge_id: str
    symbol: str
    original_side: str          # "long" or "short"
    original_position_id: str
    original_entry_price: float
    original_best_excursion_bps: float  # best PnL bps before hedge triggered
    hedge_side: str             # opposite of original
    hedge_entry_price: float
    hedge_quantity: float
    hedge_entry_utc: str
    hedge_cost_bps: float       # fee cost of the hedge leg
    max_hold_deadline_utc: str
    max_pair_drawdown_bps: float
    net_pnl_close_threshold_bps: float
    status: str = "LOCKED"      # LOCKED | UNHEDGED | CLOSED_WIN | CLOSED_LOSS | CLOSED_TIMEOUT
    unhedge_reason: str | None = None
    net_pair_pnl_bps: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "hedge_id": self.hedge_id,
            "symbol": self.symbol,
            "original_side": self.original_side,
            "original_position_id": self.original_position_id,
            "original_entry_price": self.original_entry_price,
            "original_best_excursion_bps": self.original_best_excursion_bps,
            "hedge_side": self.hedge_side,
            "hedge_entry_price": self.hedge_entry_price,
            "hedge_quantity": self.hedge_quantity,
            "hedge_entry_utc": self.hedge_entry_utc,
            "hedge_cost_bps": self.hedge_cost_bps,
            "max_hold_deadline_utc": self.max_hold_deadline_utc,
            "max_pair_drawdown_bps": self.max_pair_drawdown_bps,
            "net_pnl_close_threshold_bps": self.net_pnl_close_threshold_bps,
            "status": self.status,
            "unhedge_reason": self.unhedge_reason,
            "net_pair_pnl_bps": self.net_pair_pnl_bps,
            "places_real_order": False,
            "paper_only": True,
        }


# ── Decision helpers ──────────────────────────────────────────────────────────

def should_trigger_hedge_lock(
    *,
    position_id: str,
    symbol: str,
    side: str,
    pnl_bps: float,
    best_excursion_bps: float,
    drawdown_from_best_bps: float,
    hold_seconds: int,
    existing_hedge_ids: set[str],
    config: HedgeLockConfig,
) -> dict[str, Any]:
    """Return trigger=True if HedgeLock should replace a trailing-stop close.

    This is called in exits.py when TIER_2_TRAILING_STOP would otherwise fire.
    """
    if not config.enabled:
        return {"trigger": False, "reason": "HEDGE_LOCK_NOT_ENABLED"}

    # No double-locking the same position
    if position_id in existing_hedge_ids:
        return {"trigger": False, "reason": "ALREADY_HEDGE_LOCKED"}

    # Must have had a real profitable excursion before we lock
    if best_excursion_bps < config.min_profit_excursion_before_lock_bps:
        return {
            "trigger": False,
            "reason": f"INSUFFICIENT_EXCURSION:{best_excursion_bps:.1f}bps<{config.min_profit_excursion_before_lock_bps:.1f}bps",
        }

    # The hedge fee must not exceed the excursion we're protecting
    total_fee_bps = config.fee_per_leg_bps * 2
    if total_fee_bps >= best_excursion_bps:
        return {
            "trigger": False,
            "reason": f"FEE_EXCEEDS_EXCURSION:fees={total_fee_bps:.1f}bps>=excursion={best_excursion_bps:.1f}bps",
        }

    return {
        "trigger": True,
        "reason": "HEDGE_LOCK_ELIGIBLE",
        "hedge_side": "long" if side == "short" else "short",
        "estimated_fee_bps": total_fee_bps,
        "protected_excursion_bps": best_excursion_bps,
    }


def build_hedge_lock_pair(
    *,
    original_position_id: str,
    symbol: str,
    original_side: str,
    original_entry_price: float,
    best_excursion_bps: float,
    hedge_entry_price: float,
    hedge_quantity: float,
    hedge_entry_utc: str,
    max_hold_deadline_utc: str,
    config: HedgeLockConfig,
) -> HedgeLockPair:
    """Construct a new HedgeLockPair. Returns a ready-to-store state object."""
    return HedgeLockPair(
        hedge_id=f"hedge_{uuid.uuid4().hex[:12]}",
        symbol=symbol,
        original_side=original_side,
        original_position_id=original_position_id,
        original_entry_price=original_entry_price,
        original_best_excursion_bps=best_excursion_bps,
        hedge_side="long" if original_side == "short" else "short",
        hedge_entry_price=hedge_entry_price,
        hedge_quantity=hedge_quantity,
        hedge_entry_utc=hedge_entry_utc,
        hedge_cost_bps=config.fee_per_leg_bps * 2,
        max_hold_deadline_utc=max_hold_deadline_utc,
        max_pair_drawdown_bps=config.max_pair_drawdown_bps,
        net_pnl_close_threshold_bps=config.net_pnl_close_threshold_bps,
    )


def evaluate_hedge_lock_exit(
    *,
    pair: HedgeLockPair,
    original_pnl_bps: float,
    hedge_pnl_bps: float,
    current_utc: str,
) -> dict[str, Any]:
    """Decide what to do with an active hedge lock pair.

    Returns action: HOLD | CLOSE_WIN | CLOSE_TIMEOUT | CLOSE_MAX_DRAWDOWN | UNHEDGE
    """
    net_pnl_bps = original_pnl_bps + hedge_pnl_bps

    # Net positive → close both as a WIN
    if net_pnl_bps >= pair.net_pnl_close_threshold_bps:
        return {
            "action": "CLOSE_WIN",
            "net_pnl_bps": net_pnl_bps,
            "original_pnl_bps": original_pnl_bps,
            "hedge_pnl_bps": hedge_pnl_bps,
            "reason": "NET_PNL_POSITIVE",
        }

    # Max pair drawdown hit → close both to stop further damage
    if net_pnl_bps <= -abs(pair.max_pair_drawdown_bps):
        return {
            "action": "CLOSE_MAX_DRAWDOWN",
            "net_pnl_bps": net_pnl_bps,
            "reason": f"MAX_PAIR_DRAWDOWN_EXCEEDED:{net_pnl_bps:.1f}bps",
        }

    # Deadline exceeded → close both
    if current_utc >= pair.max_hold_deadline_utc:
        return {
            "action": "CLOSE_TIMEOUT",
            "net_pnl_bps": net_pnl_bps,
            "reason": "MAX_HEDGE_HOLD_TIME",
        }

    # Original thesis has resumed (original position now net positive again)
    if original_pnl_bps >= pair.net_pnl_close_threshold_bps:
        return {
            "action": "UNHEDGE",
            "net_pnl_bps": net_pnl_bps,
            "reason": "ORIGINAL_THESIS_RESUMED",
        }

    return {
        "action": "HOLD",
        "net_pnl_bps": net_pnl_bps,
        "original_pnl_bps": original_pnl_bps,
        "hedge_pnl_bps": hedge_pnl_bps,
    }
