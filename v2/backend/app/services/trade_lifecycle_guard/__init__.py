"""Shared trade lifecycle guard contracts.

Paper uses this now; live can use the same pure validation layer later without
changing live submit behavior in this pass.
"""

from .contracts import TradeLifecycleGuardInput, TradeLifecycleGuardResult
from .guard import evaluate_trade_lifecycle_guard

__all__ = [
    "TradeLifecycleGuardInput",
    "TradeLifecycleGuardResult",
    "evaluate_trade_lifecycle_guard",
]
