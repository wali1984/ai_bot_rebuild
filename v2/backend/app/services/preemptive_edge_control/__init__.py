"""Preemptive edge control: pre-trade, pre-failure candidate evaluation.

Every candidate must receive a preemptive decision object BEFORE it can reach
paper fill, REDUCE_SIZE, A+, or live dry-run. Missing evidence fails closed.
Paper-only: nothing in this package submits, modifies, or routes orders.
"""

from v2.backend.app.services.preemptive_edge_control.decision import (
    PREEMPTIVE_DECISIONS,
    evaluate_candidate,
)
from v2.backend.app.services.preemptive_edge_control.service import (
    evaluate_preemptive_decision,
)

__all__ = [
    "evaluate_candidate",
    "evaluate_preemptive_decision",
    "PREEMPTIVE_DECISIONS",
]
