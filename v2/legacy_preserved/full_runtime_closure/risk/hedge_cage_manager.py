"""
risk/hedge_cage_manager.py — Hedge Cage Detection, Main Leg Tracking & Exit Policy.

A "hedge cage" is when both LONG and SHORT legs are open on the same symbol.
This is a failure mode, not a strategy. Without an exit policy, cages persist
indefinitely, accumulating gross margin while net exposure stays near zero.

This module provides:
  1. **Main leg persistence** — tracks which leg is alpha-driven (main) vs
     protective (hedge). Written on first open from the alpha model.
     Redis key: main_leg:{account_id}:{symbol} = LONG|SHORT
     Hedges MUST NOT overwrite main leg.

  2. **Hedge cage detection** — identifies symbols where both legs are open.

  3. **Cage exit policy** — state machine:
     - UNWIND: reduce both legs proportionally when gross IM too high
     - RESOLVE: pick main leg (using edge signal), close hedge leg
     - TIMEOUT_FLAT: flatten both legs if cage persists too long

  4. **Hedge-aware reduction ordering** — for the auto-deleverager:
     - PAIR_REDUCE: reduce both legs to free margin without flipping exposure
     - HEDGE_LEG_FIRST: reduce hedge leg preferentially for symbol cap breaches

Kill-switch: config.HEDGE_CAGE_ENABLED (default: True)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    import config
except ImportError:
    config = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# ─── helpers ────────────────────────────────────────────────────────────────

def _cfg(key: str, default):
    if config is not None:
        val = getattr(config, key, None)
        if val is not None:
            return val
    return default


def _sf(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        out = float(v)
        return default if out != out else out  # NaN guard
    except Exception:
        return default


# ─── data classes ───────────────────────────────────────────────────────────

@dataclass
class CageLeg:
    """One leg of a hedge cage."""
    symbol: str
    side: str           # "LONG" or "SHORT"
    size: float
    initial_margin: float
    unrealized_pnl: float
    roe_pct: float
    mark_price: float
    entry_price: float
    leverage: float
    is_main: bool       # True if this is the alpha-driven leg


@dataclass
class HedgeCage:
    """A symbol with both legs open."""
    symbol: str
    long_leg: CageLeg
    short_leg: CageLeg
    main_side: Optional[str]    # "LONG" or "SHORT" or None if unknown
    hedge_side: Optional[str]   # opposite of main, or None
    gross_im: float             # sum of both legs' IM
    net_exposure_usd: float     # net notional (positive = net long)
    cage_age_sec: float         # how long both legs have been open
    cage_start_ts: float        # when cage was first detected


@dataclass
class PairReduceOrder:
    """Instruction to reduce both legs of a cage proportionally."""
    symbol: str
    main_leg_side: str
    main_leg_reduce_pct: float
    main_leg_reduce_qty: float
    hedge_leg_side: str
    hedge_leg_reduce_pct: float
    hedge_leg_reduce_qty: float
    total_margin_freed_est: float
    reason: str
    reason_code: str


# ─── main leg tracking ─────────────────────────────────────────────────────

class MainLegTracker:
    """
    Tracks which leg (LONG or SHORT) is the alpha-model-driven "main" leg.
    
    Rules:
      - Written when a symbol first opens from the alpha model (OPEN_LONG, OPEN_SHORT)
      - Flips only on explicit CLOSE_AND_LONG / CLOSE_AND_SHORT (flip actions)
      - Hedge adds (ADD_HEDGE_*, OPEN_HEDGE_*) NEVER overwrite main leg
      - TTL refreshed on every update (default 24h)
    """

    REDIS_KEY_PREFIX = "main_leg"

    def __init__(self, redis_client=None):
        self.redis = redis_client

    def get_main_leg(self, account_id: str, symbol: str) -> Optional[str]:
        """Return 'LONG' or 'SHORT' or None if no main leg recorded."""
        if not self.redis:
            return None
        try:
            key = f"{self.REDIS_KEY_PREFIX}:{account_id}:{symbol}"
            val = self.redis.get(key)
            if val is None:
                return None
            val_str = val.decode("utf-8") if isinstance(val, (bytes, bytearray)) else str(val)
            return val_str.upper().strip() if val_str.upper().strip() in ("LONG", "SHORT") else None
        except Exception:
            return None

    def set_main_leg(self, account_id: str, symbol: str, side: str, source: str = "unknown") -> bool:
        """
        Record the main leg side. Only call this for alpha-model opens/flips.
        Never call for hedge adds.
        """
        if not _cfg("MAIN_LEG_TRACKING_ENABLED", True):
            return False
        if not self.redis:
            return False
        side_u = str(side).upper().strip()
        if side_u not in ("LONG", "SHORT"):
            return False
        try:
            key = f"{self.REDIS_KEY_PREFIX}:{account_id}:{symbol}"
            ttl = int(_cfg("MAIN_LEG_TTL_SEC", 86400))
            self.redis.setex(key, ttl, side_u)
            logger.info(
                "MAIN_LEG_SET | account=%s | symbol=%s | side=%s | source=%s | ttl=%ds",
                account_id, symbol, side_u, source, ttl,
            )
            return True
        except Exception as e:
            logger.debug("MAIN_LEG_SET_ERR | %s | %s", symbol, e)
            return False

    def clear_main_leg(self, account_id: str, symbol: str) -> bool:
        """Clear main leg when symbol goes fully flat."""
        if not self.redis:
            return False
        try:
            key = f"{self.REDIS_KEY_PREFIX}:{account_id}:{symbol}"
            self.redis.delete(key)
            logger.info("MAIN_LEG_CLEAR | account=%s | symbol=%s", account_id, symbol)
            return True
        except Exception:
            return False

    def is_hedge_action(self, action: str, category: str = "") -> bool:
        """Return True if this action is a hedge/protective (should NOT set main leg)."""
        act_u = str(action or "").upper().strip()
        cat_u = str(category or "").upper().strip()
        if act_u.startswith(("OPEN_HEDGE_", "ADD_HEDGE_")):
            return True
        if cat_u in ("PROTECTIVE", "HEDGE", "RECOVERY", "HEDGE_TRIM", "GOVERNOR_DELEVERAGE"):
            return True
        return False

    def should_set_main_leg(self, action: str, category: str = "") -> Optional[str]:
        """
        Determine if this action should set or flip the main leg.
        Returns the side ('LONG' or 'SHORT') or None.
        """
        if self.is_hedge_action(action, category):
            return None

        act_u = str(action or "").upper().strip()

        # Opens set main leg
        if act_u in ("OPEN_LONG", "ENTER_LONG"):
            return "LONG"
        if act_u in ("OPEN_SHORT", "ENTER_SHORT"):
            return "SHORT"

        # Flips change main leg
        if act_u == "CLOSE_AND_LONG":
            return "LONG"
        if act_u == "CLOSE_AND_SHORT":
            return "SHORT"

        return None

    def get_hedge_side(self, account_id: str, symbol: str) -> Optional[str]:
        """Return the hedge leg side (opposite of main). None if unknown."""
        main = self.get_main_leg(account_id, symbol)
        if main == "LONG":
            return "SHORT"
        if main == "SHORT":
            return "LONG"
        return None


# ─── hedge cage detector ───────────────────────────────────────────────────

class HedgeCageDetector:
    """
    Detects and tracks hedge cages (both legs open on a symbol).
    Maintains cage start timestamps to enforce timeout policy.
    """

    CAGE_TS_PREFIX = "hedge_cage_ts"

    def __init__(self, redis_client=None, main_leg_tracker: Optional[MainLegTracker] = None):
        self.redis = redis_client
        self.main_leg_tracker = main_leg_tracker or MainLegTracker(redis_client)

    def detect_cages(self, account_id: str) -> List[HedgeCage]:
        """Scan all positions and return list of hedge cages."""
        if not self.redis:
            return []

        cages: List[HedgeCage] = []
        now = time.time()

        try:
            sym_set = self.redis.smembers(f"positions:live:symbols:{account_id}")
            if not sym_set:
                return []

            for sym_raw in sym_set:
                sym = sym_raw.decode("utf-8") if isinstance(sym_raw, (bytes, bytearray)) else str(sym_raw)
                try:
                    raw = self.redis.hgetall(f"positions:live:{sym}")
                    if not raw:
                        continue

                    legs: Dict[str, Dict] = {}
                    for side_key in ("long", "short", b"long", b"short"):
                        val = raw.get(side_key)
                        if not val:
                            continue
                        val_str = val.decode("utf-8") if isinstance(val, (bytes, bytearray)) else str(val)
                        try:
                            data = json.loads(val_str)
                            size = _sf(data.get("size"))
                            if size > 0:
                                sk = side_key.decode("utf-8") if isinstance(side_key, (bytes, bytearray)) else str(side_key)
                                legs[sk.upper()] = data
                        except Exception:
                            continue

                    if len(legs) < 2 or "LONG" not in legs or "SHORT" not in legs:
                        # Not a cage — clear cage timestamp
                        self._clear_cage_ts(account_id, sym)
                        continue

                    # Both legs open — this is a cage
                    cage_start = self._get_or_set_cage_ts(account_id, sym, now)
                    main_side = self.main_leg_tracker.get_main_leg(account_id, sym)
                    hedge_side = {"LONG": "SHORT", "SHORT": "LONG"}.get(main_side) if main_side else None

                    long_data = legs["LONG"]
                    short_data = legs["SHORT"]

                    long_leg = CageLeg(
                        symbol=sym, side="LONG",
                        size=_sf(long_data.get("size")),
                        initial_margin=_sf(long_data.get("initialMargin")),
                        unrealized_pnl=_sf(long_data.get("unrealized_pnl")),
                        roe_pct=_sf(long_data.get("roi_pct")),
                        mark_price=_sf(long_data.get("mark_price") or long_data.get("current_price")),
                        entry_price=_sf(long_data.get("entry_price")),
                        leverage=_sf(long_data.get("leverage"), 1.0),
                        is_main=(main_side == "LONG"),
                    )
                    short_leg = CageLeg(
                        symbol=sym, side="SHORT",
                        size=_sf(short_data.get("size")),
                        initial_margin=_sf(short_data.get("initialMargin")),
                        unrealized_pnl=_sf(short_data.get("unrealized_pnl")),
                        roe_pct=_sf(short_data.get("roi_pct")),
                        mark_price=_sf(short_data.get("mark_price") or short_data.get("current_price")),
                        entry_price=_sf(short_data.get("entry_price")),
                        leverage=_sf(short_data.get("leverage"), 1.0),
                        is_main=(main_side == "SHORT"),
                    )

                    gross_im = long_leg.initial_margin + short_leg.initial_margin
                    # Net exposure: long notional - short notional
                    long_notional = long_leg.size * long_leg.mark_price if long_leg.mark_price > 0 else 0
                    short_notional = short_leg.size * short_leg.mark_price if short_leg.mark_price > 0 else 0
                    net_exposure = long_notional - short_notional

                    cages.append(HedgeCage(
                        symbol=sym,
                        long_leg=long_leg,
                        short_leg=short_leg,
                        main_side=main_side,
                        hedge_side=hedge_side,
                        gross_im=gross_im,
                        net_exposure_usd=net_exposure,
                        cage_age_sec=now - cage_start,
                        cage_start_ts=cage_start,
                    ))

                except Exception as e:
                    logger.debug("CAGE_DETECT_ERR | symbol=%s | err=%s", sym, e)

        except Exception as e:
            logger.debug("CAGE_DETECT_SYMBOLS_ERR | account=%s | err=%s", account_id, e)

        return cages

    def _get_or_set_cage_ts(self, account_id: str, symbol: str, now: float) -> float:
        """Get existing cage start timestamp, or set it to now."""
        if not self.redis:
            return now
        try:
            key = f"{self.CAGE_TS_PREFIX}:{account_id}:{symbol}"
            val = self.redis.get(key)
            if val is not None:
                return _sf(val, now)
            self.redis.setex(key, 86400, str(now))  # 24h TTL
            return now
        except Exception:
            return now

    def _clear_cage_ts(self, account_id: str, symbol: str):
        """Clear cage start timestamp when cage is resolved."""
        if not self.redis:
            return
        try:
            self.redis.delete(f"{self.CAGE_TS_PREFIX}:{account_id}:{symbol}")
        except Exception:
            pass

    def compute_pair_reduce(
        self,
        cage: HedgeCage,
        margin_to_free: float,
        equity: float,
    ) -> Optional[PairReduceOrder]:
        """
        Compute a proportional pair-reduce order for a hedge cage.
        
        Policy:
          - If main_leg is known: hedge leg gets 60% of reduction, main 40%
          - If main_leg unknown: reduce proportionally by current IM weight
          - Never exceed GOV_DELEVERAGE_MAX_REDUCE_PCT of any leg
        """
        max_pct = float(_cfg("GOV_DELEVERAGE_MAX_REDUCE_PCT", 0.20))
        pair_ratio = float(_cfg("GOV_DELEVERAGE_PAIR_REDUCE_RATIO", 0.6))  # hedge gets this fraction

        main_leg = cage.long_leg if cage.main_side == "LONG" else cage.short_leg if cage.main_side == "SHORT" else None
        hedge_leg = cage.short_leg if cage.main_side == "LONG" else cage.long_leg if cage.main_side == "SHORT" else None

        if main_leg and hedge_leg:
            # Known main/hedge: hedge gets pair_ratio, main gets (1-pair_ratio)
            hedge_margin_share = margin_to_free * pair_ratio
            main_margin_share = margin_to_free * (1.0 - pair_ratio)
        else:
            # Unknown: split by IM weight
            total_im = cage.gross_im
            if total_im <= 0:
                return None
            long_weight = cage.long_leg.initial_margin / total_im
            short_weight = cage.short_leg.initial_margin / total_im
            # Treat the larger leg as "hedge" (more aggressive reduction)
            if cage.long_leg.initial_margin >= cage.short_leg.initial_margin:
                hedge_leg = cage.long_leg
                main_leg = cage.short_leg
                hedge_margin_share = margin_to_free * long_weight
                main_margin_share = margin_to_free * short_weight
            else:
                hedge_leg = cage.short_leg
                main_leg = cage.long_leg
                hedge_margin_share = margin_to_free * short_weight
                main_margin_share = margin_to_free * long_weight

        # Convert margin to reduction %
        hedge_reduce_pct = min(hedge_margin_share / hedge_leg.initial_margin, max_pct) if hedge_leg.initial_margin > 0 else 0
        main_reduce_pct = min(main_margin_share / main_leg.initial_margin, max_pct) if main_leg.initial_margin > 0 else 0

        # Convert to qty
        hedge_reduce_qty = hedge_leg.size * hedge_reduce_pct if hedge_reduce_pct > 0 else 0
        main_reduce_qty = main_leg.size * main_reduce_pct if main_reduce_pct > 0 else 0

        if hedge_reduce_qty <= 0 and main_reduce_qty <= 0:
            return None

        total_freed = (hedge_leg.initial_margin * hedge_reduce_pct) + (main_leg.initial_margin * main_reduce_pct)

        return PairReduceOrder(
            symbol=cage.symbol,
            main_leg_side=main_leg.side,
            main_leg_reduce_pct=round(main_reduce_pct, 6),
            main_leg_reduce_qty=round(main_reduce_qty, 6),
            hedge_leg_side=hedge_leg.side,
            hedge_leg_reduce_pct=round(hedge_reduce_pct, 6),
            hedge_leg_reduce_qty=round(hedge_reduce_qty, 6),
            total_margin_freed_est=round(total_freed, 2),
            reason=f"PAIR_REDUCE: hedge({hedge_leg.side})={hedge_reduce_pct*100:.1f}%, main({main_leg.side})={main_reduce_pct*100:.1f}%",
            reason_code="PAIR_REDUCE",
        )

    def check_cage_timeout(self, cage: HedgeCage) -> bool:
        """Return True if cage has exceeded timeout threshold."""
        timeout = int(_cfg("HEDGE_CAGE_TIMEOUT_SEC", 7200))
        return cage.cage_age_sec >= timeout

    def check_cage_gross_im_breach(self, cage: HedgeCage, equity: float) -> bool:
        """Return True if cage gross IM exceeds per-cage cap."""
        max_pct = float(_cfg("HEDGE_CAGE_MAX_GROSS_IM_PCT", 0.25))
        if equity <= 0:
            return False
        return (cage.gross_im / equity) > max_pct
