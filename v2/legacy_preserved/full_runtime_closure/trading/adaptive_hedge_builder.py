"""
Adaptive Hedge Builder
======================
Builds hedges progressively as market conditions indicate increasing reversal risk.

Logic:
1. Monitor squeeze potential, momentum, and liquidation proximity
2. Gradually build opposite-side hedge (dynamic target 0% → max based on conditions)
3. When reversal confirmed, flip hedge to become primary position
4. Repeat cycle in opposite direction

This complements the existing HEDGE_BUILD state machine with adaptive sizing.
"""

import logging
import time
import json
import math
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, List
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class HedgeState:
    """Current hedge state for a symbol"""
    symbol: str
    primary_side: str  # LONG or SHORT
    primary_entry: float
    primary_size_usd: float
    hedge_side: str  # Opposite of primary
    hedge_entry_avg: float = 0.0
    hedge_size_pct: float = 0.0  # % of primary position
    hedge_entries: List[Dict] = field(default_factory=list)  # Track each hedge entry
    last_update: float = 0.0
    
    @property
    def hedge_size_usd(self) -> float:
        return self.primary_size_usd * (self.hedge_size_pct / 100)


@dataclass
class HedgeDecision:
    """Decision from hedge builder"""
    action: str  # HOLD, BUILD_HEDGE, ADD_HEDGE, CLOSE_PRIMARY, FLIP, TAKE_PROFIT
    hedge_pct_to_add: float = 0.0  # % of primary to add as hedge
    primary_pct_to_close: float = 0.0  # % of primary to close
    urgency: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL
    reason: str = ""
    suggested_entry: Optional[float] = None
    
    # Context
    squeeze_score: float = 0.0
    momentum_score: float = 0.0
    liq_distance_pct: float = 0.0
    reversal_probability: float = 0.0
    # Dynamic diagnostics (Jan 2026): used for explainability + anti-churn coordination
    risk_score: float = 0.0
    continuation_score: float = 0.0
    continuation_suppression: float = 0.0
    target_hedge_pct: float = 0.0
    current_hedge_pct: float = 0.0


class AdaptiveHedgeBuilder:
    """
    Builds hedges progressively based on market conditions.
    
    Hedge Building Rules:
    1. Start building when squeeze/volatility/liquidation proximity indicates elevated reversal risk
    2. Add more as momentum fades (peak momentum → declining)
    3. Increase as adverse liquidation proximity tightens (continuous, no hard 2% cliff)
    4. Flip when momentum reverses and favorable liq cluster nearby
    5. COUNTER_SQUEEZE: Build defensive hedge when losing + adverse imbalance
    """
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.hedge_states: Dict[str, HedgeState] = {}
        # Keyed by (account_id:symbol) to avoid cross-account interference in multi-account mode.
        self.momentum_history: Dict[str, List[Tuple[float, float]]] = defaultdict(list)  # key -> [(ts, momentum)]
        self.stats = defaultdict(int)
        logger.info("AdaptiveHedgeBuilder initialized with progressive hedge logic")
    
    def _get_momentum_trend(self, key: str, current_momentum: float) -> Tuple[float, str]:
        """
        Track momentum history and detect peak/declining trend.
        Returns: (momentum_drop_from_peak, trend: "RISING" | "PEAKED" | "DECLINING")
        """
        now = time.time()
        history = self.momentum_history[key]
        
        # Add current reading
        history.append((now, current_momentum))
        
        # Keep last 30 minutes of data
        cutoff = now - 1800
        self.momentum_history[key] = [(ts, m) for ts, m in history if ts > cutoff]
        history = self.momentum_history[key]
        
        if len(history) < 3:
            return 0.0, "UNKNOWN"
        
        # Find peak momentum in recent history
        peak_momentum = max(m for _, m in history)
        
        # Calculate drop from peak
        momentum_drop = peak_momentum - current_momentum
        
        # Determine trend
        recent = [m for ts, m in history[-5:]]  # Last 5 readings
        if len(recent) >= 3:
            if recent[-1] > recent[-2] > recent[-3]:
                trend = "RISING"
            elif recent[-1] < recent[-2] < recent[-3]:
                trend = "DECLINING"
            elif momentum_drop > 0.2:
                trend = "PEAKED"
            else:
                trend = "STABLE"
        else:
            trend = "UNKNOWN"
        
        return momentum_drop, trend
    
    def _calculate_counter_squeeze_hedge_pct(
        self,
        primary_side: str,
        orderbook_imbalance: float,
        roi_pct: float,
        adverse_liq_distance_pct: float,
        current_hedge_pct: float
    ) -> Tuple[float, str, float]:
        """
        Calculate hedge percentage for COUNTER_SQUEEZE mode.
        Triggers when position is losing AND there's adverse orderbook imbalance.
        
        For LONG positions: negative imbalance = selling pressure (adverse)
        For SHORT positions: positive imbalance = buying pressure (adverse)
        
        Returns: (target_pct, level_name, risk_score)
        """
        # Dynamic sizing: continuous target (no fixed 10/15/25/40/60 rungs).
        target_pct = float(current_hedge_pct or 0.0)
        level_name = "HOLD"
        
        # Calculate adverse imbalance (absolute value of imbalance going against us)
        if primary_side == "LONG":
            # For LONG, negative imbalance is adverse (selling pressure)
            adverse_imbal = -orderbook_imbalance if orderbook_imbalance < 0 else 0.0
        else:
            # For SHORT, positive imbalance is adverse (buying pressure)
            adverse_imbal = orderbook_imbalance if orderbook_imbalance > 0 else 0.0

        try:
            from config import ADAPTIVE_HEDGE_MAX_SIZE_PCT
            max_size_pct = float(ADAPTIVE_HEDGE_MAX_SIZE_PCT)
        except Exception:
            max_size_pct = 50.0

        # Normalize inputs to smooth 0..1 factors (no hard thresholds).
        imbal_factor = max(0.0, min(1.0, abs(float(adverse_imbal))))
        liq = max(0.0, float(adverse_liq_distance_pct or 99.0))
        liq_factor = 1.0 / (1.0 + liq)  # closer to liq => higher factor

        # Loss factor: only matters when underwater; smooth via exp (no step cliffs).
        loss_factor = 0.0
        try:
            roi = float(roi_pct or 0.0)
            if roi < 0:
                # roi=-0 ->0, roi=-inf ->1
                loss_factor = 1.0 - math.exp(roi / 8.0)
        except Exception:
            loss_factor = 0.0
        loss_factor = max(0.0, min(1.0, loss_factor))

        # Counter-squeeze risk combines: adverse imbalance + underwater + liq proximity.
        counter_risk = (0.45 * imbal_factor) + (0.35 * loss_factor) + (0.20 * liq_factor)
        counter_risk = max(0.0, min(1.0, float(counter_risk)))

        # Non-linear mapping to target hedge coverage.
        counter_target = max_size_pct * (counter_risk ** 1.6)
        if counter_target > target_pct:
            target_pct = counter_target
            level_name = f"COUNTER_DYN:risk={counter_risk:.2f}"

        return float(target_pct), level_name, float(counter_risk)
    
    def _calculate_target_hedge_pct(
        self,
        *,
        primary_side: str,
        squeeze_potential: float,
        momentum_drop: float,
        momentum_score: float,
        momentum_trend: str,
        rsi: float,
        adx: float,
        orderbook_imbalance: float,
        adverse_liq_distance_pct: float,
        current_hedge_pct: float,
    ) -> Tuple[float, str, float, float, float]:
        """
        Determine target hedge percentage based on conditions.
        Returns: (target_pct, level_name, risk_score, continuation_score, suppression)
        """
        target_pct = float(current_hedge_pct or 0.0)
        level_name = "HOLD"

        try:
            from config import ADAPTIVE_HEDGE_MAX_SIZE_PCT
            max_size_pct = float(ADAPTIVE_HEDGE_MAX_SIZE_PCT)
        except Exception:
            max_size_pct = 50.0

        # Smooth 0..1 factorization (no discrete 10/20/35/50 steps).
        squeeze = max(0.0, min(1.0, float(squeeze_potential or 0.0)))
        mom = max(0.0, min(1.0, float(momentum_drop or 0.0)))
        liq = max(0.0, float(adverse_liq_distance_pct or 99.0))
        liq_factor = 1.0 / (1.0 + liq)  # closer => higher

        # Composite reversal risk score
        risk = (0.45 * squeeze) + (0.25 * mom) + (0.30 * liq_factor)
        risk = max(0.0, min(1.0, float(risk)))

        # ------------------------------------------------------------------
        # Continuation-aware suppression (Jan 2026)
        #
        # Goal:
        # - Avoid opening hedges at local tops/bottoms when the trend is still
        #   strongly continuing (hedge cost/fees become "buying insurance at the wick").
        # - But MUST bypass suppression when reversal risk is truly high.
        #
        # Method:
        # - Compute a smooth continuation_score in [0,1] from momentum + ADX + RSI,
        #   aligned to the primary position direction.
        # - Reduce hedge risk by a suppression factor that fades out when:
        #   - liquidation proximity is high (liq_factor near 1), or
        #   - risk itself is high (1 - risk near 0)
        # ------------------------------------------------------------------
        try:
            ps = str(primary_side or "").upper()
        except Exception:
            ps = "LONG"

        # Directional alignment: map momentum_score into a continuation probability.
        # We assume momentum_score is roughly in [-1, +1] (clamp defensively).
        ms = max(-1.0, min(1.0, float(momentum_score or 0.0)))
        mom_dir = ms if ps == "LONG" else -ms
        cont_mom = max(0.0, min(1.0, (mom_dir + 1.0) / 2.0))  # aligned -> 1, opposite -> 0

        # ADX: higher trend strength -> more continuation. Normalize softly.
        adx_v = max(0.0, float(adx or 0.0))
        cont_adx = max(0.0, min(1.0, adx_v / 50.0))

        # RSI: treat distance from 50 in direction of the trend as continuation.
        rsi_v = max(0.0, min(100.0, float(rsi or 50.0)))
        rsi_dir = (rsi_v - 50.0) / 50.0  # [-1, +1]
        rsi_dir = rsi_dir if ps == "LONG" else -rsi_dir
        cont_rsi = max(0.0, min(1.0, (rsi_dir + 1.0) / 2.0))

        # Momentum trend factor (avoid suppressing when momentum is clearly declining)
        mt = str(momentum_trend or "").upper()
        if mt == "RISING":
            trend_fac = 1.0
        elif mt == "STABLE":
            trend_fac = 0.6
        elif mt == "PEAKED":
            trend_fac = 0.25
        elif mt == "DECLINING":
            trend_fac = 0.0
        else:
            trend_fac = 0.5

        continuation_score = (0.45 * cont_mom) + (0.35 * cont_adx) + (0.20 * cont_rsi)
        continuation_score = max(0.0, min(1.0, float(continuation_score))) * float(trend_fac)

        # Orderbook alignment: if imbalance supports the position, boost continuation slightly.
        try:
            ob = max(-1.0, min(1.0, float(orderbook_imbalance or 0.0)))
        except Exception:
            ob = 0.0
        ob_dir = ob if ps == "LONG" else -ob
        ob_support = max(0.0, min(1.0, (ob_dir + 1.0) / 2.0))
        continuation_score = max(0.0, min(1.0, float(0.85 * continuation_score + 0.15 * ob_support)))

        # Suppression fades out when liq_factor high (close to liq) or risk high (bypass gating for big moves).
        suppression = float(continuation_score) * float(max(0.0, min(1.0, 1.0 - float(liq_factor)))) * float(max(0.0, min(1.0, 1.0 - float(risk))))
        suppression = max(0.0, min(1.0, float(suppression)))

        risk_adj = float(risk) * float(1.0 - suppression)
        risk_adj = max(0.0, min(1.0, float(risk_adj)))

        dynamic_target = max_size_pct * (risk_adj ** 1.6)
        if dynamic_target > target_pct:
            target_pct = dynamic_target
            level_name = f"DYN:risk={risk_adj:.2f}|cont={continuation_score:.2f}|sup={suppression:.2f}"

        return float(target_pct), level_name, float(risk_adj), float(continuation_score), float(suppression)
    
    def _should_flip(
        self,
        primary_side: str,
        momentum_score: float,
        momentum_trend: str,
        favorable_liq_distance_pct: float,
        favorable_liq_strength: float,
        pnl_pct: float
    ) -> Tuple[bool, str]:
        """
        Determine if we should flip from primary to hedge becoming new primary.
        """
        reasons = []
        score = 0.0
        
        # 1. Strong momentum reversal against primary
        if primary_side == "LONG" and momentum_score < -0.5:
            score += 0.3
            reasons.append(f"NEG_MOMENTUM:{momentum_score:.2f}")
        elif primary_side == "SHORT" and momentum_score > 0.5:
            score += 0.3
            reasons.append(f"POS_MOMENTUM:{momentum_score:.2f}")
        
        # 2. Declining momentum trend
        if momentum_trend == "DECLINING":
            score += 0.2
            reasons.append("MOMENTUM_DECLINING")
        
        # 3. Favorable liquidation cluster nearby (squeeze potential for hedge)
        if favorable_liq_distance_pct < 2.0 and favorable_liq_strength > 0.6:
            score += 0.3
            reasons.append(f"FAV_LIQ_NEARBY:{favorable_liq_distance_pct:.1f}%")
        
        # 4. Primary in profit (good exit point)
        if pnl_pct > 1.5:
            score += 0.2
            reasons.append(f"PROFIT_SECURED:{pnl_pct:.1f}%")
        
        should_flip = score >= 0.6
        reason = " + ".join(reasons) if reasons else "NO_FLIP_CONDITIONS"
        
        return should_flip, reason
    
    def analyze_hedge_opportunity(
        self,
        symbol: str,
        primary_side: str,
        primary_entry: float,
        primary_size_usd: float,
        current_price: float,
        conditions,  # MarketConditions object
        account_id: str = "primary",
        current_hedge_pct: Optional[float] = None,
    ) -> HedgeDecision:
        """
        Analyze current conditions and decide on hedge action.
        
        Args:
            symbol: Trading pair
            primary_side: Current primary position side (LONG/SHORT)
            primary_entry: Entry price of primary position
            primary_size_usd: Size of primary position in USD
            current_price: Current market price
            conditions: MarketConditions with liq levels, momentum, squeeze, etc.
        
        Returns:
            HedgeDecision with recommended action
        """
        self.stats['total_analyzed'] += 1
        aid = account_id or "primary"
        
        # Get or create hedge state
        state_key = f"{aid}:{symbol}:{primary_side}"
        if state_key not in self.hedge_states:
            self.hedge_states[state_key] = HedgeState(
                symbol=symbol,
                primary_side=primary_side,
                primary_entry=primary_entry,
                primary_size_usd=primary_size_usd,
                hedge_side="SHORT" if primary_side == "LONG" else "LONG"
            )
        
        state = self.hedge_states[state_key]

        # Sync in the currently-observed hedge size (from live positions).
        # IMPORTANT: this must reflect REAL exposure so we can continue adding hedge
        # after partial profit-taking reduces the hedge leg.
        try:
            if current_hedge_pct is not None:
                state.hedge_size_pct = max(0.0, float(current_hedge_pct))
        except Exception:
            pass
        
        # Calculate PnL
        if primary_side == "LONG":
            pnl_pct = ((current_price - primary_entry) / primary_entry) * 100
            adverse_liq_dist = conditions.liq_long_distance_pct
            adverse_liq_str = conditions.liq_long_strength
            favorable_liq_dist = conditions.liq_short_distance_pct
            favorable_liq_str = conditions.liq_short_strength
        else:
            pnl_pct = ((primary_entry - current_price) / primary_entry) * 100
            adverse_liq_dist = conditions.liq_short_distance_pct
            adverse_liq_str = conditions.liq_short_strength
            favorable_liq_dist = conditions.liq_long_distance_pct
            favorable_liq_str = conditions.liq_long_strength
        
        # Get momentum trend
        momentum_drop, momentum_trend = self._get_momentum_trend(f"{aid}:{symbol}", conditions.momentum_score)
        
        # Calculate target hedge percentage from standard squeeze logic
        target_hedge_pct, hedge_level, std_risk, cont_score, cont_sup = self._calculate_target_hedge_pct(
            primary_side=primary_side,
            squeeze_potential=conditions.squeeze_potential,
            momentum_drop=momentum_drop,
            momentum_score=conditions.momentum_score,
            momentum_trend=momentum_trend,
            rsi=getattr(conditions, "rsi", 50.0),
            adx=getattr(conditions, "adx", 25.0),
            orderbook_imbalance=getattr(conditions, "orderbook_imbalance", 0.0),
            adverse_liq_distance_pct=adverse_liq_dist,
            current_hedge_pct=state.hedge_size_pct,
        )
        
        # Calculate target hedge percentage from COUNTER_SQUEEZE logic
        # This kicks in when position is losing + adverse orderbook imbalance
        counter_squeeze_pct, counter_level, counter_risk = self._calculate_counter_squeeze_hedge_pct(
            primary_side=primary_side,
            orderbook_imbalance=getattr(conditions, 'orderbook_imbalance', 0.0),
            roi_pct=pnl_pct,
            adverse_liq_distance_pct=adverse_liq_dist,
            current_hedge_pct=state.hedge_size_pct
        )
        
        # Take the maximum hedge recommendation from both systems
        if counter_squeeze_pct > target_hedge_pct:
            target_hedge_pct = counter_squeeze_pct
            hedge_level = counter_level
            # Counter-squeeze is loss/imbalance driven; don't suppress it as "trend continuation".
            std_risk = float(counter_risk)
            cont_score = 0.0
            cont_sup = 0.0
            logger.info(f"[COUNTER_SQUEEZE] {symbol} {primary_side}: "
                       f"imbal={getattr(conditions, 'orderbook_imbalance', 0.0):.2f}, "
                       f"roi={pnl_pct:.1f}%, liq_dist={adverse_liq_dist:.1f}% "
                       f"-> {counter_level} target={counter_squeeze_pct:.0f}%")
        
        # Check for flip conditions
        should_flip, flip_reason = self._should_flip(
            primary_side=primary_side,
            momentum_score=conditions.momentum_score,
            momentum_trend=momentum_trend,
            favorable_liq_distance_pct=favorable_liq_dist,
            favorable_liq_strength=favorable_liq_str,
            pnl_pct=pnl_pct
        )
        
        # Build decision
        decision = HedgeDecision(
            action="HOLD",
            squeeze_score=conditions.squeeze_potential,
            momentum_score=conditions.momentum_score,
            liq_distance_pct=adverse_liq_dist,
            reversal_probability=0.0,
            risk_score=float(std_risk),
            continuation_score=float(cont_score),
            continuation_suppression=float(cont_sup),
            target_hedge_pct=float(target_hedge_pct),
            current_hedge_pct=float(state.hedge_size_pct),
        )
        
        # Decision logic
        if should_flip and state.hedge_size_pct >= 25:
            # Flip: hedge becomes primary, close original primary
            decision.action = "FLIP"
            decision.primary_pct_to_close = 100
            decision.urgency = "HIGH"
            decision.reason = f"FLIP_TO_{state.hedge_side}: {flip_reason}"
            decision.reversal_probability = 0.8
            self.stats['flip_signals'] += 1
            
        elif target_hedge_pct > state.hedge_size_pct:
            # Build more hedge
            pct_to_add = target_hedge_pct - state.hedge_size_pct
            decision.action = "BUILD_HEDGE" if state.hedge_size_pct == 0 else "ADD_HEDGE"
            decision.hedge_pct_to_add = pct_to_add
            decision.urgency = "HIGH" if adverse_liq_dist < 1.5 else ("HIGH" if hedge_level.startswith("COUNTER_") else "MEDIUM")
            
            # Build detailed reason including counter-squeeze info if active
            imbal = getattr(conditions, 'orderbook_imbalance', 0.0)
            if hedge_level.startswith("COUNTER_"):
                decision.reason = f"{hedge_level}: adverse_imbal={abs(imbal):.2f}, " \
                                f"roi={pnl_pct:.1f}%, liq={adverse_liq_dist:.1f}%"
                self.stats['counter_squeeze_signals'] += 1
            else:
                decision.reason = f"{hedge_level}: squeeze={conditions.squeeze_potential:.2f}, " \
                                f"mom_drop={momentum_drop:.2f}, liq={adverse_liq_dist:.1f}%"
            decision.suggested_entry = current_price
            self.stats['hedge_build_signals'] += 1
            
        elif pnl_pct > conditions.atr_pct * 2 and momentum_trend == "DECLINING":
            # Take partial profit on primary
            decision.action = "TAKE_PROFIT"
            decision.primary_pct_to_close = 25
            decision.urgency = "MEDIUM"
            decision.reason = f"PARTIAL_PROFIT: PnL={pnl_pct:.1f}% > 2x ATR, momentum declining"
            self.stats['profit_take_signals'] += 1
            
        else:
            # Hold current positions
            decision.action = "HOLD"
            decision.reason = f"STABLE: squeeze={conditions.squeeze_potential:.2f}, " \
                            f"hedge={state.hedge_size_pct:.0f}%, trend={momentum_trend}"
        
        # Update state timestamp
        state.last_update = time.time()
        
        return decision
    
    def record_hedge_entry(
        self,
        symbol: str,
        primary_side: str,
        hedge_entry_price: float,
        hedge_size_pct: float,
        account_id: str = "primary",
    ):
        """Record a hedge entry for tracking"""
        aid = account_id or "primary"
        state_key = f"{aid}:{symbol}:{primary_side}"
        if state_key in self.hedge_states:
            state = self.hedge_states[state_key]
            state.hedge_entries.append({
                "price": hedge_entry_price,
                "pct": hedge_size_pct,
                "timestamp": time.time()
            })
            state.hedge_size_pct += hedge_size_pct
            
            # Update average entry
            total_weighted = sum(e["price"] * e["pct"] for e in state.hedge_entries)
            total_pct = sum(e["pct"] for e in state.hedge_entries)
            state.hedge_entry_avg = total_weighted / total_pct if total_pct > 0 else 0
            
            logger.info(
                f"HEDGE_RECORDED | {symbol} | side={state.hedge_side} | "
                f"entry=${hedge_entry_price:,.0f} | total={state.hedge_size_pct:.0f}% | "
                f"avg=${state.hedge_entry_avg:,.0f}"
            )
    
    def execute_flip(self, symbol: str, old_primary_side: str, account_id: str = "primary") -> Optional[HedgeState]:
        """
        Execute a flip: hedge becomes primary, create new state.
        Returns the new state for the flipped position.
        """
        aid = account_id or "primary"
        state_key = f"{aid}:{symbol}:{old_primary_side}"
        if state_key not in self.hedge_states:
            return None
        
        old_state = self.hedge_states[state_key]
        
        # Create new state with hedge as primary
        new_state = HedgeState(
            symbol=symbol,
            primary_side=old_state.hedge_side,
            primary_entry=old_state.hedge_entry_avg,
            primary_size_usd=old_state.hedge_size_usd,
            hedge_side=old_primary_side,
            hedge_size_pct=0,
            hedge_entries=[]
        )
        
        # Store new state
        new_key = f"{aid}:{symbol}:{new_state.primary_side}"
        self.hedge_states[new_key] = new_state
        
        # Clear old state
        del self.hedge_states[state_key]
        
        logger.info(
            f"HEDGE_FLIP | {symbol} | {old_primary_side} → {new_state.primary_side} | "
            f"new_entry=${new_state.primary_entry:,.0f} | size=${new_state.primary_size_usd:,.0f}"
        )
        
        self.stats['flips_executed'] += 1
        return new_state
    
    def get_stats(self) -> Dict:
        """Return statistics"""
        return dict(self.stats)
    
    def get_hedge_state(self, symbol: str, primary_side: str, account_id: str = "primary") -> Optional[HedgeState]:
        """Get current hedge state for a position"""
        aid = account_id or "primary"
        return self.hedge_states.get(f"{aid}:{symbol}:{primary_side}")


# Singleton instance
_adaptive_hedge_builder: Optional[AdaptiveHedgeBuilder] = None

def get_adaptive_hedge_builder(redis_client=None) -> AdaptiveHedgeBuilder:
    """Get or create the singleton AdaptiveHedgeBuilder instance"""
    global _adaptive_hedge_builder
    if _adaptive_hedge_builder is None:
        _adaptive_hedge_builder = AdaptiveHedgeBuilder(redis_client=redis_client)
    return _adaptive_hedge_builder

