"""
Hedge Budget Governor
====================

Goal:
- Hedges are allowed (often bypassing portfolio slot blocks), but hedge *sizing* must remain
  adaptive and safe under a no-loss system.
- Scale hedge margin/notional by confidence and available headroom.
- Prevent runaway hedge-add spam when microstructure is toxic or headroom is low.

This is a downsizer/governor, not a hard blocker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class HedgeBudgetDecision:
    allowed_margin_usd: float
    scaled: bool
    reason: str


def _f(x, default=0.0) -> float:
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def _clamp01(x: float) -> float:
    try:
        if x != x:
            return 0.0
        return max(0.0, min(1.0, float(x)))
    except Exception:
        return 0.0


class HedgeBudgetGovernor:
    def __init__(
        self,
        *,
        max_frac_available: float,
        max_frac_equity: float,
    ):
        self.max_frac_available = float(max_frac_available or 0.0)
        self.max_frac_equity = float(max_frac_equity or 0.0)

    def compute_allowed_margin(
        self,
        *,
        confidence: float,
        portfolio: Dict,
        toxicity: Optional[float] = None,
    ) -> HedgeBudgetDecision:
        """
        portfolio: dict with best-effort keys:
          - total_balance (equity)
          - available_balance (available margin)
          - total_margin_used
          - margin_utilization_pct
        toxicity: optional 0..1 used to reduce step size under toxic microstructure
        """
        try:
            conf = float(confidence or 0.0)
        except Exception:
            conf = 0.0
        if conf > 1.0:
            conf /= 100.0
        conf = _clamp01(conf)

        eq = _f((portfolio or {}).get("total_balance"), 0.0)
        avail = _f((portfolio or {}).get("available_balance"), 0.0)

        if eq <= 0 or avail <= 0:
            return HedgeBudgetDecision(allowed_margin_usd=0.0, scaled=True, reason="no_headroom")

        tox = _clamp01(_f(toxicity, 0.0)) if toxicity is not None else 0.0

        # Confidence scaling: 0.80..0.99 -> 0.35..1.00 scale
        # This is continuous, not thresholded.
        conf_scale = 0.35 + 0.65 * conf
        # Toxicity reduces allowable step size (avoid adverse selection compounding)
        tox_scale = 1.0 - 0.6 * tox

        # Two soft caps: by available and by equity
        cap_avail = max(0.0, avail * max(0.0, self.max_frac_available))
        cap_eq = max(0.0, eq * max(0.0, self.max_frac_equity))
        cap = max(0.0, min(cap_avail, cap_eq))

        allowed = cap * conf_scale * tox_scale
        # Ensure we don't output negative or NaN
        if not (allowed >= 0.0):
            allowed = 0.0

        return HedgeBudgetDecision(
            allowed_margin_usd=float(allowed),
            scaled=True,
            reason=f"cap=min(avail*{self.max_frac_available:.2f},eq*{self.max_frac_equity:.2f})={cap:.2f} conf_scale={conf_scale:.2f} tox_scale={tox_scale:.2f}",
        )

