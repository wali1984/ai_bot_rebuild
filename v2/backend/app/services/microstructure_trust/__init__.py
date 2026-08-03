"""Adversarial microstructure trust layer.

Public orderbook data is treated as noisy input, not execution truth. The
package computes fail-closed trust evidence from feed quality, book behavior,
trade tape, liquidation context, and cross-venue confirmation.
"""
from .cascade_context import (
    CASCADE_CONTEXT_STATUSES,
    CASCADE_ABSENT_NO_TRADE,
    CASCADE_EVENT_CONFIRMED,
    CASCADE_INSUFFICIENT_SHADOW_ONLY,
    CASCADE_LEVEL_PROXIMITY_CONFIRMED,
    CASCADE_PROXY_CONFIRMED,
    CASCADE_STALE_NO_TRADE,
    build_cascade_context,
    context_allows_short_trend_paper_entry,
)
from .cross_venue_confirmation import evaluate_cross_venue_confirmation
from .feed_quality import evaluate_feed_quality
from .liquidation_sweep_detector import detect_liquidation_sweep
from .orderbook_adversarial_features import compute_orderbook_adversarial_features
from .trade_tape_confirmation import evaluate_trade_tape_confirmation
from .trust_score import MicrostructureAction, classify_microstructure_trust, score_microstructure_trust

__all__ = [
    "CASCADE_ABSENT_NO_TRADE",
    "CASCADE_CONTEXT_STATUSES",
    "CASCADE_EVENT_CONFIRMED",
    "CASCADE_INSUFFICIENT_SHADOW_ONLY",
    "CASCADE_LEVEL_PROXIMITY_CONFIRMED",
    "CASCADE_PROXY_CONFIRMED",
    "CASCADE_STALE_NO_TRADE",
    "MicrostructureAction",
    "build_cascade_context",
    "classify_microstructure_trust",
    "context_allows_short_trend_paper_entry",
    "compute_orderbook_adversarial_features",
    "detect_liquidation_sweep",
    "evaluate_cross_venue_confirmation",
    "evaluate_feed_quality",
    "evaluate_trade_tape_confirmation",
    "score_microstructure_trust",
]
