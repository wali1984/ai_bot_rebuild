"""
ADDITIONAL CRITICAL FIXES: Signal Spam, Premature Profit Taking, Market Maker Gaming
=======================================================================================

These fixes address 3 additional issues causing the 50% portfolio loss:

1. DYNAMIC PROFIT TAKING - Closes winners too early, ignoring trend confidence
2. MULTIPLE TF SIGNAL SPAM - Same coin gets signals from multiple TFs causing stacking
3. LIQUIDATION ALGOS - False signals from liquidation/microstructure detection

Author: AI Assistant
Date: 2025-12-22
Status: PRODUCTION CRITICAL - Additional Death Spiral Prevention
"""

import logging
from typing import Dict, Any, Optional, List, Tuple, Set
from collections import defaultdict, deque
import time
import numpy as np

logger = logging.getLogger(__name__)


class MultiTimeframeSignalCoordinator:
    """
    CRITICAL FIX #1: Prevents multiple TF signals for same coin causing position stacking.
    
    Problem: Trainer generates signal from 1m, 5m, 15m all saying LONG BTCUSDT.
             Trader executes all 3 → 3x position → market makers detect → reverse.
    
    Solution: Only allow ONE action per symbol per time window across ALL timeframes.
              Higher timeframes take priority. Conflicting signals are resolved.
    """
    
    def __init__(self):
        # Track last action per symbol (regardless of TF)
        self.last_action_per_symbol = {}  # symbol -> {action, confidence, timestamp, timeframe}
        
        # Timeframe priority (higher TF = higher priority)
        self.tf_priority = {
            '4h': 5,
            '1h': 4,
            '15m': 3,
            '5m': 2,
            '1m': 1
        }
        
        # Signal aggregation window (seconds)
        self.aggregation_window = 60  # 1 minute to collect all TF signals
        
        # Pending signals waiting for aggregation
        self.pending_signals = defaultdict(list)  # symbol -> [signal1, signal2, ...]
        
        # Last published signal per symbol (for deduplication)
        self.last_published = {}  # symbol -> {action, timestamp}
        
        # Minimum time between same actions on same symbol
        self.action_cooldown = {
            'LONG': 300,      # 5 minutes between LONG signals
            'SHORT': 300,     # 5 minutes between SHORT signals
            'CLOSE': 120,     # 2 minutes between CLOSE signals
            'HEDGE': 600,     # 10 minutes between HEDGE actions
        }
        
        logger.info("🎯 Multi-timeframe signal coordinator initialized")
    
    def should_publish_signal(self, symbol: str, action: str, timeframe: str, 
                             confidence: float, position_info: Dict = None) -> Tuple[bool, str]:
        """
        Determine if signal should be published or suppressed.
        
        Args:
            symbol: Trading symbol
            action: Action (LONG, SHORT, CLOSE_LONG, etc.)
            timeframe: Source timeframe
            confidence: Signal confidence
            position_info: Current position information
            
        Returns:
            (should_publish: bool, reason: str)
        """
        
        now = time.time()
        
        # Extract base action (LONG, SHORT, CLOSE, HEDGE)
        base_action = self._get_base_action(action)
        
        # Check 1: Cooldown period for same action
        if symbol in self.last_published:
            last = self.last_published[symbol]
            if last['action'] == base_action:
                time_since = now - last['timestamp']
                required_cooldown = self.action_cooldown.get(base_action, 300)
                
                if time_since < required_cooldown:
                    remaining = required_cooldown - time_since
                    return (False, f"🔒 Cooldown active: {remaining:.0f}s remaining for {base_action} on {symbol}")
        
        # Check 2: Conflicting signals from different timeframes
        recent_signals = self._get_recent_signals(symbol, window=60)  # Last 60 seconds
        
        if recent_signals:
            # Check for conflicting directions
            conflicts = self._detect_conflicts(recent_signals, action)
            if conflicts:
                return (False, f"⚠️ Conflicting signals from multiple TFs: {conflicts}")
            
            # Check if we already have same action from higher TF
            for sig in recent_signals:
                if sig['action'] == action:
                    sig_priority = self.tf_priority.get(sig['timeframe'], 0)
                    current_priority = self.tf_priority.get(timeframe, 0)
                    
                    if sig_priority > current_priority:
                        return (False, f"⬆️ Higher TF ({sig['timeframe']}) already published {action}")
                    elif sig_priority == current_priority and sig['confidence'] > confidence:
                        return (False, f"⚡ Same TF with higher confidence already published")
        
        # Check 3: Position stacking prevention
        if position_info:
            current_positions = position_info.get('count', 0)
            if current_positions > 0 and base_action in ['LONG', 'SHORT']:
                # Already have position on this symbol
                if self._would_stack_position(symbol, action, position_info):
                    return (False, f"🚫 Would stack position (already {current_positions} positions)")
        
        # Check 4: Market maker gaming detection
        if self._detect_market_maker_gaming(symbol, action):
            return (False, f"🎯 Market maker gaming pattern detected - blocking signal")
        
        # All checks passed - signal is valid
        self.last_published[symbol] = {
            'action': base_action,
            'timestamp': now,
            'timeframe': timeframe,
            'confidence': confidence
        }
        
        return (True, f"✅ Signal approved: {action} from {timeframe} @ {confidence:.2f}")
    
    def _get_base_action(self, action: str) -> str:
        """Extract base action from compound actions"""
        if 'LONG' in action:
            return 'LONG'
        elif 'SHORT' in action:
            return 'SHORT'
        elif 'CLOSE' in action:
            return 'CLOSE'
        elif 'HEDGE' in action:
            return 'HEDGE'
        return action
    
    def _get_recent_signals(self, symbol: str, window: int = 60) -> List[Dict]:
        """Get signals published for symbol in last N seconds"""
        if symbol not in self.last_action_per_symbol:
            return []
        
        now = time.time()
        signals = []
        
        # Check pending signals
        if symbol in self.pending_signals:
            for sig in self.pending_signals[symbol]:
                if now - sig['timestamp'] < window:
                    signals.append(sig)
        
        return signals
    
    def _detect_conflicts(self, recent_signals: List[Dict], new_action: str) -> Optional[str]:
        """Detect if new action conflicts with recent signals"""
        new_base = self._get_base_action(new_action)
        
        for sig in recent_signals:
            sig_base = self._get_base_action(sig['action'])
            
            # LONG vs SHORT conflict
            if (new_base == 'LONG' and sig_base == 'SHORT') or \
               (new_base == 'SHORT' and sig_base == 'LONG'):
                return f"{sig_base} from {sig['timeframe']} conflicts with {new_base}"
        
        return None
    
    def _would_stack_position(self, symbol: str, action: str, position_info: Dict) -> bool:
        """Check if action would stack positions unnecessarily"""
        current_side = position_info.get('side', None)
        action_side = 'LONG' if 'LONG' in action else 'SHORT' if 'SHORT' in action else None
        
        # Would add to existing position of same side
        return current_side == action_side
    
    def _detect_market_maker_gaming(self, symbol: str, action: str) -> bool:
        """
        Detect if we're being gamed by market makers.
        Pattern: Rapid position changes (flip-flop) indicating MM manipulation.
        """
        if symbol not in self.last_action_per_symbol:
            return False
        
        history = self.last_action_per_symbol.get(symbol, {})
        if not history:
            return False
        
        # Check for rapid reversals (flip-flop pattern)
        last_action = history.get('action')
        last_time = history.get('timestamp', 0)
        
        now = time.time()
        time_since = now - last_time
        
        # If we're reversing position within 5 minutes, likely being gamed
        if time_since < 300:  # 5 minutes
            new_base = self._get_base_action(action)
            if (last_action == 'LONG' and new_base == 'SHORT') or \
               (last_action == 'SHORT' and new_base == 'LONG'):
                logger.warning(f"⚠️ [{symbol}] Market maker gaming detected: {last_action} → {new_base} in {time_since:.0f}s")
                return True
        
        return False


class SmartProfitTaking:
    """
    CRITICAL FIX #2: Prevents premature profit taking that kills winning trades.
    
    Problem: Dynamic profit taking closes winners too early, even when trend is strong
             and lower TF has high confidence continuation signal.
    
    Solution: Consider trend strength, confidence, and timeframe alignment before
              taking profit. Let winners run when conditions favor continuation.
    """
    
    def __init__(self):
        # Profit taking thresholds based on trend strength
        self.min_profit_for_partial = 2.0  # % - minimum profit to consider partial close
        self.min_profit_for_full = 5.0     # % - minimum profit for full close
        
        # Trend confidence requirements
        self.min_trend_confidence = 0.85    # Require 85% confidence for trend continuation
        self.allow_profit_take_below = 0.70 # Below 70% confidence, allow profit taking
        
        # Timeframe alignment (all TFs agree) gives stronger signal
        self.tf_alignment_bonus = 0.10      # +10% confidence if all TFs align
        
        logger.info("💰 Smart profit taking module initialized")
    
    def should_take_profit(self, symbol: str, position_info: Dict,
                          current_signals: Dict[str, Dict]) -> Tuple[bool, float, str]:
        """
        Determine if profit should be taken and how much.
        
        Args:
            symbol: Trading symbol
            position_info: Current position (side, entry, PNL%, etc.)
            current_signals: Signals from all timeframes {tf: {action, confidence}}
            
        Returns:
            (should_take: bool, take_percentage: float, reason: str)
        """
        
        current_pnl_pct = position_info.get('pnl_pct', 0)
        current_side = position_info.get('side')  # LONG or SHORT
        
        # Not in profit - don't take profit
        if current_pnl_pct <= 0:
            return (False, 0.0, "Not in profit")
        
        # Check 1: Minimum profit threshold
        if current_pnl_pct < self.min_profit_for_partial:
            return (False, 0.0, f"Profit too small ({current_pnl_pct:.1f}% < {self.min_profit_for_partial}%)")
        
        # Check 2: Trend analysis from signals
        trend_analysis = self._analyze_trend(current_signals, current_side)
        
        # Strong trend continuation - let it run
        if trend_analysis['is_strong_continuation']:
            return (False, 0.0, 
                   f"🚀 Strong trend continuation: {trend_analysis['avg_confidence']:.2f} confidence, "
                   f"{trend_analysis['aligned_tfs']}/{trend_analysis['total_tfs']} TFs aligned")
        
        # Weak trend or reversal - take profit
        if trend_analysis['is_reversal_likely']:
            # Determine how much to take
            if current_pnl_pct >= self.min_profit_for_full:
                take_pct = 100.0  # Full exit
                reason = f"📊 Full profit take: {current_pnl_pct:.1f}% profit, reversal likely"
            else:
                take_pct = 50.0   # Partial exit
                reason = f"📊 Partial profit take (50%): {current_pnl_pct:.1f}% profit, trend weakening"
            
            return (True, take_pct, reason)
        
        # Neutral/uncertain - scale with profit level
        if current_pnl_pct >= self.min_profit_for_full:
            # Large profit, neutral trend - take partial
            take_pct = 30.0  # Take 30% off, let rest run
            return (True, take_pct, 
                   f"💰 Profit lock (30%): {current_pnl_pct:.1f}% profit, trend neutral")
        
        # Small profit, neutral trend - hold
        return (False, 0.0, 
               f"⏳ Hold: {current_pnl_pct:.1f}% profit, waiting for stronger signal")
    
    def _analyze_trend(self, signals: Dict[str, Dict], current_side: str) -> Dict:
        """
        Analyze trend strength and direction from multi-TF signals.
        
        Returns:
            {
                'is_strong_continuation': bool,
                'is_reversal_likely': bool,
                'avg_confidence': float,
                'aligned_tfs': int,
                'total_tfs': int
            }
        """
        if not signals:
            return {
                'is_strong_continuation': False,
                'is_reversal_likely': False,
                'avg_confidence': 0.0,
                'aligned_tfs': 0,
                'total_tfs': 0
            }
        
        # Count TFs that agree with current position
        aligned_tfs = 0
        opposing_tfs = 0
        total_confidence = 0.0
        total_tfs = len(signals)
        
        for tf, signal in signals.items():
            action = signal.get('action', '')
            confidence = signal.get('confidence', 0.0)
            
            # Check if signal aligns with current position
            if (current_side == 'LONG' and 'LONG' in action) or \
               (current_side == 'SHORT' and 'SHORT' in action):
                aligned_tfs += 1
                total_confidence += confidence
            elif (current_side == 'LONG' and 'SHORT' in action) or \
                 (current_side == 'SHORT' and 'LONG' in action):
                opposing_tfs += 1
        
        avg_confidence = total_confidence / total_tfs if total_tfs > 0 else 0.0
        
        # Strong continuation: >70% TFs aligned with high confidence
        is_strong_continuation = (
            aligned_tfs >= 0.7 * total_tfs and 
            avg_confidence >= self.min_trend_confidence
        )
        
        # Reversal likely: >50% TFs opposing
        is_reversal_likely = opposing_tfs >= 0.5 * total_tfs
        
        return {
            'is_strong_continuation': is_strong_continuation,
            'is_reversal_likely': is_reversal_likely,
            'avg_confidence': avg_confidence,
            'aligned_tfs': aligned_tfs,
            'total_tfs': total_tfs
        }


class LiquidationAlgoController:
    """
    CRITICAL FIX #3: Controls liquidation/microstructure algos that cause false signals.
    
    Problem: Liquidation level detection and microstructure scripts generate false signals
             that compound with other issues, creating more losing trades.
    
    Solution: Add confidence filters, validation, and emergency disable capability.
    """
    
    def __init__(self):
        # Track liquidation algo performance
        self.liq_signal_performance = deque(maxlen=100)  # Last 100 signals
        
        # Emergency disable threshold
        self.min_win_rate = 0.40  # If win rate < 40%, disable
        self.min_samples = 20     # Need 20 samples before evaluating
        
        # Confidence boost/penalty based on performance
        self.confidence_adjustment = 0.0  # Start neutral
        
        # Status
        self.is_enabled = True
        self.disable_reason = None
        
        logger.info("🔍 Liquidation algo controller initialized")
    
    def should_use_liq_signal(self, symbol: str, liq_signal: Dict) -> Tuple[bool, str]:
        """
        Validate if liquidation signal should be used.
        
        Args:
            symbol: Trading symbol
            liq_signal: Liquidation/microstructure signal
            
        Returns:
            (should_use: bool, reason: str)
        """
        
        # Check 1: Is algo enabled?
        if not self.is_enabled:
            return (False, f"🚫 Liquidation algo DISABLED: {self.disable_reason}")
        
        # Check 2: Signal confidence
        confidence = liq_signal.get('confidence', 0.0)
        adjusted_confidence = confidence + self.confidence_adjustment
        
        # LOWERED (Dec 30, 2025): Liquidation detection signals are valuable even at lower confidence
        # Original 0.75 was blocking ALL signals - detection != trading confidence
        if adjusted_confidence < 0.45:  # Require 45% minimum (was 75%)
            return (False, f"⚠️ Liq signal confidence too low: {adjusted_confidence:.2f} < 0.45")
        
        # Check 3: Signal freshness
        signal_age = time.time() - liq_signal.get('timestamp', 0)
        if signal_age > 300:  # 5 minutes old
            return (False, f"⏰ Liq signal too old: {signal_age:.0f}s")
        
        # Check 4: Conflicting timeframes
        source_tf = liq_signal.get('timeframe', '')
        if source_tf == '1m':
            # 1m liquidation signals are too noisy
            return (False, "📉 1m liquidation signals disabled (too noisy)")
        
        # Signal is valid
        return (True, f"✅ Liq signal approved: {confidence:.2f} confidence from {source_tf}")
    
    def record_liq_signal_result(self, signal_id: str, was_profitable: bool, pnl_pct: float):
        """Record outcome of liquidation signal for performance tracking"""
        self.liq_signal_performance.append({
            'signal_id': signal_id,
            'profitable': was_profitable,
            'pnl_pct': pnl_pct,
            'timestamp': time.time()
        })
        
        # Update performance metrics
        self._update_performance_metrics()
    
    def _update_performance_metrics(self):
        """Update performance and adjust confidence or disable if needed"""
        if len(self.liq_signal_performance) < self.min_samples:
            return
        
        # Calculate win rate
        wins = sum(1 for sig in self.liq_signal_performance if sig['profitable'])
        win_rate = wins / len(self.liq_signal_performance)
        
        # Calculate average PNL
        avg_pnl = np.mean([sig['pnl_pct'] for sig in self.liq_signal_performance])
        
        logger.info(f"📊 Liquidation algo performance: {win_rate:.1%} win rate, {avg_pnl:.2f}% avg PNL")
        
        # Emergency disable if performing poorly
        if win_rate < self.min_win_rate:
            self.is_enabled = False
            self.disable_reason = f"Poor performance: {win_rate:.1%} win rate < {self.min_win_rate:.1%}"
            logger.error(f"🚨 LIQUIDATION ALGO DISABLED: {self.disable_reason}")
            return
        
        # Adjust confidence based on performance
        if win_rate >= 0.60:
            self.confidence_adjustment = 0.05  # Boost confidence
        elif win_rate >= 0.50:
            self.confidence_adjustment = 0.0   # Neutral
        else:
            self.confidence_adjustment = -0.10  # Penalize confidence
        
        logger.info(f"🎯 Liquidation confidence adjustment: {self.confidence_adjustment:+.2f}")


# Integration instructions
INTEGRATION_INSTRUCTIONS = """
=============================================================================
ADDITIONAL FIXES - INTEGRATION INSTRUCTIONS
=============================================================================

These fixes should be integrated ALONGSIDE the hedge fix in:
rl/CRITICAL_HEDGE_AND_PORTFOLIO_FIX.py

ADD TO hybrid_trainer.py:

1. IMPORT (top of file):
   from rl.ADDITIONAL_CRITICAL_FIXES import (
       MultiTimeframeSignalCoordinator,
       SmartProfitTaking,
       LiquidationAlgoController
   )

2. IN __init__ (after portfolio tracker init):
   
   # Initialize signal coordinator
   self.signal_coordinator = MultiTimeframeSignalCoordinator()
   logger.info("🎯 Multi-TF signal coordinator initialized")
   
   # Initialize smart profit taking
   self.smart_profit_taking = SmartProfitTaking()
   logger.info("💰 Smart profit taking initialized")
   
   # Initialize liquidation algo controller
   self.liq_controller = LiquidationAlgoController()
   logger.info("🔍 Liquidation algo controller initialized")

3. BEFORE PUBLISHING ANY SIGNAL (in signal generation loop):
   
   # Check with coordinator first
   should_publish, reason = self.signal_coordinator.should_publish_signal(
       symbol=symbol,
       action=action_name,
       timeframe=timeframe,
       confidence=confidence,
       position_info=current_position_info
   )
   
   if not should_publish:
       logger.info(f"🚫 [{symbol}] {reason}")
       continue  # Skip this signal
   
   logger.info(f"✅ [{symbol}] {reason}")

4. BEFORE DYNAMIC PROFIT TAKING (in profit take logic):
   
   # Get current signals from all TFs for this symbol
   current_signals = self._get_current_signals(symbol)  # Dict[tf] -> {action, confidence}
   
   # Check with smart profit taking
   should_take, take_pct, reason = self.smart_profit_taking.should_take_profit(
       symbol=symbol,
       position_info=position_info,
       current_signals=current_signals
   )
   
   if not should_take:
       logger.info(f"💎 [{symbol}] Holding: {reason}")
       continue
   
   logger.info(f"💰 [{symbol}] {reason} - Taking {take_pct:.0f}%")
   # Proceed with profit taking at take_pct percentage

5. BEFORE USING LIQUIDATION SIGNALS:
   
   # Validate liquidation signal
   should_use, reason = self.liq_controller.should_use_liq_signal(
       symbol=symbol,
       liq_signal=liq_signal_data
   )
   
   if not should_use:
       logger.debug(f"🚫 [{symbol}] {reason}")
       continue  # Ignore this liquidation signal
   
   logger.info(f"✅ [{symbol}] {reason}")

=============================================================================
TRADER SIDE FIXES (trader.py and trader-asjad.py):
=============================================================================

The traders are blindly executing ALL signals from Redis. Add validation:

IN execute_signal() method (around line 800):

def execute_signal(self, signal: Dict) -> bool:
    \"\"\"Execute trading signal with validation\"\"\"
    
    symbol = signal['symbol']
    action = signal['action']
    
    # NEW: Check if we already have this exact position
    current_positions = self._get_current_positions(symbol)
    
    # Prevent stacking same-side positions
    if action in ['LONG', 'SHORT']:
        for pos in current_positions:
            if pos['side'] == action:
                logger.info(f"🚫 [{symbol}] Already have {action} position, skipping signal")
                return False  # Don't execute duplicate
    
    # Prevent rapid flip-flopping
    last_action_time = self._last_actions.get(symbol, 0)
    if time.time() - last_action_time < 120:  # 2 minute minimum
        logger.info(f"🔒 [{symbol}] Action cooldown active, skipping")
        return False
    
    # Proceed with execution...
    self._last_actions[symbol] = time.time()
    ...

=============================================================================
"""

if __name__ == "__main__":
    print(INTEGRATION_INSTRUCTIONS)
    print("\n✅ Additional critical fixes module loaded")

