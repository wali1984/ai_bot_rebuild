"""
Intrabar Squeeze Fast-Lane Detector (1m Protective-Only)

Production-safe event detection for fast-lane protective actions.
NO NEW ENTRIES when flat - only protect existing positions during extreme events.

Author: WMA AI Trading System
"""

import time
import hashlib
import logging
from typing import Dict, Optional, List, Tuple
from collections import defaultdict, deque

logger = logging.getLogger('hybrid_trainer.fastlane')


class FastLaneEventDetector:
    """
    Detects intrabar events that trigger protective fast-lane actions.
    
    Event types:
    - SQUEEZE_UP: Rapid upward price movement with volume/liquidations
    - SQUEEZE_DOWN: Rapid downward price movement with volume/liquidations
    - LIQ_BURST: Large liquidation cluster
    - SPREAD_SHOCK: Orderbook spread widening
    - WICK_REVERSAL: Sharp reversal after wick formation
    """
    
    def __init__(self, config):
        self.config = config
        
        # Counters for monitoring (in-memory only)
        self.stats = {
            'events_detected': 0,
            'signals_emitted': 0,
            'signals_suppressed': 0,
            'hedge_opens_emitted': 0,
            'close_reduce_emitted': 0,
        }
        
        # Price history ring buffer for fallback calculations (symbol -> deque of (ts, price))
        self._price_history = {}
        
        logger.info("[FASTLANE] Detector initialized with protective-only mode (Redis-backed anti-spam)")
    
    def get_intrabar_state(self, symbol: str, redis_client=None, 
                           price_history: Optional[List[Tuple[float, float]]] = None) -> Dict:
        """
        Pull microstructure features for intrabar event detection.
        
        Fail-closed: Returns {"ok": False} if insufficient data.
        
        Args:
            symbol: Trading symbol
            redis_client: Redis client for feature access
            price_history: Optional list of (timestamp, price) tuples for last 60s
            
        Returns:
            dict with normalized intrabar state
        """
        state = {
            "ok": False,  # Will be set to True if we have sufficient data
            "ret_15s": 0.0,
            "ret_30s": 0.0,
            "ret_60s": 0.0,
            "vol_burst": 0.0,
            "liq_burst_usd": 0.0,
            "spread_pct": 0.0,
            "imbalance": 0.0,
            "ts_ms": int(time.time() * 1000)
        }
        
        has_sufficient_data = False
        
        try:
            # Try to get current price for ring buffer
            current_price = None
            if redis_client:
                # Try tick key first, then 1m close
                tick_key = f"tick:{symbol}:price"
                price_str = redis_client.get(tick_key)
                if price_str:
                    try:
                        current_price = float(price_str)
                    except:
                        pass
            
            # Update price history ring buffer
            if current_price:
                if symbol not in self._price_history:
                    self._price_history[symbol] = deque(maxlen=120)  # 2 minutes of second data
                self._price_history[symbol].append((time.time(), current_price))
            
            # Try to get microstructure features from Redis
            if redis_client:
                # Check for pre-computed microstructure features
                micro_key = f"microstructure:{symbol}:1m"
                micro_data = redis_client.hgetall(micro_key)
                
                if micro_data:
                    # Parse microstructure data
                    state["ret_15s"] = float(micro_data.get(b'ret_15s', micro_data.get('ret_15s', 0)) or 0)
                    state["ret_30s"] = float(micro_data.get(b'ret_30s', micro_data.get('ret_30s', 0)) or 0)
                    state["ret_60s"] = float(micro_data.get(b'ret_60s', micro_data.get('ret_60s', 0)) or 0)
                    state["vol_burst"] = float(micro_data.get(b'vol_burst_15s', micro_data.get('vol_burst_15s', 0)) or 0)
                    
                    # Check staleness
                    feature_ts = int(micro_data.get(b'ts_ms', micro_data.get('ts_ms', 0)) or 0)
                    if feature_ts > 0:
                        age_sec = (state["ts_ms"] - feature_ts) / 1000.0
                        if age_sec <= 30:  # Not stale if <= 30s old
                            has_sufficient_data = True
                
                # Get liquidation data
                liq_key = f"liquidations:{symbol}:30s"
                liq_data = redis_client.get(liq_key)
                if liq_data:
                    try:
                        state["liq_burst_usd"] = float(liq_data)
                    except:
                        pass
                
                # Get orderbook data
                ob_key = f"orderbook:{symbol}:snapshot"
                ob_data = redis_client.hgetall(ob_key)
                if ob_data:
                    try:
                        spread = float(ob_data.get(b'spread_pct', ob_data.get('spread_pct', 0)) or 0)
                        imbalance = float(ob_data.get(b'imbalance', ob_data.get('imbalance', 0)) or 0)
                        state["spread_pct"] = spread
                        state["imbalance"] = imbalance
                    except:
                        pass
            
            # Fallback: calculate from price ring buffer if no Redis data
            if not has_sufficient_data and symbol in self._price_history and len(self._price_history[symbol]) >= 2:
                price_hist = list(self._price_history[symbol])
                current_price = price_hist[-1][1]
                current_ts = price_hist[-1][0]
                
                # Calculate returns at different windows
                for ts, price in reversed(price_hist[:-1]):
                    age = current_ts - ts
                    
                    if age <= 15 and state["ret_15s"] == 0.0:
                        state["ret_15s"] = (current_price - price) / price if price > 0 else 0.0
                    if age <= 30 and state["ret_30s"] == 0.0:
                        state["ret_30s"] = (current_price - price) / price if price > 0 else 0.0
                    if age <= 60 and state["ret_60s"] == 0.0:
                        state["ret_60s"] = (current_price - price) / price if price > 0 else 0.0
                
                # If we got at least one return, consider it sufficient
                if state["ret_15s"] != 0.0 or state["ret_30s"] != 0.0:
                    has_sufficient_data = True
            
            # Fallback: use provided price_history
            if not has_sufficient_data and price_history and len(price_history) >= 2:
                current_price = price_history[-1][1]
                
                for ts, price in reversed(price_history[:-1]):
                    age = state["ts_ms"] / 1000.0 - ts
                    
                    if age <= 15 and state["ret_15s"] == 0.0:
                        state["ret_15s"] = (current_price - price) / price if price > 0 else 0.0
                    if age <= 30 and state["ret_30s"] == 0.0:
                        state["ret_30s"] = (current_price - price) / price if price > 0 else 0.0
                    if age <= 60 and state["ret_60s"] == 0.0:
                        state["ret_60s"] = (current_price - price) / price if price > 0 else 0.0
                
                if state["ret_15s"] != 0.0 or state["ret_30s"] != 0.0:
                    has_sufficient_data = True
        
        except Exception as e:
            logger.debug(f"[FASTLANE] Error getting intrabar state for {symbol}: {e}")
            has_sufficient_data = False
        
        state["ok"] = has_sufficient_data
        return state
    
    def detect_fastlane_event(self, symbol: str, intrabar_state: Dict, 
                             has_position: bool, current_pos: Optional[Dict] = None) -> Optional[Dict]:
        """
        Detect if an intrabar event warrants fast-lane protective action.
        
        Args:
            symbol: Trading symbol
            intrabar_state: Output from get_intrabar_state()
            has_position: Whether we have an open position
            current_pos: Current position details (side, pnl_pct, etc.)
            
        Returns:
            Event dict if triggered, None otherwise
        """
        # CRITICAL: No events if no position (protective-only)
        if not has_position:
            return None
        
        # Fail-closed: Don't trigger if insufficient data
        if not intrabar_state.get("ok", False):
            logger.debug(f"[FASTLANE] {symbol} - insufficient data, skipping event detection")
            return None
        
        # Extract thresholds from config
        ret_15s_thresh = getattr(self.config, 'FASTLANE_RET15_UP', 0.006)
        vol_burst_thresh = getattr(self.config, 'FASTLANE_VOL_BURST', 2.0)
        liq_burst_thresh = getattr(self.config, 'FASTLANE_LIQ_BURST_USD', 250000)
        spread_shock_thresh = getattr(self.config, 'FASTLANE_SPREAD_SHOCK_PCT', 0.002)
        
        # Extract state
        ret_15s = abs(intrabar_state.get("ret_15s", 0.0))
        ret_30s = abs(intrabar_state.get("ret_30s", 0.0))
        ret_60s = abs(intrabar_state.get("ret_60s", 0.0))
        vol_burst = intrabar_state.get("vol_burst", 0.0)
        liq_burst = intrabar_state.get("liq_burst_usd", 0.0)
        spread_pct = intrabar_state.get("spread_pct", 0.0)
        
        # Determine direction
        direction = None
        if intrabar_state.get("ret_15s", 0.0) > 0:
            direction = "UP"
        elif intrabar_state.get("ret_15s", 0.0) < 0:
            direction = "DOWN"
        
        # Event detection logic
        event_type = None
        severity = 0.0
        trigger_reasons = []
        
        # Check for price squeeze (rapid movement)
        price_squeeze = False
        if ret_15s >= ret_15s_thresh:
            price_squeeze = True
            severity = max(severity, min(1.0, ret_15s / ret_15s_thresh))
            trigger_reasons.append(f"ret_15s={intrabar_state.get('ret_15s', 0.0):.4f}")
        
        # Check for volume/liquidation confirmation
        has_confirmation = False
        if vol_burst >= vol_burst_thresh:
            has_confirmation = True
            severity = max(severity, min(1.0, vol_burst / vol_burst_thresh / 2))
            trigger_reasons.append(f"vol_burst={vol_burst:.2f}x")
        
        if liq_burst >= liq_burst_thresh:
            has_confirmation = True
            severity = max(severity, min(1.0, liq_burst / liq_burst_thresh))
            trigger_reasons.append(f"liq_burst=${liq_burst/1000:.0f}k")
        
        if spread_pct >= spread_shock_thresh:
            has_confirmation = True
            severity = max(severity, min(1.0, spread_pct / spread_shock_thresh))
            trigger_reasons.append(f"spread_shock={spread_pct:.4f}")
        
        # Determine event type
        if price_squeeze and has_confirmation:
            if direction == "UP":
                event_type = "SQUEEZE_UP"
            elif direction == "DOWN":
                event_type = "SQUEEZE_DOWN"
            else:
                event_type = "SQUEEZE_UNKNOWN"
        elif liq_burst >= liq_burst_thresh:
            event_type = "LIQ_BURST"
        elif spread_pct >= spread_shock_thresh:
            event_type = "SPREAD_SHOCK"
        
        # No event if no triggers
        if not event_type or severity < 0.3:  # Minimum severity threshold
            return None
        
        # Generate stable event_id for deduplication (simpler format per spec)
        # Format: symbol:event_type:second_bucket
        second_bucket = int(intrabar_state['ts_ms'] / 1000)
        event_id = f"{symbol}:{event_type}:{second_bucket}"
        
        event = {
            "event_type": event_type,
            "direction": direction,
            "severity": severity,
            "trigger_reasons": trigger_reasons,
            "event_id": event_id,
            "ts_ms": intrabar_state.get("ts_ms", int(time.time() * 1000)),
            "intrabar_snapshot": intrabar_state  # Include full state
        }
        
        self.stats['events_detected'] += 1
        logger.info(f"[FASTLANE] EVENT DETECTED: {symbol} {event_type} severity={severity:.2f} reasons={trigger_reasons}")
        
        return event
    
    def should_emit_signal(self, symbol: str, event: Dict, current_pos: Optional[Dict] = None, 
                           redis_client=None) -> Tuple[bool, str]:
        """
        Check anti-spam controls to determine if signal should be emitted.
        
        Uses Redis for persistent state across restarts.
        
        Args:
            symbol: Trading symbol
            event: Event dict from detect_fastlane_event()
            current_pos: Current position details
            redis_client: Redis client for persistent storage
            
        Returns:
            (should_emit, reason)
        """
        if not redis_client:
            # No Redis - allow but warn
            logger.warning("[FASTLANE] No Redis client - anti-spam disabled")
            return True, "NO_REDIS"
        
        now = time.time()
        event_id = event["event_id"]
        severity = event["severity"]
        spread_pct = event.get("intrabar_snapshot", {}).get("spread_pct", 0.0)
        
        # Rule 1: Dedupe - same event_id
        last_event_key = f"fastlane:last_event:{symbol}"
        last_event_id = redis_client.get(last_event_key)
        if last_event_id:
            if isinstance(last_event_id, bytes):
                last_event_id = last_event_id.decode()
            if last_event_id == event_id:
                self.stats['signals_suppressed'] += 1
                return False, f"DEDUPE (same event_id)"
        
        # Rule 2: Cooldown - recently emitted
        last_emit_key = f"fastlane:last_emit_ts:{symbol}"
        last_emit_ts_str = redis_client.get(last_emit_key)
        if last_emit_ts_str:
            try:
                last_emit_ts = float(last_emit_ts_str)
                time_since = now - last_emit_ts
                cooldown = getattr(self.config, 'FASTLANE_COOLDOWN_SEC', 45)
                if time_since < cooldown:
                    # Only allow if this is an extreme event
                    extreme_severity = getattr(self.config, 'FASTLANE_EXTREME_SEVERITY', 0.9)
                    if severity < extreme_severity:
                        self.stats['signals_suppressed'] += 1
                        return False, f"COOLDOWN ({time_since:.1f}s < {cooldown}s)"
            except:
                pass
        
        # Rule 3: Rate limit - max N emits per hour
        rate_limit_key = f"fastlane:rate_limit:{symbol}"
        emit_count = 0
        try:
            emit_count_str = redis_client.get(rate_limit_key)
            if emit_count_str:
                emit_count = int(emit_count_str)
        except:
            pass
        
        max_per_hour = getattr(self.config, 'FASTLANE_RATE_LIMIT_PER_HOUR', 20)
        extreme_severity = getattr(self.config, 'FASTLANE_EXTREME_SEVERITY', 0.9)
        if emit_count >= max_per_hour:
            # Only allow if extreme severity
            if severity < extreme_severity:
                self.stats['signals_suppressed'] += 1
                return False, f"RATE_LIMIT ({emit_count}/{max_per_hour} per hour)"
        
        # Rule 4: Spread check - wide spread => only allow if extreme OR reduce/close only
        max_spread = getattr(self.config, 'FASTLANE_MAX_SPREAD_PCT', 0.0015)
        if spread_pct > max_spread:
            if severity < extreme_severity:
                self.stats['signals_suppressed'] += 1
                return False, f"SPREAD_TOO_WIDE ({spread_pct:.4f} > {max_spread:.4f})"
        
        # Passed all checks
        return True, "EMIT_ALLOWED"
    
    def record_emit(self, symbol: str, event: Dict, redis_client=None):
        """
        Record that a signal was emitted for anti-spam tracking.
        
        Uses Redis for persistent state.
        
        Args:
            symbol: Trading symbol
            event: Event dict
            redis_client: Redis client for persistent storage
        """
        if not redis_client:
            logger.warning("[FASTLANE] No Redis client - cannot record emit")
            return
        
        now = time.time()
        event_id = event["event_id"]
        
        try:
            # Update last event ID (with TTL)
            last_event_key = f"fastlane:last_event:{symbol}"
            cooldown = getattr(self.config, 'FASTLANE_COOLDOWN_SEC', 45)
            redis_client.setex(last_event_key, cooldown * 2, event_id)  # TTL = 2x cooldown
            
            # Update last emit timestamp (with TTL)
            last_emit_key = f"fastlane:last_emit_ts:{symbol}"
            redis_client.setex(last_emit_key, cooldown * 2, str(now))
            
            # Increment rate limit counter (with 1 hour TTL)
            rate_limit_key = f"fastlane:rate_limit:{symbol}"
            redis_client.incr(rate_limit_key)
            redis_client.expire(rate_limit_key, 3600)  # 1 hour TTL
            
            self.stats['signals_emitted'] += 1
            
        except Exception as e:
            logger.error(f"[FASTLANE] Failed to record emit: {e}")
    
    def get_stats(self) -> Dict:
        """Get detector statistics."""
        return dict(self.stats)
    
    def log_stats(self):
        """Log periodic statistics."""
        logger.info(
            f"[FASTLANE] STATS: events={self.stats['events_detected']} "
            f"emitted={self.stats['signals_emitted']} suppressed={self.stats['signals_suppressed']} "
            f"hedge_opens={self.stats['hedge_opens_emitted']} close_reduce={self.stats['close_reduce_emitted']}"
        )

