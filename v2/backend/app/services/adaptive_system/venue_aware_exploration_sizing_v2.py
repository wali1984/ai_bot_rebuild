"""Venue-aware bounded exploration sizing — FINAL PASS Phase 12 / task FP-130.

Root cause of the traced 0-fill deadlock: a STATIC 5% exploration risk fraction
produces a reduced notional (~$1-3) below the exchange minimum (~$5) for the whole
small-notional universe, so every exploration candidate is blocked at
BLOCK_RISK_BUDGET_BELOW_EXECUTABLE_MINIMUM and nothing ever fills.

Phase 12 replaces that with venue-aware selection. This function answers ONE
question for a single candidate, deterministically and without side effects:

    Is there an exploration size that is BOTH venue-executable AND inside the
    unchanged catastrophic-loss envelope?

Rules (all from FINAL PASS Phase 12):
  * NEVER increase risk merely to force a fill. The chosen size may not exceed the
    catastrophic caps (max risk $, max notional, max leverage).
  * NEVER authorize a size whose final risk-reduced quantity cannot satisfy venue
    requirements (min notional AND min qty AND qty step).
  * If no size satisfies BOTH, return SELECT_ANOTHER_OPPORTUNITY — the caller must
    pick a different executable symbol/timeframe/action, not raise risk here.

This module changes NO threshold and grants NO authority; it emits a bounded,
venue-checked size proposal that the hard validator still revalidates.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

SCHEMA_VERSION = "venue_aware_exploration_sizing_v2"

EXECUTABLE = "VENUE_EXECUTABLE_WITHIN_ENVELOPE"
SELECT_ANOTHER = "SELECT_ANOTHER_OPPORTUNITY"


def _finite_pos(v: float | int | None) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and v > 0.0


@dataclass(frozen=True)
class ExplorationSizeProposal:
    decision: str
    executable: bool
    final_notional_usd: float | None
    final_quantity: float | None
    max_loss_if_stop_usd: float | None
    reason: str
    schema_version: str = SCHEMA_VERSION


def propose_exploration_size(
    *,
    mark_price: float,
    stop_distance_fraction: float,     # e.g. 0.02 for a 2% stop
    venue_min_notional: float,
    venue_min_qty: float,
    venue_qty_step: float,
    # catastrophic-loss envelope (Category D — hard outer limits, NEVER relaxed):
    catastrophic_max_loss_usd: float,   # absolute per-trade dollar-loss ceiling
    catastrophic_max_notional_usd: float,  # absolute notional/exposure ceiling
) -> ExplorationSizeProposal:
    """Return the smallest venue-executable size and whether it fits the envelope.

    The smallest executable position is exactly the venue minimum (rounded UP to a
    valid qty step). Its bounded loss is qty*price*stop_distance_fraction. If that
    bounded loss (and its notional) fit inside the catastrophic envelope, the
    exploration is executable at that minimum size — which is NOT "raising risk to
    hit the minimum": it is the smallest real position, and its dollar loss is
    checked against the hard ceiling, not inflated to reach it. If it does not fit,
    we do not grow risk — we tell the caller to select another opportunity.
    """
    for name, val in (
        ("mark_price", mark_price),
        ("stop_distance_fraction", stop_distance_fraction),
        ("venue_min_notional", venue_min_notional),
        ("venue_min_qty", venue_min_qty),
        ("venue_qty_step", venue_qty_step),
        ("catastrophic_max_loss_usd", catastrophic_max_loss_usd),
        ("catastrophic_max_notional_usd", catastrophic_max_notional_usd),
    ):
        if not _finite_pos(val):
            return ExplorationSizeProposal(
                decision=SELECT_ANOTHER, executable=False, final_notional_usd=None,
                final_quantity=None, max_loss_if_stop_usd=None,
                reason=f"INVALID_INPUT:{name}",
            )

    # Smallest qty satisfying BOTH venue minimums, rounded UP to a valid step.
    qty_from_notional = venue_min_notional / mark_price
    min_qty = max(venue_min_qty, qty_from_notional)
    steps = math.ceil(min_qty / venue_qty_step - 1e-9)
    final_qty = steps * venue_qty_step
    final_notional = final_qty * mark_price
    max_loss = final_notional * stop_distance_fraction

    # Hard envelope checks — these are the ONLY things that may forbid the trade,
    # and they are never relaxed to force a fill.
    if final_notional > catastrophic_max_notional_usd:
        return ExplorationSizeProposal(
            decision=SELECT_ANOTHER, executable=False,
            final_notional_usd=final_notional, final_quantity=final_qty,
            max_loss_if_stop_usd=max_loss,
            reason="VENUE_MINIMUM_EXCEEDS_CATASTROPHIC_NOTIONAL_CEILING",
        )
    if max_loss > catastrophic_max_loss_usd:
        return ExplorationSizeProposal(
            decision=SELECT_ANOTHER, executable=False,
            final_notional_usd=final_notional, final_quantity=final_qty,
            max_loss_if_stop_usd=max_loss,
            reason="VENUE_MINIMUM_BOUNDED_LOSS_EXCEEDS_CATASTROPHIC_LOSS_CEILING",
        )

    return ExplorationSizeProposal(
        decision=EXECUTABLE, executable=True,
        final_notional_usd=final_notional, final_quantity=final_qty,
        max_loss_if_stop_usd=max_loss,
        reason="SMALLEST_VENUE_EXECUTABLE_SIZE_WITHIN_CATASTROPHIC_ENVELOPE",
    )


__all__ = [
    "SCHEMA_VERSION",
    "EXECUTABLE",
    "SELECT_ANOTHER",
    "ExplorationSizeProposal",
    "propose_exploration_size",
]
