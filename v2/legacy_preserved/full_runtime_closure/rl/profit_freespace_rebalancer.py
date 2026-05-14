"""
Profit-only freespace rebalancer (no-loss compatible)
====================================================

When the system wants to open/increase a high-quality position but is blocked by
portfolio slot or total margin constraints, this module can propose a *profit-only*
partial close on a "weak" position to free margin.

Hard invariants:
- NEVER closes at a loss (requires net profit after fees estimate > 0).
- Only triggers when trainer deems the position "weak" (regime / model context).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
FREESPACE_LOG_VERBOSE = os.getenv("FREESPACE_LOG_VERBOSE", "true").lower() in ("1", "true", "yes")


@dataclass
class FreespaceCandidate:
    account_id: str
    symbol: str
    side: str  # LONG|SHORT
    close_pct: float
    est_net_profit_usd: float
    reason: str


def _f(x, default=0.0) -> float:
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def _clamp(x: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except Exception:
        return lo


class ProfitFreespaceRebalancer:
    def __init__(self, *, round_trip_fee_pct: float):
        # round_trip_fee_pct is percent-of-notional (e.g., 0.04 means 0.04%)
        self.round_trip_fee_pct = max(0.0, float(round_trip_fee_pct or 0.0)) / 100.0

    def propose(
        self,
        *,
        account_id: str,
        positions_by_symbol_side: Dict[str, Dict[str, dict]],
        required_margin_usd: float,
        weakness: Dict[str, float],
        max_close_pct: float = 0.35,
    ) -> Optional[FreespaceCandidate]:
        """
        positions_by_symbol_side: {symbol: {'LONG': posdict, 'SHORT': posdict}}
          posdict expects best-effort keys:
            - unrealized_pnl (usd)
            - notional (usd) or (entry_price*size)
            - margin_used (usd)
        weakness: {symbol: weakness_score} where higher means "weaker"/more likely to give back profits.
        """
        req = max(0.0, float(required_margin_usd or 0.0))
        if req <= 0:
            return None

        best: Optional[FreespaceCandidate] = None

        # Adaptive weakness threshold (no static cut):
        # Use a percentile of the current weakness distribution so "weak" is relative to the current
        # portfolio state / model context.
        try:
            wvals = [float(v or 0.0) for v in (weakness or {}).values()]
            wvals = [v for v in wvals if v == v]  # drop NaN
        except Exception:
            wvals = []
        w_thr = 0.0
        if len(wvals) >= 3:
            wvals.sort()
            # 70th percentile → only trim the weaker tail, but adapts if everything is weak/strong.
            idx = max(0, min(len(wvals) - 1, int(0.70 * (len(wvals) - 1))))
            w_thr = float(wvals[idx])

        for sym, legs in (positions_by_symbol_side or {}).items():
            w = float(weakness.get(sym, 0.0) or 0.0)
            # only consider weak positions relative to the current distribution
            if w < w_thr:
                continue
            for side in ("LONG", "SHORT"):
                p = (legs or {}).get(side)
                if not isinstance(p, dict):
                    continue
                upnl = _f(p.get("unrealized_pnl"), 0.0)
                if upnl <= 0:
                    continue  # profit-only
                margin_used = _f(p.get("margin_used", p.get("initialMargin")), 0.0)
                notional = _f(p.get("notional"), 0.0)
                if notional <= 0 and margin_used > 0:
                    lev = _f(p.get("leverage"), 1.0)
                    notional = margin_used * max(1.0, lev)

                if margin_used <= 0 or notional <= 0:
                    continue

                # Choose close_pct sufficient to free req, capped.
                close_pct = _clamp(req / margin_used, 0.10, float(max_close_pct))

                # Estimate net profit after fees for the closing slice:
                # realized_upnl_slice - roundtrip_fee(on notional slice)
                slice_upnl = upnl * close_pct
                fee_est = notional * close_pct * self.round_trip_fee_pct
                net = slice_upnl - fee_est
                if net <= 0:
                    continue

                cand = FreespaceCandidate(
                    account_id=str(account_id),
                    symbol=str(sym),
                    side=side,
                    close_pct=float(close_pct),
                    est_net_profit_usd=float(net),
                    reason=f"profit_freespace weak={w:.2f} upnl={upnl:.2f} margin={margin_used:.2f} fee_est={fee_est:.2f}",
                )
                if FREESPACE_LOG_VERBOSE:
                    logger.info(f"📦 [FREESPACE] CANDIDATE | {account_id}:{sym} {side} | close={close_pct:.1%} | net=${net:.2f} | weak={w:.2f}")
                if best is None:
                    best = cand
                else:
                    # Prefer freeing more margin with higher weakness and higher net profit
                    score_best = best.est_net_profit_usd * 0.7 + best.close_pct * 100.0 * 0.3
                    score_new = cand.est_net_profit_usd * 0.7 + cand.close_pct * 100.0 * 0.3
                    if score_new > score_best:
                        best = cand

        if best and FREESPACE_LOG_VERBOSE:
            logger.info(f"🚀 [FREESPACE] SELECTED | {best.account_id}:{best.symbol} {best.side} | close={best.close_pct:.1%} | net=${best.est_net_profit_usd:.2f}")
        return best



def emit_freespace_proposal(redis_client, candidate: FreespaceCandidate) -> bool:
    """Emit a freespace rebalance proposal to the orchestrator."""
    if redis_client is None or candidate is None:
        return False
    try:
        from rl.proposal_bus import emit_proposal
        proposal = {
            "account_id": str(candidate.account_id),
            "symbol": str(candidate.symbol),
            "action": f"PARTIAL_CLOSE_{candidate.side.upper()}",
            "action_name": f"PARTIAL_CLOSE_{candidate.side.upper()}",
            "timeframe": "multi",
            "close_fraction": float(candidate.close_pct),
            "confidence": 0.85,  # Freespace uses structural confidence
            "action_category": "FREESPACE",
            "source": "profit_freespace_rebalancer",
            "profit_intent": True,
            "net_profit_usd": float(candidate.est_net_profit_usd),
            "reason": candidate.reason,
            "event": "FREESPACE_PROPOSAL",
        }
        try:
            from risk.trainer_alignment import enrich_proposal_with_trainer
            enrich_proposal_with_trainer(redis_client, proposal)
        except Exception:
            pass
        success = emit_proposal(redis_client, stream="proposals:freespace", proposal=proposal)
        if success and FREESPACE_LOG_VERBOSE:
            logger.info(f"📦 [FREESPACE] PROPOSAL_EMITTED | {candidate.account_id}:{candidate.symbol} {candidate.side} | close={candidate.close_pct:.1%}")
        return success
    except Exception as e:
        logger.warning(f"[FREESPACE] emit_proposal error: {e}")
        return False
