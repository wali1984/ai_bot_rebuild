#!/usr/bin/env python3
"""
Hedge Intelligence Engine
=========================

Advanced hedge decision system that:
1. Uses multi-source data (CoinAPI, microstructure, anti-MM patterns)
2. Implements anti-churn hysteresis and counter-algo logic
3. Provides validated exits instead of hard blocking

Key Features:
- Counter-Market-Maker Detection: Identifies MM patterns and acts contrary
- Fast Move Detection: Uses CoinAPI and price velocity analysis
- Hysteresis Band: Prevents churn between trigger and breakeven
- Time-Committed Hedges: Minimum hold time prevents premature exits
- Validated Exits: Multi-module consensus before closing hedged positions

Author: AI Trading System
Created: Dec 30, 2025
"""

import os
import time
import json
import logging
import threading
from typing import Dict, Optional, Tuple, List, Any, NamedTuple
from dataclasses import dataclass, field
from collections import defaultdict, deque
from enum import Enum, auto
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS AND DATA STRUCTURES
# =============================================================================

class MarketMakerPattern(Enum):
    """Detected market maker patterns"""
    NONE = "none"
    SPOOFING = "spoofing"           # Large orders placed/cancelled quickly
    LAYERING = "layering"           # Multiple orders at different levels
    SWEEP = "sweep"                 # Aggressive taking of liquidity
    WASH_TRADE = "wash_trade"       # Artificial volume creation
    STOP_HUNT = "stop_hunt"         # Price pushed to trigger stops
    FADE_REVERSAL = "fade_reversal" # Quick reversal after fast move
    ABSORPTION = "absorption"       # Large orders absorbing momentum


class HedgeState(Enum):
    """Lifecycle state of a hedge"""
    NONE = "none"
    PENDING = "pending"             # Hedge recommended but not executed
    ACTIVE = "active"               # Hedge position is open
    COMMITTED = "committed"         # In minimum hold period
    PROFIT_TARGET = "profit_target" # Hedge profitable, waiting for exit signal
    EXIT_VALIDATION = "exit_validation"  # Exit requested, validating
    UNWINDING = "unwinding"         # Hedge being closed


class ExitValidationResult(Enum):
    """Result of exit validation"""
    APPROVED = "approved"           # Exit allowed
    DENIED_TREND = "denied_trend"   # Trend still adverse, keep hedge
    DENIED_MM = "denied_mm"         # Market maker pattern detected
    DENIED_MOMENTUM = "denied_momentum"  # Momentum against exit
    DENIED_COMMITMENT = "denied_commitment"  # Still in commitment period
    DENIED_PROFIT = "denied_profit" # Would exit at loss, wait for profit


@dataclass
class HedgeIntelligenceState:
    """Tracks the intelligence state for a hedged position"""
    symbol: str
    position_side: str
    hedge_side: str
    
    # Timing
    created_at: float = 0.0
    activated_at: float = 0.0
    commitment_expires_at: float = 0.0
    last_evaluation_at: float = 0.0
    
    # State
    state: HedgeState = HedgeState.NONE
    
    # Entry conditions
    entry_roe_pct: float = 0.0
    entry_price: float = 0.0
    entry_risk_score: float = 0.0
    entry_reasons: List[str] = field(default_factory=list)
    
    # Exit conditions
    profit_target_pct: float = 5.0   # Exit hedge when it's +5% profitable
    loss_limit_pct: float = -15.0    # Maximum loss on hedge before force exit
    
    # Anti-churn
    oscillation_count: int = 0
    last_oscillation_at: float = 0.0
    mm_pattern_detections: int = 0
    
    # Market data at entry
    entry_spread_pct: float = 0.0
    entry_depth_ratio: float = 1.0
    entry_volatility: float = 0.0
    
    # Validation history
    exit_denials: List[Tuple[float, str]] = field(default_factory=list)


@dataclass
class MarketIntelligence:
    """Aggregated market intelligence from multiple sources"""
    symbol: str
    timestamp: float
    
    # CoinAPI data
    coinapi_spread_pct: float = 0.0
    coinapi_depth_ratio: float = 1.0  # bid_depth / ask_depth
    coinapi_trade_intensity: float = 0.0  # trades per second
    coinapi_last_trade_side: str = ""
    coinapi_vwap: float = 0.0
    
    # Anti-MM signals
    mm_pattern: MarketMakerPattern = MarketMakerPattern.NONE
    mm_confidence: float = 0.0
    mm_adverse_for: str = ""  # LONG or SHORT - which side is this adverse for
    
    # Fast move detection
    fast_move_detected: bool = False
    fast_move_direction: str = ""  # UP or DOWN
    fast_move_magnitude_pct: float = 0.0
    fast_move_duration_sec: float = 0.0
    
    # Price action
    price_velocity_1m: float = 0.0  # % change per minute
    price_velocity_5m: float = 0.0
    price_acceleration: float = 0.0  # derivative of velocity
    
    # Order flow
    order_flow_imbalance: float = 0.0  # -1 to +1, positive = buying pressure
    large_order_detected: bool = False
    large_order_side: str = ""
    
    # Microstructure
    micro_score: float = 0.5  # 0-1, higher = healthier market
    liquidity_score: float = 0.5


class HedgeIntelligenceEngine:
    """
    Advanced hedge intelligence system with counter-algo capabilities.
    
    Key Principles:
    1. Don't just react to ROE - understand WHY the move is happening
    2. Counter market maker patterns instead of being victimized by them
    3. Use commitment periods to prevent churn
    4. Require multi-factor validation before exits
    """
    
    # Configuration defaults
    DEFAULT_COMMITMENT_SECONDS = 300      # 5 min minimum hedge hold
    DEFAULT_PROFIT_TARGET_PCT = 5.0       # Exit hedge at +5% profit
    DEFAULT_HYSTERESIS_BAND_PCT = 8.0     # Don't oscillate within 8% of trigger
    DEFAULT_MM_DETECTION_LOOKBACK = 60    # Seconds to analyze for MM patterns
    DEFAULT_FAST_MOVE_THRESHOLD_PCT = 1.5 # 1.5% move in < 30 seconds
    
    def __init__(self, redis_client=None, config=None):
        self.redis = redis_client
        self.config = config
        
        # Load configuration
        self.enabled = os.getenv("HEDGE_INTELLIGENCE_ENABLED", "true").lower() in ["1", "true", "yes"]
        self.commitment_seconds = int(os.getenv("HEDGE_COMMITMENT_SECONDS", str(self.DEFAULT_COMMITMENT_SECONDS)))
        self.profit_target_pct = float(os.getenv("HEDGE_PROFIT_TARGET_PCT", str(self.DEFAULT_PROFIT_TARGET_PCT)))
        self.hysteresis_band_pct = float(os.getenv("HEDGE_HYSTERESIS_BAND_PCT", str(self.DEFAULT_HYSTERESIS_BAND_PCT)))
        self.mm_detection_lookback = int(os.getenv("HEDGE_MM_LOOKBACK_SEC", str(self.DEFAULT_MM_DETECTION_LOOKBACK)))
        self.fast_move_threshold = float(os.getenv("HEDGE_FAST_MOVE_PCT", str(self.DEFAULT_FAST_MOVE_THRESHOLD_PCT)))
        
        # State tracking
        self._hedge_states: Dict[str, HedgeIntelligenceState] = {}
        self._price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=120))  # 2 min @ 1s
        self._trade_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
        self._order_flow_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=60))
        
        # Locks for thread safety
        self._state_lock = threading.Lock()
        
        # Cache
        self._intelligence_cache: Dict[str, Tuple[MarketIntelligence, float]] = {}
        self._cache_ttl = 2.0
        
        logger.info(
            f"🧠 HedgeIntelligenceEngine initialized | enabled={self.enabled} | "
            f"commitment={self.commitment_seconds}s | profit_target={self.profit_target_pct}% | "
            f"hysteresis={self.hysteresis_band_pct}%"
        )
    
    # =========================================================================
    # PUBLIC API - ENHANCED HEDGE DECISIONS
    # =========================================================================
    
    def should_open_hedge(
        self,
        symbol: str,
        position_side: str,
        roe_pct: float,
        entry_price: float,
        current_price: float,
        leverage: int,
        base_recommendation_should_hedge: bool = False,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Determine if a hedge should be opened using multi-source intelligence.
        
        Returns:
            Tuple of (should_hedge, reason, details)
        """
        if not self.enabled:
            return base_recommendation_should_hedge, "engine_disabled", {}
        
        # Get market intelligence
        intelligence = self._gather_market_intelligence(symbol)
        details = {
            'roe_pct': roe_pct,
            'mm_pattern': intelligence.mm_pattern.value,
            'fast_move': intelligence.fast_move_detected,
            'micro_score': intelligence.micro_score,
        }
        
        # Check existing hedge state
        with self._state_lock:
            existing_state = self._hedge_states.get(symbol)
            if existing_state and existing_state.state in [HedgeState.ACTIVE, HedgeState.COMMITTED]:
                return False, "hedge_already_active", details
        
        # =================================================================
        # MULTI-SOURCE DECISION LOGIC
        # =================================================================
        
        decision_factors = []
        should_hedge = False
        urgency_boost = 0.0
        
        # 1. ROE TRIGGER with hysteresis
        roe_trigger, roe_reason = self._evaluate_roe_with_hysteresis(symbol, roe_pct, position_side)
        if roe_trigger:
            decision_factors.append(f"roe:{roe_reason}")
            should_hedge = True
        
        # 2. ANTI-MARKET-MAKER SIGNALS
        mm_trigger, mm_reason = self._evaluate_market_maker_threat(intelligence, position_side)
        if mm_trigger:
            decision_factors.append(f"anti_mm:{mm_reason}")
            should_hedge = True
            urgency_boost += 0.2
        
        # 3. FAST MOVE DETECTION
        fast_move_trigger, fm_reason = self._evaluate_fast_move_threat(intelligence, position_side)
        if fast_move_trigger:
            decision_factors.append(f"fast_move:{fm_reason}")
            should_hedge = True
            urgency_boost += 0.3
        
        # 4. ORDER FLOW ANALYSIS
        flow_trigger, flow_reason = self._evaluate_order_flow(intelligence, position_side)
        if flow_trigger:
            decision_factors.append(f"flow:{flow_reason}")
            should_hedge = True
            urgency_boost += 0.1
        
        # 5. COINAPI MICROSTRUCTURE
        micro_trigger, micro_reason = self._evaluate_coinapi_microstructure(intelligence, position_side)
        if micro_trigger:
            decision_factors.append(f"micro:{micro_reason}")
            should_hedge = True
        
        # 6. COUNTER-ALGO SIGNAL
        # If we detect MM trying to push price against us, proactively hedge
        counter_signal = self._generate_counter_algo_signal(symbol, position_side, intelligence)
        if counter_signal:
            decision_factors.append(f"counter_algo:{counter_signal}")
            should_hedge = True
            urgency_boost += 0.25
        
        details['decision_factors'] = decision_factors
        details['urgency_boost'] = urgency_boost
        details['factor_count'] = len(decision_factors)
        
        # Final decision with factor consensus
        # Need at least 2 factors for proactive hedge, or ROE trigger alone for reactive
        if len(decision_factors) >= 2 or (roe_trigger and roe_pct < -15):
            reason = "|".join(decision_factors[:3])
            
            # Create hedge state
            if should_hedge:
                self._create_hedge_state(
                    symbol=symbol,
                    position_side=position_side,
                    roe_pct=roe_pct,
                    entry_price=current_price,
                    risk_score=min(1.0, len(decision_factors) * 0.25),
                    reasons=decision_factors,
                    intelligence=intelligence
                )
            
            return True, reason, details
        elif base_recommendation_should_hedge and roe_pct < -20:
            # Fall back to base recommendation for deep losses
            return True, "roe_deep_loss_fallback", details
        
        return False, "insufficient_factors", details
    
    def validate_hedge_exit(
        self,
        symbol: str,
        action_name: str,
        current_roe_pct: float,
        hedge_pnl_pct: float = 0.0,
    ) -> Tuple[bool, ExitValidationResult, str]:
        """
        Validate whether a hedge exit (CLOSE signal) should be allowed.
        
        Instead of hard blocking, this provides intelligent validation.
        
        Returns:
            Tuple of (allowed, result_enum, explanation)
        """
        if not self.enabled:
            return True, ExitValidationResult.APPROVED, "engine_disabled"
        
        with self._state_lock:
            state = self._hedge_states.get(symbol)
        
        if not state or state.state == HedgeState.NONE:
            # No hedge state tracked - allow exit
            return True, ExitValidationResult.APPROVED, "no_hedge_state_tracked"
        
        now = time.time()
        
        # =================================================================
        # VALIDATION CHECKS
        # =================================================================
        
        # 1. COMMITMENT PERIOD CHECK
        if state.state == HedgeState.COMMITTED and now < state.commitment_expires_at:
            remaining = int(state.commitment_expires_at - now)
            explanation = f"commitment_period_remaining:{remaining}s"
            self._record_exit_denial(symbol, explanation)
            return False, ExitValidationResult.DENIED_COMMITMENT, explanation
        
        # 2. PROFIT TARGET CHECK
        # Don't close hedge at a loss if we can wait for profit
        if hedge_pnl_pct < 0 and state.state != HedgeState.NONE:
            # Check if hedge is still protecting us
            if current_roe_pct < -5:  # Main position still in trouble
                explanation = f"hedge_protecting_main_position:roe={current_roe_pct:.1f}%"
                self._record_exit_denial(symbol, explanation)
                return False, ExitValidationResult.DENIED_PROFIT, explanation
        
        # 3. MARKET CONDITION VALIDATION
        intelligence = self._gather_market_intelligence(symbol)
        
        # 3a. Check for adverse MM patterns
        if intelligence.mm_pattern != MarketMakerPattern.NONE:
            if self._is_mm_pattern_adverse_for_exit(intelligence, state.position_side):
                explanation = f"mm_pattern_adverse:{intelligence.mm_pattern.value}"
                self._record_exit_denial(symbol, explanation)
                return False, ExitValidationResult.DENIED_MM, explanation
        
        # 3b. Check momentum
        momentum_adverse = self._is_momentum_against_exit(intelligence, state.position_side)
        if momentum_adverse and current_roe_pct < -10:
            explanation = f"momentum_against_exit:velocity={intelligence.price_velocity_1m:.2f}%"
            self._record_exit_denial(symbol, explanation)
            return False, ExitValidationResult.DENIED_MOMENTUM, explanation
        
        # 3c. Check trend
        trend_adverse = self._is_trend_against_exit(symbol, state.position_side)
        if trend_adverse and current_roe_pct < -15:
            explanation = "trend_still_adverse"
            self._record_exit_denial(symbol, explanation)
            return False, ExitValidationResult.DENIED_TREND, explanation
        
        # =================================================================
        # EXIT APPROVED
        # =================================================================
        
        # Clean up hedge state
        self._clear_hedge_state(symbol)
        
        return True, ExitValidationResult.APPROVED, "validation_passed"
    
    def activate_hedge(self, symbol: str, hedge_order_id: str = None):
        """Called when hedge order is filled - transitions state to COMMITTED."""
        with self._state_lock:
            state = self._hedge_states.get(symbol)
            if state:
                now = time.time()
                state.activated_at = now
                state.commitment_expires_at = now + self.commitment_seconds
                state.state = HedgeState.COMMITTED
                
                logger.info(
                    f"🔒 [HEDGE_INTEL] {symbol} hedge ACTIVATED | "
                    f"commitment_until={datetime.fromtimestamp(state.commitment_expires_at).strftime('%H:%M:%S')} | "
                    f"order={hedge_order_id}"
                )
    
    def update_hedge_pnl(self, symbol: str, hedge_pnl_pct: float):
        """Update hedge state based on PnL."""
        with self._state_lock:
            state = self._hedge_states.get(symbol)
            if not state:
                return
            
            now = time.time()
            
            # Transition from COMMITTED to ACTIVE after commitment period
            if state.state == HedgeState.COMMITTED and now >= state.commitment_expires_at:
                state.state = HedgeState.ACTIVE
                logger.info(f"🔓 [HEDGE_INTEL] {symbol} commitment period ended - hedge now ACTIVE")
            
            # Transition to PROFIT_TARGET if profitable enough
            if hedge_pnl_pct >= state.profit_target_pct:
                if state.state in [HedgeState.ACTIVE, HedgeState.COMMITTED]:
                    state.state = HedgeState.PROFIT_TARGET
                    logger.info(f"🎯 [HEDGE_INTEL] {symbol} hedge reached profit target: {hedge_pnl_pct:.1f}%")
    
    # =========================================================================
    # MARKET INTELLIGENCE GATHERING
    # =========================================================================
    
    def _gather_market_intelligence(self, symbol: str) -> MarketIntelligence:
        """Gather intelligence from all available sources."""
        now = time.time()
        
        # Check cache
        cached = self._intelligence_cache.get(symbol)
        if cached and (now - cached[1]) < self._cache_ttl:
            return cached[0]
        
        intelligence = MarketIntelligence(symbol=symbol, timestamp=now)
        
        if self.redis:
            # 1. CoinAPI data
            self._gather_coinapi_data(symbol, intelligence)
            
            # 2. Microstructure data
            self._gather_microstructure_data(symbol, intelligence)
            
            # 3. Order flow data
            self._gather_order_flow_data(symbol, intelligence)
            
            # 4. Detect MM patterns
            self._detect_market_maker_patterns(symbol, intelligence)
            
            # 5. Detect fast moves
            self._detect_fast_moves(symbol, intelligence)
        
        # Cache result
        self._intelligence_cache[symbol] = (intelligence, now)
        
        return intelligence
    
    def _gather_coinapi_data(self, symbol: str, intelligence: MarketIntelligence):
        """Gather CoinAPI WebSocket data."""
        try:
            # CoinAPI market snapshot
            key = f"msnap:coinapi_wsds:{symbol}"
            data = self.redis.hgetall(key)
            if data:
                intelligence.coinapi_spread_pct = float(data.get('spread_pct', 0) or 0)
                intelligence.coinapi_vwap = float(data.get('vwap', 0) or 0)
                
                bid_depth = float(data.get('bid_depth', 1) or 1)
                ask_depth = float(data.get('ask_depth', 1) or 1)
                intelligence.coinapi_depth_ratio = bid_depth / max(0.001, ask_depth)
                
                intelligence.coinapi_last_trade_side = data.get('last_trade_side', '')
            
            # Trade intensity from recent trades
            trades_key = f"trades:coinapi:{symbol}"
            trades_raw = self.redis.lrange(trades_key, 0, 99)
            if trades_raw:
                trades = [json.loads(t) if isinstance(t, str) else t for t in trades_raw]
                if len(trades) >= 2:
                    time_span = trades[0].get('timestamp', time.time()) - trades[-1].get('timestamp', time.time())
                    if time_span > 0:
                        intelligence.coinapi_trade_intensity = len(trades) / time_span
        except Exception as e:
            logger.debug(f"[HEDGE_INTEL] CoinAPI gather failed: {e}")
    
    def _gather_microstructure_data(self, symbol: str, intelligence: MarketIntelligence):
        """Gather microstructure data from unified features."""
        try:
            # Try multiple timeframes
            for tf in ['1m', '5m', '15m']:
                key = f"unified_features:{symbol}:{tf}"
                data = self.redis.hgetall(key)
                if data:
                    intelligence.micro_score = float(data.get('microstructure_score', 0.5) or 0.5)
                    intelligence.order_flow_imbalance = float(data.get('order_flow_imbalance', 0) or 0)
                    intelligence.liquidity_score = float(data.get('liquidity_score', 0.5) or 0.5)
                    
                    # Price velocity
                    price_change = float(data.get('price_change_pct', 0) or 0)
                    if tf == '1m':
                        intelligence.price_velocity_1m = price_change
                    elif tf == '5m':
                        intelligence.price_velocity_5m = price_change / 5
                    break
        except Exception as e:
            logger.debug(f"[HEDGE_INTEL] Microstructure gather failed: {e}")
    
    def _gather_order_flow_data(self, symbol: str, intelligence: MarketIntelligence):
        """Gather order flow analysis data."""
        try:
            # Anti-MM signals
            key = f"anti_mm:{symbol}"
            data = self.redis.hgetall(key)
            if data:
                spoof_score = float(data.get('spoof_score', 0) or 0)
                sweep_detected = data.get('sweep_detected', 'false').lower() == 'true'
                large_order_side = data.get('large_order_side', '')
                
                if spoof_score > 0.7:
                    intelligence.mm_pattern = MarketMakerPattern.SPOOFING
                    intelligence.mm_confidence = spoof_score
                elif sweep_detected:
                    intelligence.mm_pattern = MarketMakerPattern.SWEEP
                    intelligence.mm_confidence = 0.8
                
                if large_order_side:
                    intelligence.large_order_detected = True
                    intelligence.large_order_side = large_order_side
        except Exception as e:
            logger.debug(f"[HEDGE_INTEL] Order flow gather failed: {e}")
    
    def _detect_market_maker_patterns(self, symbol: str, intelligence: MarketIntelligence):
        """Detect market maker manipulation patterns."""
        try:
            # Check for stop hunt pattern
            # Stop hunt: price spikes to trigger stops then immediately reverses
            price_history = self._price_history.get(symbol, deque())
            if len(price_history) >= 30:
                prices = [p[1] for p in price_history]
                recent_high = max(prices[-30:])
                recent_low = min(prices[-30:])
                current = prices[-1] if prices else 0
                
                # Detect spike and reversal
                if len(prices) >= 60:
                    older_prices = prices[-60:-30]
                    old_range = max(older_prices) - min(older_prices) if older_prices else 0
                    new_range = recent_high - recent_low
                    
                    # Sudden range expansion followed by return to mean
                    if new_range > old_range * 2:
                        mid_point = (max(older_prices) + min(older_prices)) / 2
                        if abs(current - mid_point) < old_range * 0.5:
                            intelligence.mm_pattern = MarketMakerPattern.STOP_HUNT
                            intelligence.mm_confidence = 0.7
                            
                            # Determine which side was hunted
                            if recent_high > max(older_prices):
                                intelligence.mm_adverse_for = "SHORT"  # Shorts got stopped
                            else:
                                intelligence.mm_adverse_for = "LONG"  # Longs got stopped
        except Exception as e:
            logger.debug(f"[HEDGE_INTEL] MM pattern detection failed: {e}")
    
    def _detect_fast_moves(self, symbol: str, intelligence: MarketIntelligence):
        """Detect rapid price movements."""
        try:
            price_history = self._price_history.get(symbol, deque())
            if len(price_history) < 10:
                return
            
            # Check last 30 seconds
            now = time.time()
            recent_prices = [(t, p) for t, p in price_history if now - t < 30]
            
            if len(recent_prices) >= 5:
                first_price = recent_prices[0][1]
                last_price = recent_prices[-1][1]
                time_span = recent_prices[-1][0] - recent_prices[0][0]
                
                if first_price > 0 and time_span > 0:
                    move_pct = (last_price - first_price) / first_price * 100
                    
                    if abs(move_pct) >= self.fast_move_threshold:
                        intelligence.fast_move_detected = True
                        intelligence.fast_move_direction = "UP" if move_pct > 0 else "DOWN"
                        intelligence.fast_move_magnitude_pct = abs(move_pct)
                        intelligence.fast_move_duration_sec = time_span
                        
                        # Calculate acceleration
                        if len(recent_prices) >= 10:
                            mid_idx = len(recent_prices) // 2
                            first_half_move = (recent_prices[mid_idx][1] - recent_prices[0][1]) / max(0.001, recent_prices[0][1])
                            second_half_move = (recent_prices[-1][1] - recent_prices[mid_idx][1]) / max(0.001, recent_prices[mid_idx][1])
                            intelligence.price_acceleration = second_half_move - first_half_move
        except Exception as e:
            logger.debug(f"[HEDGE_INTEL] Fast move detection failed: {e}")
    
    # =========================================================================
    # DECISION EVALUATION METHODS
    # =========================================================================
    
    def _evaluate_roe_with_hysteresis(
        self, symbol: str, roe_pct: float, position_side: str
    ) -> Tuple[bool, str]:
        """Evaluate ROE trigger with hysteresis to prevent churn."""
        with self._state_lock:
            state = self._hedge_states.get(symbol)
        
        # Base trigger threshold (e.g., -20%)
        base_trigger = -15.0
        
        # If we recently had a hedge that was closed, add hysteresis
        if state and state.oscillation_count > 0:
            # Each oscillation raises the trigger threshold
            hysteresis_penalty = state.oscillation_count * self.hysteresis_band_pct
            adjusted_trigger = base_trigger - hysteresis_penalty
            
            if roe_pct > adjusted_trigger:
                return False, f"hysteresis_band:threshold={adjusted_trigger:.1f}%"
        
        if roe_pct <= base_trigger:
            return True, f"roe_trigger:{roe_pct:.1f}%"
        
        return False, "roe_ok"
    
    def _evaluate_market_maker_threat(
        self, intelligence: MarketIntelligence, position_side: str
    ) -> Tuple[bool, str]:
        """Evaluate if MM activity threatens our position."""
        if intelligence.mm_pattern == MarketMakerPattern.NONE:
            return False, "no_mm_pattern"
        
        # Check if the pattern is adverse for our position side
        if intelligence.mm_adverse_for == position_side:
            return True, f"{intelligence.mm_pattern.value}_against_{position_side}"
        
        # Spoofing is always concerning
        if intelligence.mm_pattern == MarketMakerPattern.SPOOFING:
            if intelligence.mm_confidence >= 0.7:
                return True, f"high_confidence_spoofing:{intelligence.mm_confidence:.2f}"
        
        # Sweep in opposite direction
        if intelligence.mm_pattern == MarketMakerPattern.SWEEP:
            # If sweep is buying and we're short, or vice versa
            if intelligence.large_order_side:
                adverse = (
                    (intelligence.large_order_side == "BUY" and position_side == "SHORT") or
                    (intelligence.large_order_side == "SELL" and position_side == "LONG")
                )
                if adverse:
                    return True, f"sweep_against_position"
        
        return False, "mm_not_threatening"
    
    def _evaluate_fast_move_threat(
        self, intelligence: MarketIntelligence, position_side: str
    ) -> Tuple[bool, str]:
        """Evaluate if fast move threatens our position."""
        if not intelligence.fast_move_detected:
            return False, "no_fast_move"
        
        # Fast move against our position
        adverse = (
            (intelligence.fast_move_direction == "DOWN" and position_side == "LONG") or
            (intelligence.fast_move_direction == "UP" and position_side == "SHORT")
        )
        
        if adverse:
            return True, f"fast_{intelligence.fast_move_direction}_{intelligence.fast_move_magnitude_pct:.1f}%"
        
        # Even if not adverse, acceleration matters
        if abs(intelligence.price_acceleration) > 0.01:
            # Accelerating move is more threatening
            return True, f"accelerating_move:{intelligence.price_acceleration:.3f}"
        
        return False, "fast_move_not_threatening"
    
    def _evaluate_order_flow(
        self, intelligence: MarketIntelligence, position_side: str
    ) -> Tuple[bool, str]:
        """Evaluate order flow signals."""
        imbalance = intelligence.order_flow_imbalance
        
        # Strong imbalance against our position
        if position_side == "LONG" and imbalance < -0.5:
            return True, f"selling_pressure:{imbalance:.2f}"
        elif position_side == "SHORT" and imbalance > 0.5:
            return True, f"buying_pressure:{imbalance:.2f}"
        
        # Large order detected against us
        if intelligence.large_order_detected:
            adverse = (
                (intelligence.large_order_side == "SELL" and position_side == "LONG") or
                (intelligence.large_order_side == "BUY" and position_side == "SHORT")
            )
            if adverse:
                return True, f"large_{intelligence.large_order_side}_order"
        
        return False, "flow_neutral"
    
    def _evaluate_coinapi_microstructure(
        self, intelligence: MarketIntelligence, position_side: str
    ) -> Tuple[bool, str]:
        """Evaluate CoinAPI microstructure signals."""
        # Wide spread indicates low liquidity / potential for adverse moves
        if intelligence.coinapi_spread_pct > 0.3:
            return True, f"wide_spread:{intelligence.coinapi_spread_pct:.2f}%"
        
        # Depth imbalance against our position
        if position_side == "LONG" and intelligence.coinapi_depth_ratio < 0.5:
            return True, f"thin_bid_depth:{intelligence.coinapi_depth_ratio:.2f}"
        elif position_side == "SHORT" and intelligence.coinapi_depth_ratio > 2.0:
            return True, f"thin_ask_depth:{intelligence.coinapi_depth_ratio:.2f}"
        
        # Low microstructure score
        if intelligence.micro_score < 0.3:
            return True, f"poor_microstructure:{intelligence.micro_score:.2f}"
        
        return False, "micro_ok"
    
    def _generate_counter_algo_signal(
        self, symbol: str, position_side: str, intelligence: MarketIntelligence
    ) -> Optional[str]:
        """
        Generate proactive counter-algo signal.
        
        Instead of being a victim of market maker games, anticipate and counter them.
        """
        signals = []
        
        # 1. If we detect stop hunt setup, hedge BEFORE they execute
        if intelligence.mm_pattern == MarketMakerPattern.SPOOFING:
            # Spoofing usually precedes a move - hedge proactively
            signals.append("pre_spoof_defense")
        
        # 2. If depth is thin on our side, MM might push through
        if position_side == "LONG" and intelligence.coinapi_depth_ratio < 0.7:
            signals.append("thin_bid_preempt")
        elif position_side == "SHORT" and intelligence.coinapi_depth_ratio > 1.4:
            signals.append("thin_ask_preempt")
        
        # 3. If trade intensity suddenly drops, MM might be pulling liquidity
        if intelligence.coinapi_trade_intensity < 0.5:  # Very low activity
            if intelligence.coinapi_spread_pct > 0.2:
                signals.append("liquidity_vacuum")
        
        # 4. Acceleration pattern - move is picking up speed
        if intelligence.price_acceleration < -0.005 and position_side == "LONG":
            signals.append("sell_acceleration")
        elif intelligence.price_acceleration > 0.005 and position_side == "SHORT":
            signals.append("buy_acceleration")
        
        if signals:
            return "|".join(signals)
        return None
    
    # =========================================================================
    # EXIT VALIDATION HELPERS
    # =========================================================================
    
    def _is_mm_pattern_adverse_for_exit(
        self, intelligence: MarketIntelligence, position_side: str
    ) -> bool:
        """Check if current MM pattern makes exit unfavorable."""
        if intelligence.mm_pattern == MarketMakerPattern.NONE:
            return False
        
        # Fade reversal - MM might push price back
        if intelligence.mm_pattern == MarketMakerPattern.FADE_REVERSAL:
            return True
        
        # Stop hunt in progress - don't exit into it
        if intelligence.mm_pattern == MarketMakerPattern.STOP_HUNT:
            return True
        
        return False
    
    def _is_momentum_against_exit(
        self, intelligence: MarketIntelligence, position_side: str
    ) -> bool:
        """Check if momentum makes exit unfavorable."""
        # Strong momentum against our position means hedge is protecting us
        if position_side == "LONG":
            if intelligence.price_velocity_1m < -0.3:  # Price falling fast
                return True
            if intelligence.order_flow_imbalance < -0.4:  # Selling pressure
                return True
        else:
            if intelligence.price_velocity_1m > 0.3:  # Price rising fast
                return True
            if intelligence.order_flow_imbalance > 0.4:  # Buying pressure
                return True
        
        return False
    
    def _is_trend_against_exit(self, symbol: str, position_side: str) -> bool:
        """Check if trend is still adverse (hedge should stay)."""
        try:
            if not self.redis:
                return False
            
            # Check technical indicators
            for tf in ['5m', '15m', '1h']:
                key = f"unified_features:{symbol}:{tf}"
                data = self.redis.hgetall(key)
                if data:
                    ema_cross = float(data.get('ema_cross_signal', 0) or 0)
                    adx = float(data.get('adx', 0) or 0)
                    rsi = float(data.get('rsi', 50) or 50)
                    
                    # Strong trend against position
                    if position_side == "LONG":
                        if ema_cross < -0.5 and adx > 25:  # Bearish trend
                            return True
                        if rsi < 30 and adx > 20:  # Oversold but trending down
                            return True
                    else:
                        if ema_cross > 0.5 and adx > 25:  # Bullish trend
                            return True
                        if rsi > 70 and adx > 20:  # Overbought but trending up
                            return True
                    break
        except Exception as e:
            logger.debug(f"[HEDGE_INTEL] Trend check failed: {e}")
        
        return False
    
    # =========================================================================
    # STATE MANAGEMENT
    # =========================================================================
    
    def _create_hedge_state(
        self,
        symbol: str,
        position_side: str,
        roe_pct: float,
        entry_price: float,
        risk_score: float,
        reasons: List[str],
        intelligence: MarketIntelligence
    ):
        """Create a new hedge intelligence state."""
        now = time.time()
        hedge_side = "SHORT" if position_side == "LONG" else "LONG"
        
        state = HedgeIntelligenceState(
            symbol=symbol,
            position_side=position_side,
            hedge_side=hedge_side,
            created_at=now,
            state=HedgeState.PENDING,
            entry_roe_pct=roe_pct,
            entry_price=entry_price,
            entry_risk_score=risk_score,
            entry_reasons=reasons,
            profit_target_pct=self.profit_target_pct,
            entry_spread_pct=intelligence.coinapi_spread_pct,
            entry_depth_ratio=intelligence.coinapi_depth_ratio,
            entry_volatility=intelligence.price_velocity_1m
        )
        
        with self._state_lock:
            # Check for oscillation (recent hedge on same symbol)
            existing = self._hedge_states.get(symbol)
            if existing and (now - existing.created_at) < 600:  # Within 10 min
                state.oscillation_count = existing.oscillation_count + 1
                state.last_oscillation_at = now
                logger.warning(
                    f"⚠️ [HEDGE_INTEL] {symbol} oscillation detected: count={state.oscillation_count}"
                )
            
            self._hedge_states[symbol] = state
    
    def _clear_hedge_state(self, symbol: str):
        """Clear hedge state after exit."""
        with self._state_lock:
            if symbol in self._hedge_states:
                state = self._hedge_states[symbol]
                state.state = HedgeState.NONE
                # Don't delete - keep for oscillation tracking
    
    def _record_exit_denial(self, symbol: str, reason: str):
        """Record an exit denial for debugging."""
        with self._state_lock:
            state = self._hedge_states.get(symbol)
            if state:
                state.exit_denials.append((time.time(), reason))
                # Keep only last 10 denials
                state.exit_denials = state.exit_denials[-10:]
    
    def record_price(self, symbol: str, price: float):
        """Record price for analysis (call frequently)."""
        self._price_history[symbol].append((time.time(), price))
    
    # =========================================================================
    # STATUS AND DEBUGGING
    # =========================================================================
    
    def get_hedge_state(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current hedge intelligence state for a symbol."""
        with self._state_lock:
            state = self._hedge_states.get(symbol)
            if not state:
                return None
            
            return {
                'symbol': state.symbol,
                'position_side': state.position_side,
                'hedge_side': state.hedge_side,
                'state': state.state.value,
                'created_at': state.created_at,
                'commitment_expires_at': state.commitment_expires_at,
                'entry_roe_pct': state.entry_roe_pct,
                'entry_reasons': state.entry_reasons,
                'oscillation_count': state.oscillation_count,
                'exit_denials': state.exit_denials[-5:]
            }


# =============================================================================
# SINGLETON ACCESSOR
# =============================================================================

_hedge_intelligence_engine: Optional[HedgeIntelligenceEngine] = None
_engine_lock = threading.Lock()


def get_hedge_intelligence_engine(redis_client=None) -> HedgeIntelligenceEngine:
    """Get or create the singleton HedgeIntelligenceEngine instance."""
    global _hedge_intelligence_engine
    
    with _engine_lock:
        if _hedge_intelligence_engine is None:
            _hedge_intelligence_engine = HedgeIntelligenceEngine(redis_client=redis_client)
        return _hedge_intelligence_engine

