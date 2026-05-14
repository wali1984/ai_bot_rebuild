"""
Toxicity Shield (Option 1 core)
==============================

Computes:
- toxicity score T in [0,1]
- effective_edge_after_cost (best-effort)
- execution_mode: WAIT_REPRICE | PASSIVE_MAKER | AGGRESSIVE_TAKER

This is designed to be:
- always-on (no static 1m block)
- execution-conditional (enter only when edge-after-cost is positive)
- compatible with no-loss (reduces adverse selection churn)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)
TOXICITY_LOG_VERBOSE = os.getenv("TOXICITY_LOG_VERBOSE", "true").lower() in ("1", "true", "yes")


@dataclass
class ToxicityDecision:
    toxicity: float
    execution_mode: str  # WAIT_REPRICE | PASSIVE_MAKER | AGGRESSIVE_TAKER
    effective_edge: float  # dimensionless proxy (>=0 means acceptable)
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


class ToxicityShield:
    def __init__(
        self,
        *,
        round_trip_fee_pct: float,
        min_edge_multiple: float,
        wait_threshold: float,
        maker_threshold: float,
        effective_edge_min_multiple: float,
    ):
        self.round_trip_fee_pct = float(round_trip_fee_pct or 0.0) / 100.0
        self.min_edge_multiple = max(1.0, float(min_edge_multiple or 1.0))
        self.wait_threshold = float(wait_threshold or 0.75)
        self.maker_threshold = float(maker_threshold or 0.45)
        self.effective_edge_min_multiple = max(1.0, float(effective_edge_min_multiple or 1.0))

    def decide(
        self,
        *,
        symbol: str,
        direction: str,
        confidence: float,
        micro: Optional[Dict] = None,
        expected_move_pct: Optional[float] = None,
    ) -> ToxicityDecision:
        """
        micro: dict with best-effort keys:
          - spoof_score (0..1)
          - churn_score (0..1)
          - snapback_score (0..1)
          - fast_move_score (0..1+)
          - fast_move_against (0..1) (optional)
          - imbalance_5 (-1..1)
          - spread_bps (0..??) or spread (bps-like)
        expected_move_pct: expected directional move in percent (0..), optional.
        """
        micro = micro or {}
        conf = _clamp01(float(confidence or 0.0) if float(confidence or 0.0) <= 1.0 else float(confidence or 0.0) / 100.0)
        dir_u = str(direction or "NONE").upper()

        spoof = _clamp01(_f(micro.get("spoof_score"), 0.0))
        churn = _clamp01(_f(micro.get("churn_score"), 0.0))
        snapback = _clamp01(_f(micro.get("snapback_score"), 0.0))
        fast = _clamp01(_f(micro.get("fast_move_score"), 0.0))
        fast_against = _clamp01(_f(micro.get("fast_move_against"), 0.0))

        # Spread in bps (best-effort). Some producers store spread as bps already.
        spread = _f(micro.get("spread_bps", micro.get("spread", 0.0)), 0.0)
        # Normalize: 20 bps considered high for many alts; clamp to [0,1]
        spread_n = _clamp01(float(spread) / 20.0) if spread > 0 else 0.0

        # Toxicity combines manipulation risk + fast-move adverse selection + spread cost.
        manip = max(spoof, churn, snapback)
        tox = _clamp01(max(manip, fast * max(0.25, fast_against), spread_n))

        # Expected move in percent (directional); if unknown, approximate from confidence.
        exp_move_pct = _f(expected_move_pct, default=0.0)
        if exp_move_pct <= 0.0:
            # Very conservative proxy: 0.10%..0.60% based on confidence
            exp_move_pct = 0.10 + 0.50 * conf

        # Cost proxy: round-trip fees plus spread and toxicity penalty.
        fee_pct = max(0.0, float(self.round_trip_fee_pct))
        spread_cost_pct = max(0.0, float(spread) / 10000.0)  # bps -> fraction
        tox_penalty_pct = float(tox) * max(fee_pct, 0.0002) * float(self.min_edge_multiple)
        cost_pct = fee_pct + spread_cost_pct + tox_penalty_pct

        # Effective edge: expected move must exceed costs by a multiple.
        effective_edge = (exp_move_pct / 100.0) - (cost_pct * float(self.effective_edge_min_multiple))

        # Select mode
        if effective_edge <= 0.0:
            return ToxicityDecision(
                toxicity=tox,
                execution_mode="WAIT_REPRICE",
                effective_edge=float(effective_edge),
                reason=f"edge<=0 exp={exp_move_pct:.2f}% cost~{cost_pct*100:.2f}% tox={tox:.2f} spread_bps={spread:.1f}",
            )

        # Edge is positive: prefer maker under moderate/high toxicity.
        if tox >= float(self.wait_threshold):
            result = ToxicityDecision(
                toxicity=tox,
                execution_mode="WAIT_REPRICE",
                effective_edge=float(effective_edge),
                reason=f"toxic_wait tox={tox:.2f} edge={effective_edge:.4f}",
            )
            if TOXICITY_LOG_VERBOSE:
                logger.info(f"☠️ [TOXICITY] {symbol} | mode=WAIT_REPRICE | tox={tox:.2f} | edge={effective_edge:.4f}")
            return result
        if tox >= float(self.maker_threshold):
            result = ToxicityDecision(
                toxicity=tox,
                execution_mode="PASSIVE_MAKER",
                effective_edge=float(effective_edge),
                reason=f"maker_only tox={tox:.2f} edge={effective_edge:.4f}",
            )
            if TOXICITY_LOG_VERBOSE:
                logger.info(f"☠️ [TOXICITY] {symbol} | mode=PASSIVE_MAKER | tox={tox:.2f} | edge={effective_edge:.4f}")
            return result

        result = ToxicityDecision(
            toxicity=tox,
            execution_mode="AGGRESSIVE_TAKER",
            effective_edge=float(effective_edge),
            reason=f"taker_ok tox={tox:.2f} edge={effective_edge:.4f}",
        )
        if TOXICITY_LOG_VERBOSE:
            logger.info(f"☠️ [TOXICITY] {symbol} | mode=AGGRESSIVE_TAKER | tox={tox:.2f} | edge={effective_edge:.4f}")
        return result

