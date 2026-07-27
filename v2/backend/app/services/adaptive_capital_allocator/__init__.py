"""Adaptive V2 capital allocation.

The allocator computes paper/live target notional dynamically from model edge,
market quality, exposure, drawdown, liquidity, and account constraints. It does
not use fixed runtime dollar sizing.
"""

from .allocator import (
    allocate_authorized_adaptive_paper_action,
    allocate_live_candidate,
    allocate_paper_candidate,
    explain_allocation,
)
from .contracts import (
    ADAPTIVE_CAPITAL_POLICY_VERSION,
    AllocationDecision,
    AllocationInput,
    AllocationResult,
    RiskEnvelope,
)

__all__ = [
    "ADAPTIVE_CAPITAL_POLICY_VERSION",
    "AllocationDecision",
    "AllocationInput",
    "AllocationResult",
    "RiskEnvelope",
    "allocate_live_candidate",
    "allocate_authorized_adaptive_paper_action",
    "allocate_paper_candidate",
    "explain_allocation",
]
