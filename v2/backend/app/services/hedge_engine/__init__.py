"""Paper/live-dry-run hedge and margin stress simulation helpers.

The package is deliberately pure: it does not hold exchange clients, write
Redis, or mutate leverage/margin mode. Callers attach the returned simulations
to paper decisions, allocator payloads, and live-dry-run operator packets.
"""

from .cross_margin_stress import simulate_cross_margin_stress
from .hedge_intent import evaluate_hedge_intent
from .portfolio_exposure import compute_portfolio_exposure

__all__ = [
    "compute_portfolio_exposure",
    "evaluate_hedge_intent",
    "simulate_cross_margin_stress",
]
