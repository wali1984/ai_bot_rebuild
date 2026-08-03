"""V2 paper-only symbol-concentration guard (no live, no canary).

Computes the recent intent-share per symbol from the paper-shadow
observation evidence and decides whether a new candidate intent should
be allowed, down-ranked, or BLOCKED on the basis of concentration.

This guard runs in the PAPER and SHADOW lanes only. It cannot enable
live trading, cannot change ``live_symbols``, cannot touch the live
gate. Its outputs feed the paper-fill simulator and the replay miner
so that paper-edge analytics see a more diverse symbol mix.

Hard rules (asserted by tests):
- No exchange-mutating call.
- No live/canary approval.
- No Redis write outside ``v2:`` namespace.
- No legacy filesystem mutation.
- Decision logic is deterministic given the windowed evidence.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Iterable

DEFAULT_MAX_RECENT_INTENT_SHARE_PER_SYMBOL = 0.60
DEFAULT_MIN_SYMBOL_DIVERSITY = 3
DEFAULT_DOWNRANK_SHARE_THRESHOLD = 0.40

ALLOW = "ALLOW"
DOWNRANK = "DOWNRANK"
BLOCK = "BLOCK"

BLOCK_REASON_OVERCONCENTRATED = "block_paper_symbol_overconcentrated"
DOWNRANK_REASON_CONCENTRATED = "downrank_paper_symbol_concentrated"
BLOCK_REASON_BELOW_DIVERSITY = "block_paper_symbol_below_min_diversity"


@dataclass(frozen=True)
class ConcentrationDecision:
    """Output of the paper-only concentration guard."""

    decision: str
    reason: str | None
    symbol: str
    recent_share: float
    distinct_symbol_count: int
    window_total: int
    threshold_max_share: float
    threshold_min_diversity: int


def _normalise_distribution(
    distribution: Mapping[str, int] | None,
) -> tuple[dict[str, int], int]:
    if not distribution:
        return {}, 0
    cleaned: dict[str, int] = {}
    total = 0
    for sym, count in distribution.items():
        if not sym:
            continue
        try:
            n = int(count)
        except (TypeError, ValueError):
            continue
        if n < 0:
            continue
        cleaned[str(sym).upper()] = n
        total += n
    return cleaned, total


def compute_share(
    distribution: Mapping[str, int] | None,
    symbol: str,
) -> tuple[float, int]:
    """Return (share, total) for ``symbol`` inside ``distribution``."""
    cleaned, total = _normalise_distribution(distribution)
    if total <= 0:
        return 0.0, 0
    n = cleaned.get(str(symbol).upper(), 0)
    return float(n) / float(total), total


def evaluate(
    distribution: Mapping[str, int] | None,
    symbol: str,
    *,
    max_share: float = DEFAULT_MAX_RECENT_INTENT_SHARE_PER_SYMBOL,
    min_diversity: int = DEFAULT_MIN_SYMBOL_DIVERSITY,
    downrank_share: float = DEFAULT_DOWNRANK_SHARE_THRESHOLD,
) -> ConcentrationDecision:
    """Evaluate a candidate paper intent against concentration thresholds.

    Returns ``ConcentrationDecision`` with one of ``ALLOW``,
    ``DOWNRANK``, or ``BLOCK``. The decision never mutates state.
    """
    cleaned, total = _normalise_distribution(distribution)
    distinct = len({s for s, n in cleaned.items() if n > 0})
    share, _ = compute_share(distribution, symbol)
    sym_upper = str(symbol).upper()

    if total > 0 and distinct < int(min_diversity):
        # Allow the candidate IF it would lift diversity; block if it
        # would only add weight to an already-dominant symbol.
        if sym_upper in cleaned:
            return ConcentrationDecision(
                decision=BLOCK,
                reason=BLOCK_REASON_BELOW_DIVERSITY,
                symbol=sym_upper,
                recent_share=share,
                distinct_symbol_count=distinct,
                window_total=total,
                threshold_max_share=float(max_share),
                threshold_min_diversity=int(min_diversity),
            )
        return ConcentrationDecision(
            decision=ALLOW,
            reason=None,
            symbol=sym_upper,
            recent_share=share,
            distinct_symbol_count=distinct,
            window_total=total,
            threshold_max_share=float(max_share),
            threshold_min_diversity=int(min_diversity),
        )

    if share >= float(max_share):
        return ConcentrationDecision(
            decision=BLOCK,
            reason=BLOCK_REASON_OVERCONCENTRATED,
            symbol=sym_upper,
            recent_share=share,
            distinct_symbol_count=distinct,
            window_total=total,
            threshold_max_share=float(max_share),
            threshold_min_diversity=int(min_diversity),
        )

    if share >= float(downrank_share):
        return ConcentrationDecision(
            decision=DOWNRANK,
            reason=DOWNRANK_REASON_CONCENTRATED,
            symbol=sym_upper,
            recent_share=share,
            distinct_symbol_count=distinct,
            window_total=total,
            threshold_max_share=float(max_share),
            threshold_min_diversity=int(min_diversity),
        )

    return ConcentrationDecision(
        decision=ALLOW,
        reason=None,
        symbol=sym_upper,
        recent_share=share,
        distinct_symbol_count=distinct,
        window_total=total,
        threshold_max_share=float(max_share),
        threshold_min_diversity=int(min_diversity),
    )


def replay_miner_feed(
    decisions: Iterable[ConcentrationDecision],
) -> list[dict]:
    """Render decisions into a serialisable list for the replay miner."""
    out: list[dict] = []
    for d in decisions:
        out.append(
            {
                "decision": d.decision,
                "reason": d.reason,
                "symbol": d.symbol,
                "recent_share": d.recent_share,
                "distinct_symbol_count": d.distinct_symbol_count,
                "window_total": d.window_total,
                "threshold_max_share": d.threshold_max_share,
                "threshold_min_diversity": d.threshold_min_diversity,
                "live_safety": {
                    "live_gate_status": "blocked_human_only",
                    "live_symbols": [],
                    "exchange_action_taken": False,
                    "old_redis_writes": False,
                },
            }
        )
    return out
