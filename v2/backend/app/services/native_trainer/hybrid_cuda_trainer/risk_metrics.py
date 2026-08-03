"""Risk-adjusted trajectory metrics for the promotion gate (WI-2).

The DL-crypto review finds Sortino/CVaR-optimised agents beat raw-return agents
with lower downside -- which matches CLAUDE.md's priority order (survival ->
liquidation avoidance -> controlled drawdown, and "reject a high-win-rate
strategy if tail losses can erase gains"). These are pure, dependency-free
functions (no torch/numpy needed) so the promotion gate can consult them without
touching the model or the protected venv.

All functions operate on a per-decision realised-return series (e.g. bps or USD).
"""
from __future__ import annotations

import math
from collections.abc import Sequence


def _finite(values: Sequence[float]) -> list[float]:
    out: list[float] = []
    for v in values:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(f)
    return out


def downside_deviation(returns: Sequence[float], target: float = 0.0) -> float:
    """Root-mean-square of returns below ``target`` (the Sortino denominator)."""
    xs = _finite(returns)
    if not xs:
        return 0.0
    sq = [min(0.0, x - target) ** 2 for x in xs]
    return math.sqrt(sum(sq) / len(sq))


def sortino_ratio(returns: Sequence[float], target: float = 0.0) -> float | None:
    """(mean return - target) / downside deviation.

    None when there is no downside (denominator 0) and mean <= target (undefined),
    or when there are no returns. A positive-mean series with zero downside returns
    +inf-equivalent -> we cap to a large finite value so gates compare cleanly.
    """
    xs = _finite(returns)
    if not xs:
        return None
    mean_excess = (sum(xs) / len(xs)) - target
    dd = downside_deviation(xs, target)
    if dd <= 0.0:
        # No downside observations.
        if mean_excess <= 0.0:
            return None
        return 1e6  # unbounded upside with no downside -> very large but finite
    return mean_excess / dd


def cvar(returns: Sequence[float], alpha: float = 0.05) -> float | None:
    """Conditional Value at Risk: mean of the worst ``alpha`` fraction of returns.

    Returned as a SIGNED return (negative = a loss). For a signed loss limit,
    CVaR(5%) >= -max_loss means the worst 5% average is within bounds.
    """
    xs = _finite(returns)
    if not xs:
        return None
    a = min(0.5, max(1e-6, float(alpha)))
    xs_sorted = sorted(xs)
    k = max(1, int(math.ceil(a * len(xs_sorted))))
    tail = xs_sorted[:k]
    return sum(tail) / len(tail)


def risk_adjusted_summary(
    returns: Sequence[float], *, cvar_alpha: float = 0.05, target: float = 0.0
) -> dict:
    xs = _finite(returns)
    n = len(xs)
    wins = sum(1 for x in xs if x > 0)
    return {
        "count": n,
        "mean_return": (sum(xs) / n) if n else None,
        "win_rate": (wins / n) if n else None,
        "sortino_ratio": sortino_ratio(xs, target),
        "downside_deviation": downside_deviation(xs, target),
        "cvar": cvar(xs, cvar_alpha),
        "cvar_alpha": cvar_alpha,
        "worst_return": min(xs) if xs else None,
    }
