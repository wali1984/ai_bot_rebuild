"""
Exit Coordinator — Single Decision Point for ALL Position Exits

April Plan v3: Replaces 12+ independent exit mechanisms with one coordinated authority.
Uses all available data: unified_features, microstructure, liquidation levels, 
TA indicators, funding/OI, orderbook depth.

Priority tiers:
  TIER 0: Emergency (liq distance < 2%) — always execute immediately
  TIER 1: Feature-driven exit (liq cascade exhaustion, microstructure reversal)
  TIER 2: Profit protection (leverage-normalized trailing)
  TIER 3: Model signal (gated by hold time + confidence)
  TIER 4: Timer-based (only stagnant positions)

Kill switch: Redis key `killswitch:exit_coordinator` = "1" → bypass, use legacy exits
Config kill switch: EXIT_COORDINATOR_ENABLED = false

Author: WMA AI Trading System — April 2026
"""

import time
import logging
import math
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExitDecision:
    """Result of exit coordinator evaluation."""
    action: str  # HOLD, TRAIL, TIGHTEN_TRAIL, CLOSE, PARTIAL_CLOSE, EMERGENCY_CLOSE
    reason: str
    tier: int  # 0-4
    confidence: float  # 0.0-1.0 how confident in this decision
    close_pct: float = 100.0  # % of position to close
    new_trail_pct: float = 0.0  # New trail distance if TRAIL/TIGHTEN_TRAIL
    tp_target: float = 0.0  # Suggested TP price (0 = no change)
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class ExitCoordinator:
    """
    Single exit authority for all positions. Evaluates ALL exit signals
    and picks the BEST action using prioritized tiers.
    
    Key principle: NEVER exit a winning position unless:
    1. Emergency (liq distance < 2%)
    2. Feature-driven signal (microstructure reversal + liq cascade exhaustion confirmed)
    3. Model CLOSE with high confidence (>0.85) AND position held > min_hold
    """

    def __init__(self, redis_client=None, account_id: str = "primary"):
        self.redis = redis_client
        self.account_id = account_id
        self._last_eval: Dict[str, float] = {}  # symbol:side -> last eval timestamp

    def is_enabled(self) -> bool:
        """Check config + Redis kill switch."""
        try:
            from config import EXIT_COORDINATOR_ENABLED, APRIL_PLAN_EXITS_ENABLED
            if not EXIT_COORDINATOR_ENABLED or not APRIL_PLAN_EXITS_ENABLED:
                return False
        except ImportError:
            return False
        # Redis kill switch (instant, no restart)
        if self.redis:
            try:
                ks = self.redis.get("killswitch:exit_coordinator")
                if ks and str(ks.decode() if isinstance(ks, bytes) else ks) == "1":
                    return False
                ks_all = self.redis.get("killswitch:all_april_plan")
                if ks_all and str(ks_all.decode() if isinstance(ks_all, bytes) else ks_all) == "1":
                    return False
            except Exception:
                pass
        return True

    def evaluate(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        leverage: float,
        margin_usd: float,
        position_age_sec: float,
        features: Dict[str, float] = None,
        micro_ctx: Dict[str, float] = None,
        liq_ctx: Dict[str, float] = None,
        model_signal: Dict[str, Any] = None,
    ) -> ExitDecision:
        """
        Evaluate all exit conditions and return the BEST decision.
        
        Args:
            symbol: Trading pair
            side: LONG or SHORT
            entry_price: Position entry price
            current_price: Current mark price
            leverage: Effective leverage for this position
            margin_usd: Position margin in USD
            position_age_sec: How long position has been open
            features: unified_features data (TA indicators, etc)
            micro_ctx: Microstructure data from coinapi_wsds
            liq_ctx: Liquidation levels data
            model_signal: Latest trainer signal for this symbol (if any)
        
        Returns:
            ExitDecision with action, reason, confidence
        """
        if not self.is_enabled():
            return ExitDecision(action="HOLD", reason="COORDINATOR_DISABLED", tier=4, confidence=0.0)

        features = features or {}
        micro_ctx = micro_ctx or {}
        liq_ctx = liq_ctx or {}
        model_signal = model_signal or {}

        is_long = side.upper() == "LONG"

        # ── Compute position metrics ──
        if is_long:
            price_move_pct = (current_price - entry_price) / entry_price * 100
        else:
            price_move_pct = (entry_price - current_price) / entry_price * 100

        roe_pct = price_move_pct * max(1.0, leverage)
        notional_usd = margin_usd * max(1.0, leverage)
        pnl_usd = notional_usd * price_move_pct / 100.0

        # ── Load config thresholds ──
        try:
            from config import (
                EXIT_COORDINATOR_EMERGENCY_LIQ_DIST_PCT,
                EXIT_COORDINATOR_MIN_HOLD_SEC,
                EXIT_PROFIT_LOCK_MIN_PRICE_MOVE_PCT,
                EXIT_TRAIL_ACTIVATION_PRICE_MOVE_PCT,
                EXIT_TRAIL_DISTANCE_PRICE_PCT,
                EXIT_ROI_KILL_PRICE_MOVE_PCT,
            )
        except ImportError:
            EXIT_COORDINATOR_EMERGENCY_LIQ_DIST_PCT = 2.0
            EXIT_COORDINATOR_MIN_HOLD_SEC = 300
            EXIT_PROFIT_LOCK_MIN_PRICE_MOVE_PCT = 0.50
            EXIT_TRAIL_ACTIVATION_PRICE_MOVE_PCT = 1.0
            EXIT_TRAIL_DISTANCE_PRICE_PCT = 0.40
            EXIT_ROI_KILL_PRICE_MOVE_PCT = -3.0

        # ══════════════════════════════════════════════════════
        # TIER 0: EMERGENCY — liquidation proximity
        # ══════════════════════════════════════════════════════
        liq_distance_pct = 100.0 / max(1.0, leverage)  # Theoretical max adverse move
        # Use actual liq data if available
        actual_liq_dist = float(liq_ctx.get("liquidation_distance_pct", liq_distance_pct))
        if actual_liq_dist < EXIT_COORDINATOR_EMERGENCY_LIQ_DIST_PCT:
            return ExitDecision(
                action="EMERGENCY_CLOSE",
                reason=f"LIQ_PROXIMITY_{actual_liq_dist:.1f}%",
                tier=0,
                confidence=1.0,
                details={"liq_dist": actual_liq_dist, "roe": roe_pct},
            )

        # ══════════════════════════════════════════════════════
        # TIER 1: Feature-driven exit signals
        # Uses microstructure + liquidation + momentum data
        # ══════════════════════════════════════════════════════
        tier1_decision = self._check_feature_driven_exit(
            symbol, side, is_long, price_move_pct, roe_pct, leverage,
            features, micro_ctx, liq_ctx, position_age_sec
        )
        if tier1_decision:
            return tier1_decision

        # ══════════════════════════════════════════════════════
        # TIER 2: Profit protection (leverage-normalized)
        # ══════════════════════════════════════════════════════
        if price_move_pct >= EXIT_TRAIL_ACTIVATION_PRICE_MOVE_PCT:
            # Position has moved enough — activate or tighten trailing
            trail_decision = self._profit_trail_decision(
                symbol, side, price_move_pct, roe_pct, leverage,
                features, micro_ctx, liq_ctx
            )
            if trail_decision and trail_decision.action != "HOLD":
                return trail_decision

        # ══════════════════════════════════════════════════════
        # TIER 3: Model CLOSE signal (gated)
        # ══════════════════════════════════════════════════════
        if model_signal:
            model_decision = self._check_model_close(
                symbol, side, is_long, price_move_pct, roe_pct,
                position_age_sec, model_signal, EXIT_COORDINATOR_MIN_HOLD_SEC
            )
            if model_decision and model_decision.action != "HOLD":
                return model_decision

        # ══════════════════════════════════════════════════════
        # TIER 4: ROI kill (leverage-normalized, last resort)
        # ══════════════════════════════════════════════════════
        if price_move_pct <= EXIT_ROI_KILL_PRICE_MOVE_PCT:
            return ExitDecision(
                action="CLOSE",
                reason=f"ROI_KILL_PRICE_{price_move_pct:.2f}%",
                tier=4,
                confidence=0.9,
                details={"price_move": price_move_pct, "roe": roe_pct, "threshold": EXIT_ROI_KILL_PRICE_MOVE_PCT},
            )

        # Default: HOLD
        return ExitDecision(action="HOLD", reason="NO_EXIT_SIGNAL", tier=4, confidence=0.0)

    def _check_feature_driven_exit(
        self, symbol, side, is_long, price_move_pct, roe_pct, leverage,
        features, micro_ctx, liq_ctx, position_age_sec
    ) -> Optional[ExitDecision]:
        """
        Use liquidation levels, microstructure, TA indicators to decide exit.
        Only fires when multiple data sources confirm reversal.
        """
        signals = []
        signal_count = 0

        # 1. Microstructure reversal: spoof + adverse flow + fast move against us
        spoof_score = float(micro_ctx.get("depth_spoof_score_v2", micro_ctx.get("depth_spoof_score_v1", 0)))
        flow_imb_5s = float(micro_ctx.get("depth_trade_imbalance_5s", 0))
        fast_move = float(micro_ctx.get("depth_fast_move_score_1m", 0))
        snapback = float(micro_ctx.get("depth_snapback_score", 0))

        # Adverse flow: selling pressure on longs, buying on shorts
        adverse_flow = (is_long and flow_imb_5s < -0.3) or (not is_long and flow_imb_5s > 0.3)
        if spoof_score > 0.5 and adverse_flow and fast_move > 0.4:
            signals.append("MICRO_REVERSAL")
            signal_count += 1

        # 2. Liquidation cascade exhaustion: we rode the cascade, now it's done
        if is_long:
            liq_cascade_spent = float(liq_ctx.get("liquidation_short_cascade_exhausted", 0))
        else:
            liq_cascade_spent = float(liq_ctx.get("liquidation_long_cascade_exhausted", 0))
        if liq_cascade_spent > 0.7:
            signals.append("LIQ_CASCADE_EXHAUSTED")
            signal_count += 1

        # 3. TA momentum reversal: RSI extreme + MACD cross + ADX weakening
        rsi = float(features.get("ind_ta_rsi_14", 50))
        macd_line = float(features.get("ind_ta_macd_line", 0))
        macd_signal = float(features.get("ind_ta_macd_signal", 0))
        adx = float(features.get("ind_ta_adx_14", 0))

        rsi_extreme = (is_long and rsi > 80) or (not is_long and rsi < 20)
        macd_cross = (is_long and macd_line < macd_signal) or (not is_long and macd_line > macd_signal)
        adx_weak = adx < 20

        if rsi_extreme and macd_cross:
            signals.append("TA_REVERSAL")
            signal_count += 1

        # 4. Snapback score high (price reverting mean)
        if snapback > 0.6 and price_move_pct > 0.3:
            signals.append("SNAPBACK")
            signal_count += 1

        # Need 2+ confirming signals for feature-driven exit (no single-source exits)
        if signal_count >= 2 and price_move_pct > 0.10:  # Must be in profit
            # Decide: partial or full close based on remaining momentum
            if adx > 25 and not adx_weak:
                # Still some trend left — partial close
                return ExitDecision(
                    action="PARTIAL_CLOSE",
                    reason=f"FEATURE_EXIT_{'_'.join(signals)}",
                    tier=1,
                    confidence=min(0.95, signal_count * 0.3),
                    close_pct=50.0,
                    details={"signals": signals, "price_move": price_move_pct, "roe": roe_pct},
                )
            else:
                return ExitDecision(
                    action="CLOSE",
                    reason=f"FEATURE_EXIT_{'_'.join(signals)}",
                    tier=1,
                    confidence=min(0.95, signal_count * 0.3),
                    details={"signals": signals, "price_move": price_move_pct, "roe": roe_pct},
                )

        return None

    def _profit_trail_decision(
        self, symbol, side, price_move_pct, roe_pct, leverage,
        features, micro_ctx, liq_ctx
    ) -> Optional[ExitDecision]:
        """
        Decide how to trail a profitable position using all data sources.
        Returns TRAIL (widen), TIGHTEN_TRAIL, or HOLD.
        """
        try:
            from config import EXIT_TRAIL_DISTANCE_PRICE_PCT
        except ImportError:
            EXIT_TRAIL_DISTANCE_PRICE_PCT = 0.40

        # Base trail distance (price-based, not ROE-based)
        trail_dist = EXIT_TRAIL_DISTANCE_PRICE_PCT

        # ATR-scale: wider trail in volatile markets
        atr_pct = float(features.get("atr_pct", features.get("ind_ta_atr_14", 0)))
        if atr_pct > 0:
            # Trail distance = max(base, 1.5x ATR)
            trail_dist = max(trail_dist, atr_pct * 1.5)

        # Momentum: if strong trend, widen trail
        adx = float(features.get("ind_ta_adx_14", 0))
        rsi = float(features.get("ind_ta_rsi_14", 50))
        if adx > 30:
            trail_dist *= 1.3  # 30% wider in strong trend
        if adx > 45:
            trail_dist *= 1.2  # Additional 20% in very strong trend

        # Liquidation magnet: if liq cluster ahead, let it run
        is_long = side.upper() == "LONG"
        if is_long:
            liq_short_dist = float(liq_ctx.get("liquidation_short_distance_pct", 100))
            liq_strength = float(liq_ctx.get("liquidation_short_strength", 0))
        else:
            liq_short_dist = float(liq_ctx.get("liquidation_long_distance_pct", 100))
            liq_strength = float(liq_ctx.get("liquidation_long_strength", 0))

        if liq_short_dist < 5.0 and liq_strength > 50:
            # Liquidation cluster ahead — widen trail to let price reach it
            trail_dist *= 1.5
            return ExitDecision(
                action="TRAIL",
                reason=f"LIQ_MAGNET_{liq_short_dist:.1f}%_str{liq_strength:.0f}M",
                tier=2,
                confidence=0.7,
                new_trail_pct=trail_dist,
                details={"liq_dist": liq_short_dist, "liq_str": liq_strength, "trail_dist": trail_dist},
            )

        # Microstructure: favorable flow → widen, adverse → tighten
        flow_imb = float(micro_ctx.get("depth_trade_imbalance_5s", 0))
        favorable_flow = (is_long and flow_imb > 0.2) or (not is_long and flow_imb < -0.2)
        adverse_flow = (is_long and flow_imb < -0.2) or (not is_long and flow_imb > 0.2)

        if favorable_flow:
            trail_dist *= 1.2  # Give more room
        elif adverse_flow:
            trail_dist *= 0.7  # Tighten

        # Cap trail distance to prevent unreasonable values
        trail_dist = max(0.10, min(trail_dist, 3.0))

        return ExitDecision(
            action="TRAIL",
            reason="PROFIT_TRAIL_ACTIVE",
            tier=2,
            confidence=0.5,
            new_trail_pct=trail_dist,
            details={"trail_dist": trail_dist, "adx": adx, "flow": flow_imb},
        )

    def _check_model_close(
        self, symbol, side, is_long, price_move_pct, roe_pct,
        position_age_sec, model_signal, min_hold_sec
    ) -> Optional[ExitDecision]:
        """
        Evaluate model CLOSE signal with proper gating.
        """
        action = str(model_signal.get("action", "")).upper()
        if "CLOSE" not in action:
            return None

        confidence = float(model_signal.get("confidence", 0))

        # Must meet hold time
        if position_age_sec < min_hold_sec:
            return None

        # If position is profitable, require higher confidence
        if price_move_pct > 0:
            # Winning position — need strong conviction to close
            required_conf = 0.85 if price_move_pct > 0.5 else 0.70
            if confidence < required_conf:
                # Convert to partial close instead of full close
                if confidence >= 0.60:
                    return ExitDecision(
                        action="PARTIAL_CLOSE",
                        reason=f"MODEL_CLOSE_PARTIAL_conf{confidence:.2f}",
                        tier=3,
                        confidence=confidence,
                        close_pct=30.0,  # Only close 30%
                        details={"model_conf": confidence, "price_move": price_move_pct},
                    )
                return None  # Don't close winner with low confidence
        else:
            # Losing position — allow close with lower confidence
            if confidence >= 0.50:
                return ExitDecision(
                    action="CLOSE",
                    reason=f"MODEL_CLOSE_LOSER_conf{confidence:.2f}",
                    tier=3,
                    confidence=confidence,
                    details={"model_conf": confidence, "price_move": price_move_pct},
                )

        # High confidence close
        if confidence >= 0.85:
            return ExitDecision(
                action="CLOSE",
                reason=f"MODEL_CLOSE_HIGH_CONF_{confidence:.2f}",
                tier=3,
                confidence=confidence,
                details={"model_conf": confidence, "price_move": price_move_pct},
            )

        return None

    def fetch_position_context(self, symbol: str, side: str) -> Tuple[Dict, Dict, Dict]:
        """
        Fetch all available data for exit evaluation from Redis.
        Returns (features, micro_ctx, liq_ctx) tuple.
        """
        features = {}
        micro_ctx = {}
        liq_ctx = {}

        if not self.redis:
            return features, micro_ctx, liq_ctx

        try:
            # 1. Unified features (5m primary, fallback to 15m)
            for tf in ("5m", "15m", "1h"):
                raw = self.redis.hgetall(f"unified_features:{symbol}:{tf}")
                if raw:
                    for k, v in raw.items():
                        ks = k.decode() if isinstance(k, bytes) else str(k)
                        vs = v.decode() if isinstance(v, bytes) else str(v)
                        try:
                            features[ks] = float(vs)
                        except (ValueError, TypeError):
                            features[ks] = vs
                    break  # Use freshest available TF

            # 2. Microstructure (coinapi_wsds)
            ms_raw = self.redis.hgetall(f"msnap:coinapi_wsds:{symbol}")
            if ms_raw:
                for k, v in ms_raw.items():
                    ks = k.decode() if isinstance(k, bytes) else str(k)
                    vs = v.decode() if isinstance(v, bytes) else str(v)
                    try:
                        micro_ctx[ks] = float(vs)
                    except (ValueError, TypeError):
                        micro_ctx[ks] = vs

            # 3. Liquidation data (from unified_features or dedicated keys)
            for tf in ("5m", "1m"):
                liq_raw = self.redis.hgetall(f"unified_features:{symbol}:{tf}")
                if liq_raw:
                    for k, v in liq_raw.items():
                        ks = k.decode() if isinstance(k, bytes) else str(k)
                        if "liquidation" in ks.lower() or "liq_" in ks.lower():
                            vs = v.decode() if isinstance(v, bytes) else str(v)
                            try:
                                liq_ctx[ks] = float(vs)
                            except (ValueError, TypeError):
                                pass
                    if liq_ctx:
                        break

        except Exception as e:
            logger.debug(f"[EXIT_COORD] Context fetch error {symbol}: {e}")

        return features, micro_ctx, liq_ctx

    def compute_leverage_normalized_threshold(
        self, base_price_move_pct: float, leverage: float
    ) -> float:
        """
        Convert a price-move-based threshold to ROE% for a given leverage.
        
        Example: base_price_move_pct=0.5%, leverage=86x → ROE = 43%
                 base_price_move_pct=0.5%, leverage=20x → ROE = 10%
        """
        return base_price_move_pct * max(1.0, leverage)
