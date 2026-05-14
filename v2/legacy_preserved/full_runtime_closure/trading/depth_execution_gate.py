"""
DEPTH EXECUTION GATE (V2)
=========================
CoinAPI Depth-based execution gate for trade timing optimization.

Uses real-time orderbook depth data to make PASS/DELAY/SIZE_REDUCE decisions
before sending orders to exchange. This is the final filter before execution.

Key Signals:
1. Spoof detection - Delay if large fake orders detected
2. Fast move - Delay entries during velocity spikes
3. Liquidity drought - Reduce size if orderbook thin
4. Imbalance divergence - Delay if flow against direction

Kill Switch: DEPTH_EXECUTION_GATE_ENABLED must be true to use this gate.
"""

import json
import logging
import time
import redis
from dataclasses import dataclass
from typing import Dict, Any, Optional, List

# Import config - fail gracefully if not available
try:
    from config import (
        REDIS_URL,
        DEPTH_EXECUTION_GATE_ENABLED,
        DEPTH_GATE_SPOOF_THRESHOLD,
        DEPTH_GATE_FAST_MOVE_THRESHOLD,
        DEPTH_GATE_MIN_QUALITY,
        DEPTH_GATE_IMBALANCE_THRESHOLD,
        DEPTH_GATE_STALENESS_MS,
        DEPTH_GATE_SIZE_REDUCE_FACTOR,
        DEPTH_GATE_DELAY_SECONDS,
        HEDGE_BYPASS_ALL_GATES,
    )
except ImportError:
    REDIS_URL = "redis://localhost:6379/0"
    DEPTH_EXECUTION_GATE_ENABLED = False
    DEPTH_GATE_SPOOF_THRESHOLD = 0.7
    DEPTH_GATE_FAST_MOVE_THRESHOLD = 0.8
    DEPTH_GATE_MIN_QUALITY = 0.5
    DEPTH_GATE_IMBALANCE_THRESHOLD = 0.6
    DEPTH_GATE_STALENESS_MS = 2000
    DEPTH_GATE_SIZE_REDUCE_FACTOR = 0.5
    DEPTH_GATE_DELAY_SECONDS = 5
    HEDGE_BYPASS_ALL_GATES = False

logger = logging.getLogger(__name__)


@dataclass
class GateDecision:
    """Result of execution gate check."""
    decision: str  # 'PASS', 'DELAY', 'SIZE_REDUCE'
    delay_seconds: int = 0
    size_multiplier: float = 1.0
    reasons: List[str] = None
    depth_snapshot: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []
        if self.depth_snapshot is None:
            self.depth_snapshot = {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'decision': self.decision,
            'delay_seconds': self.delay_seconds,
            'size_multiplier': self.size_multiplier,
            'reasons': self.reasons,
            'depth_snapshot': self.depth_snapshot,
        }


class DepthExecutionGate:
    """
    CoinAPI Depth-based execution gate for trade timing optimization.
    
    Uses real-time orderbook depth data to make PASS/DELAY/SIZE_REDUCE decisions
    before sending orders to exchange. This is the final filter before execution.
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """Initialize the execution gate."""
        if redis_client:
            self.redis = redis_client
        else:
            self.redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        
        # History for debugging/analysis
        self.gate_history: List[Dict] = []
        self.max_history = 100
        
        logger.info(f"[DepthExecutionGate] Initialized - ENABLED={DEPTH_EXECUTION_GATE_ENABLED}")
    
    def check_execution_gate(
        self,
        symbol: str,
        action: str,
        side: str,
        size_usd: float,
        is_hedge: bool = False
    ) -> GateDecision:
        """
        Check if trade should proceed, delay, or reduce size.
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            action: Action type ('OPEN', 'CLOSE', 'ADD', 'REDUCE', 'FLIP', 'TP')
            side: Order side ('BUY' or 'SELL')
            size_usd: Order size in USD
            is_hedge: Whether this is a hedge order (more lenient)
            
        Returns:
            GateDecision with decision, delay, size_multiplier, and reasons
        """
        # HEDGE BYPASS: do not apply timing/size gates to hedge orders when enabled.
        if is_hedge and bool(HEDGE_BYPASS_ALL_GATES):
            return GateDecision(
                decision='PASS',
                reasons=['HEDGE_BYPASS_ALL_GATES'],
            )

        # If gate is disabled, always PASS
        if not DEPTH_EXECUTION_GATE_ENABLED:
            return GateDecision(
                decision='PASS',
                reasons=['GATE_DISABLED'],
            )
        
        # Fetch CoinAPI depth data
        depth = self._fetch_depth_snapshot(symbol)
        
        if not depth:
            # No depth data = proceed with caution (reduced size)
            return GateDecision(
                decision='SIZE_REDUCE',
                size_multiplier=0.75,
                reasons=['NO_DEPTH_DATA'],
            )
        
        # Helper to safely convert to float
        def safe_float(val, default=0.0):
            try:
                return float(val) if val is not None else default
            except (ValueError, TypeError):
                return default
        
        # Check staleness
        staleness_ms = safe_float(depth.get('src_staleness_ms', 99999), 99999)
        if staleness_ms > DEPTH_GATE_STALENESS_MS:
            return GateDecision(
                decision='SIZE_REDUCE',
                size_multiplier=0.75,
                reasons=[f'STALE_DATA:{staleness_ms}ms'],
                depth_snapshot=depth,
            )
        
        reasons = []
        decision = 'PASS'
        delay_sec = 0
        size_mult = 1.0
        
        # Classify action type
        is_entry = action.upper() in ['OPEN', 'ADD', 'FLIP', 'INCREASE', 'OPEN_LONG', 'OPEN_SHORT', 'OPEN_HEDGE_LONG', 'OPEN_HEDGE_SHORT']
        is_exit = action.upper() in ['CLOSE', 'REDUCE', 'TP', 'SL', 'TAKE_PROFIT', 'STOP_LOSS', 'CLOSE_LONG', 'CLOSE_SHORT']
        
        # === GATE 1: SPOOF DETECTION ===
        spoof_score = safe_float(depth.get('spoof_score', 0))
        
        if spoof_score > DEPTH_GATE_SPOOF_THRESHOLD:
            # High spoof - significant delay
            decision = 'DELAY'
            delay_sec = max(delay_sec, DEPTH_GATE_DELAY_SECONDS * 3)  # 3x normal delay
            size_mult = min(size_mult, DEPTH_GATE_SIZE_REDUCE_FACTOR)
            reasons.append(f'HIGH_SPOOF:{spoof_score:.2f}')
        elif spoof_score > DEPTH_GATE_SPOOF_THRESHOLD * 0.6:
            # Moderate spoof - short delay + size reduce
            if decision == 'PASS':
                decision = 'DELAY'
            delay_sec = max(delay_sec, DEPTH_GATE_DELAY_SECONDS)
            size_mult = min(size_mult, 0.75)
            reasons.append(f'MOD_SPOOF:{spoof_score:.2f}')
        
        # === GATE 2: FAST MOVE (except for hedge exits) ===
        fast_move_score = safe_float(depth.get('fast_move_score', 0))
        fast_move_5m = safe_float(depth.get('fast_move_max_5m', 0))
        
        if fast_move_score > DEPTH_GATE_FAST_MOVE_THRESHOLD and is_entry and not is_hedge:
            # Very fast move - delay entries significantly
            decision = 'DELAY'
            delay_sec = max(delay_sec, DEPTH_GATE_DELAY_SECONDS * 4)
            size_mult = min(size_mult, DEPTH_GATE_SIZE_REDUCE_FACTOR)
            reasons.append(f'FAST_MOVE:{fast_move_score:.2f}')
        elif fast_move_score > DEPTH_GATE_FAST_MOVE_THRESHOLD * 0.6 and is_entry:
            # Moderate fast move - short delay
            if decision == 'PASS':
                decision = 'DELAY'
            delay_sec = max(delay_sec, DEPTH_GATE_DELAY_SECONDS)
            reasons.append(f'MOD_FAST_MOVE:{fast_move_score:.2f}')
        elif fast_move_score > 0.5 and is_exit:
            # Fast move during exit = ACCELERATE (don't delay profitable exits)
            reasons.append(f'FAST_EXIT_BOOST:{fast_move_score:.2f}')
            # Exits proceed without delay - this is intentional
        
        # === GATE 3: IMBALANCE DIVERGENCE ===
        imbalance = safe_float(depth.get('imbalance_5', 0.5), 0.5)  # 0-1 scale, 0.5 = neutral
        
        # Check if flow supports our direction
        side_upper = side.upper()
        if side_upper == 'BUY' and imbalance < (0.5 - DEPTH_GATE_IMBALANCE_THRESHOLD / 2):
            # Buying into seller-dominated book
            if decision == 'PASS':
                decision = 'SIZE_REDUCE'
            size_mult = min(size_mult, 0.7)
            reasons.append(f'ADVERSE_IMBALANCE_BUY:{imbalance:.2f}')
        elif side_upper == 'SELL' and imbalance > (0.5 + DEPTH_GATE_IMBALANCE_THRESHOLD / 2):
            # Selling into buyer-dominated book
            if decision == 'PASS':
                decision = 'SIZE_REDUCE'
            size_mult = min(size_mult, 0.7)
            reasons.append(f'ADVERSE_IMBALANCE_SELL:{imbalance:.2f}')
        
        # === GATE 4: LIQUIDITY CHECK ===
        bid_sum = safe_float(depth.get('book_bid_sum_5', 0))
        ask_sum = safe_float(depth.get('book_ask_sum_5', 0))
        total_liquidity = bid_sum + ask_sum
        mid_px = safe_float(depth.get('mid_px', 0))
        
        if mid_px > 0 and total_liquidity > 0:
            # Convert order size to base currency
            our_size_in_base = size_usd / mid_px
            
            # Calculate impact ratio
            impact_ratio = our_size_in_base / total_liquidity if total_liquidity > 0 else 1.0
            
            if impact_ratio > 0.25:
                # Very large relative to book - significant reduction
                if decision == 'PASS':
                    decision = 'SIZE_REDUCE'
                size_mult = min(size_mult, 0.4)
                reasons.append(f'HIGH_IMPACT:{impact_ratio:.1%}')
            elif impact_ratio > 0.10:
                # Moderate impact - small reduction
                if decision == 'PASS':
                    decision = 'SIZE_REDUCE'
                size_mult = min(size_mult, 0.7)
                reasons.append(f'MOD_IMPACT:{impact_ratio:.1%}')
        
        # === GATE 5: QUALITY CHECK ===
        quality_score = safe_float(depth.get('src_quality_score', 1.0), 1.0)
        
        if quality_score < DEPTH_GATE_MIN_QUALITY:
            # Low quality data - reduce size
            if decision == 'PASS':
                decision = 'SIZE_REDUCE'
            size_mult = min(size_mult, 0.75)
            reasons.append(f'LOW_QUALITY:{quality_score:.2f}')
        
        # === GATE 6: CHURN DETECTION ===
        churn_score = safe_float(depth.get('churn_score', 0))
        
        if churn_score > 0.7 and is_entry:
            # High churn - orderbook unstable, delay entry
            if decision == 'PASS':
                decision = 'DELAY'
            delay_sec = max(delay_sec, DEPTH_GATE_DELAY_SECONDS)
            reasons.append(f'HIGH_CHURN:{churn_score:.2f}')
        
        # Build result
        result = GateDecision(
            decision=decision,
            delay_seconds=delay_sec,
            size_multiplier=round(size_mult, 3),
            reasons=reasons if reasons else ['CLEAR'],
            depth_snapshot={
                'mid_px': mid_px,
                'spread': safe_float(depth.get('spread', 0)),
                'imbalance_5': imbalance,
                'spoof_score': spoof_score,
                'fast_move_score': fast_move_score,
                'churn_score': churn_score,
                'quality_score': quality_score,
                'bid_sum_5': bid_sum,
                'ask_sum_5': ask_sum,
                'staleness_ms': staleness_ms,
            },
        )
        
        # Store in history
        self._add_to_history(symbol, action, side, size_usd, result)
        
        # Log decision
        if decision != 'PASS':
            logger.info(
                f"[DepthExecutionGate] {symbol} {action} {side} ${size_usd:.0f}: "
                f"{decision} (delay={delay_sec}s, size_mult={size_mult:.2f}) "
                f"reasons={reasons}"
            )
        else:
            logger.debug(
                f"[DepthExecutionGate] {symbol} {action} {side} ${size_usd:.0f}: PASS"
            )
        
        return result
    
    def _fetch_depth_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch CoinAPI WSDS depth data from Redis."""
        try:
            # Primary source: msnap:coinapi_wsds:{symbol}
            key = f"msnap:coinapi_wsds:{symbol}"
            data = self.redis.hgetall(key)
            
            if data:
                return data
            
            # Fallback: unified_features depth fields
            key = f"unified_features:{symbol}:5m"
            data = self.redis.hgetall(key)
            
            if data:
                # Extract depth_ prefixed fields
                depth_data = {}
                for k, v in data.items():
                    if k.startswith('depth_'):
                        # Remove prefix for consistency
                        clean_key = k.replace('depth_', '')
                        depth_data[clean_key] = v
                
                if depth_data:
                    return depth_data
            
            return None
            
        except Exception as e:
            logger.warning(f"[DepthExecutionGate] Error fetching depth for {symbol}: {e}")
            return None
    
    def _add_to_history(
        self,
        symbol: str,
        action: str,
        side: str,
        size_usd: float,
        result: GateDecision
    ) -> None:
        """Add gate decision to history for debugging."""
        entry = {
            'timestamp': int(time.time() * 1000),
            'symbol': symbol,
            'action': action,
            'side': side,
            'size_usd': size_usd,
            'decision': result.decision,
            'delay_seconds': result.delay_seconds,
            'size_multiplier': result.size_multiplier,
            'reasons': result.reasons,
        }
        
        self.gate_history.append(entry)
        
        # Trim history
        if len(self.gate_history) > self.max_history:
            self.gate_history = self.gate_history[-self.max_history:]
    
    def get_recent_decisions(self, limit: int = 20) -> List[Dict]:
        """Get recent gate decisions for debugging."""
        return self.gate_history[-limit:]
    
    def get_pass_rate(self, window_minutes: int = 60) -> Dict[str, float]:
        """Calculate pass rate statistics."""
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - (window_minutes * 60 * 1000)
        
        recent = [h for h in self.gate_history if h['timestamp'] >= cutoff_ms]
        
        if not recent:
            return {
                'total': 0,
                'pass_rate': 1.0,
                'delay_rate': 0.0,
                'reduce_rate': 0.0,
            }
        
        total = len(recent)
        passes = sum(1 for h in recent if h['decision'] == 'PASS')
        delays = sum(1 for h in recent if h['decision'] == 'DELAY')
        reduces = sum(1 for h in recent if h['decision'] == 'SIZE_REDUCE')
        
        return {
            'total': total,
            'pass_rate': passes / total,
            'delay_rate': delays / total,
            'reduce_rate': reduces / total,
        }


# Singleton instance
_execution_gate: Optional[DepthExecutionGate] = None


def get_execution_gate() -> DepthExecutionGate:
    """Get or create singleton execution gate instance."""
    global _execution_gate
    if _execution_gate is None:
        _execution_gate = DepthExecutionGate()
    return _execution_gate


if __name__ == "__main__":
    # Test the execution gate
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    gate = DepthExecutionGate()
    
    print("\n" + "="*60)
    print("DEPTH EXECUTION GATE TEST")
    print("="*60)
    
    # Test with real data
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    
    for symbol in symbols:
        print(f"\n--- {symbol} ---")
        
        # Test entry
        result = gate.check_execution_gate(
            symbol=symbol,
            action="OPEN_LONG",
            side="BUY",
            size_usd=1000.0,
            is_hedge=False
        )
        
        print(f"  OPEN_LONG $1000:")
        print(f"    Decision: {result.decision}")
        print(f"    Delay: {result.delay_seconds}s")
        print(f"    Size Mult: {result.size_multiplier}")
        print(f"    Reasons: {result.reasons}")
        
        if result.depth_snapshot:
            print(f"    Depth: mid={result.depth_snapshot.get('mid_px', 0):.2f}, "
                  f"imb={result.depth_snapshot.get('imbalance_5', 0):.2f}, "
                  f"spoof={result.depth_snapshot.get('spoof_score', 0):.2f}")
    
    # Show pass rate
    print("\n--- Pass Rate (simulated) ---")
    stats = gate.get_pass_rate()
    print(f"  Total checks: {stats['total']}")
    print(f"  Pass rate: {stats['pass_rate']:.1%}")
    print(f"  Delay rate: {stats['delay_rate']:.1%}")
    print(f"  Reduce rate: {stats['reduce_rate']:.1%}")
