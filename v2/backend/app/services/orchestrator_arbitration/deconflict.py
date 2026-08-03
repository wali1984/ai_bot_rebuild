"""Signal deconfliction (PaperOnly).

Given multiple ``V2Signal`` records for the same symbol, deconflict by:

  1. If the list is empty -> ``MISSING_EVIDENCE_CANNOT_COMPARE``.
  2. If all signals agree on side -> select the strongest (highest
     ``confidence_calibrated``, tie-break by ``expected_move_after_cost_bps``,
     then ``freshness_seconds`` ascending).
  3. If sides disagree -> dominant side wins (sum of
     ``confidence_calibrated``) and the winning side's best signal is
     selected via the same tie-break ordering.

No network IO, no exchange SDK, no Redis client.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from .signal_schema import V2SIGNAL_SIDE_LONG, V2SIGNAL_SIDE_SHORT, V2Signal


DECONFLICT_REASON_EMPTY = "MISSING_EVIDENCE_CANNOT_COMPARE_NO_SIGNALS"
DECONFLICT_REASON_MISSING_EVIDENCE = "MISSING_EVIDENCE_CANNOT_COMPARE"
DECONFLICT_REASON_AGREE = "ALL_SIGNALS_AGREE_ON_SIDE"
DECONFLICT_REASON_DOMINANT_SIDE = "OPPOSITE_SIDES_DOMINANT_CONFIDENCE_WINS"
DECONFLICT_REASON_CONFIDENCE_TIE_BREAK = "EQUAL_AGGREGATE_CONFIDENCE_TIE_BROKEN_BY_EXPECTED_MOVE"


@dataclass(frozen=True)
class DeconflictResult:
    selected_side: Optional[str]
    selected_signal: Optional[V2Signal]
    conflict_reason: str
    long_aggregate_confidence: float
    short_aggregate_confidence: float
    considered_count: int


def _signal_sort_key(signal: V2Signal):
    # Highest confidence first, then highest expected_move, then freshest.
    return (
        -float(signal.confidence_calibrated),
        -float(signal.expected_move_after_cost_bps),
        float(signal.freshness_seconds),
    )


def deconflict_signals(signals: Sequence[V2Signal]) -> DeconflictResult:
    if not isinstance(signals, (list, tuple)):
        return DeconflictResult(
            selected_side=None,
            selected_signal=None,
            conflict_reason=DECONFLICT_REASON_MISSING_EVIDENCE,
            long_aggregate_confidence=0.0,
            short_aggregate_confidence=0.0,
            considered_count=0,
        )

    typed: List[V2Signal] = [s for s in signals if isinstance(s, V2Signal)]
    if not typed:
        return DeconflictResult(
            selected_side=None,
            selected_signal=None,
            conflict_reason=DECONFLICT_REASON_EMPTY,
            long_aggregate_confidence=0.0,
            short_aggregate_confidence=0.0,
            considered_count=0,
        )

    long_signals = [s for s in typed if s.side == V2SIGNAL_SIDE_LONG]
    short_signals = [s for s in typed if s.side == V2SIGNAL_SIDE_SHORT]

    long_conf = sum(float(s.confidence_calibrated) for s in long_signals)
    short_conf = sum(float(s.confidence_calibrated) for s in short_signals)

    if not short_signals:
        winner = sorted(long_signals, key=_signal_sort_key)[0]
        return DeconflictResult(
            selected_side=V2SIGNAL_SIDE_LONG,
            selected_signal=winner,
            conflict_reason=DECONFLICT_REASON_AGREE,
            long_aggregate_confidence=long_conf,
            short_aggregate_confidence=short_conf,
            considered_count=len(typed),
        )
    if not long_signals:
        winner = sorted(short_signals, key=_signal_sort_key)[0]
        return DeconflictResult(
            selected_side=V2SIGNAL_SIDE_SHORT,
            selected_signal=winner,
            conflict_reason=DECONFLICT_REASON_AGREE,
            long_aggregate_confidence=long_conf,
            short_aggregate_confidence=short_conf,
            considered_count=len(typed),
        )

    if long_conf > short_conf:
        winner = sorted(long_signals, key=_signal_sort_key)[0]
        return DeconflictResult(
            selected_side=V2SIGNAL_SIDE_LONG,
            selected_signal=winner,
            conflict_reason=DECONFLICT_REASON_DOMINANT_SIDE,
            long_aggregate_confidence=long_conf,
            short_aggregate_confidence=short_conf,
            considered_count=len(typed),
        )
    if short_conf > long_conf:
        winner = sorted(short_signals, key=_signal_sort_key)[0]
        return DeconflictResult(
            selected_side=V2SIGNAL_SIDE_SHORT,
            selected_signal=winner,
            conflict_reason=DECONFLICT_REASON_DOMINANT_SIDE,
            long_aggregate_confidence=long_conf,
            short_aggregate_confidence=short_conf,
            considered_count=len(typed),
        )

    # Equal aggregate confidence -> break the tie by best per-side candidate
    # using the same sort key, and prefer the side whose strongest signal has
    # the larger expected_move_after_cost_bps. If still tied, fail closed.
    best_long = sorted(long_signals, key=_signal_sort_key)[0]
    best_short = sorted(short_signals, key=_signal_sort_key)[0]
    if (
        float(best_long.expected_move_after_cost_bps)
        > float(best_short.expected_move_after_cost_bps)
    ):
        return DeconflictResult(
            selected_side=V2SIGNAL_SIDE_LONG,
            selected_signal=best_long,
            conflict_reason=DECONFLICT_REASON_CONFIDENCE_TIE_BREAK,
            long_aggregate_confidence=long_conf,
            short_aggregate_confidence=short_conf,
            considered_count=len(typed),
        )
    if (
        float(best_short.expected_move_after_cost_bps)
        > float(best_long.expected_move_after_cost_bps)
    ):
        return DeconflictResult(
            selected_side=V2SIGNAL_SIDE_SHORT,
            selected_signal=best_short,
            conflict_reason=DECONFLICT_REASON_CONFIDENCE_TIE_BREAK,
            long_aggregate_confidence=long_conf,
            short_aggregate_confidence=short_conf,
            considered_count=len(typed),
        )
    return DeconflictResult(
        selected_side=None,
        selected_signal=None,
        conflict_reason=DECONFLICT_REASON_MISSING_EVIDENCE,
        long_aggregate_confidence=long_conf,
        short_aggregate_confidence=short_conf,
        considered_count=len(typed),
    )
